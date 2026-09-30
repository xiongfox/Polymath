"""LangGraph 博物馆讲解工作流。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agent.conversation_context import derive_context_from_messages
from agent.intent import IntentRecognizer
from agent.prompts import build_guide_messages
from agent.relic_matcher import format_disambiguation_prompt, is_pending_selection_reply
from agent.state import AgentState, IntentType
from agent.wiki_index import WikiIndex
from agent.wiki_loader import load_wiki_for_intent

DEFAULT_WIKI_ROOT = Path(__file__).resolve().parent.parent / "wiki"


def build_graph(
    wiki_root: Path | str | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
):
    wiki_path = Path(wiki_root or os.getenv("WIKI_ROOT", DEFAULT_WIKI_ROOT))
    model_name = model or os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_base = base_url or os.getenv("OLLAMA_BASE_URL")

    wiki_index = WikiIndex.build(wiki_path)
    intent_recognizer = IntentRecognizer(
        wiki_index, model=model_name, base_url=ollama_base
    )
    chat_llm = ChatOllama(model=model_name, base_url=ollama_base, temperature=0.3)

    def recognize_intent(state: AgentState) -> dict:
        messages = state.get("messages") or []
        user_query = state.get("user_query") or _last_human_text(messages)
        use_llm = os.getenv("MUSEUM_AGENT_NO_LLM_INTENT", "") != "1"
        prior_messages = messages[:-1] if messages else []
        conv_ctx = (
            derive_context_from_messages(
                wiki_index, state.get("current_museum") or "", prior_messages
            )
            if prior_messages
            else None
        )
        intent_result = intent_recognizer.recognize(
            user_query,
            current_museum=state.get("current_museum"),
            history_messages=prior_messages if prior_messages else None,
            use_llm_fallback=use_llm,
        )
        updates: dict = {"intent_result": intent_result, "user_query": user_query}
        if intent_result.get("needs_disambiguation"):
            updates["pending_relic_choices"] = intent_result.get("relic_candidates")
            updates["pending_relic_prefix"] = intent_result.get("relic_prefix")
            if not is_pending_selection_reply(user_query):
                updates["pending_user_question"] = user_query
        elif intent_result.get("intent") == IntentType.CULTURAL_RELIC.value:
            updates["pending_relic_choices"] = None
            updates["pending_relic_prefix"] = None
            pending_q = None
            if conv_ctx:
                pending_q = conv_ctx.pending_user_question
            pending_q = pending_q or state.get("pending_user_question")
            if pending_q and is_pending_selection_reply(user_query):
                updates["user_query"] = pending_q
            updates["pending_user_question"] = None
        elif intent_result.get("intent") in {
            IntentType.MUSEUM_OVERVIEW.value,
            IntentType.EXHIBITION.value,
            IntentType.SWITCH_MUSEUM.value,
            IntentType.GENERAL.value,
        }:
            updates["pending_relic_choices"] = None
            updates["pending_relic_prefix"] = None
            updates["pending_user_question"] = None
        return updates

    def update_session_context(state: AgentState) -> dict:
        ir = state.get("intent_result") or {}
        if ir.get("needs_disambiguation"):
            return {}

        focus = ir.get("focus") or {}
        intent = ir.get("intent")
        updates: dict = {}

        museum = focus.get("museum")
        if intent == IntentType.SWITCH_MUSEUM.value and museum:
            updates["current_museum"] = museum
        elif museum:
            updates["current_museum"] = museum

        if focus.get("exhibition"):
            updates["last_exhibition"] = focus["exhibition"]
        relics = focus.get("cultural_relics") or []
        if focus.get("cultural_relic"):
            updates["last_cultural_relic"] = focus["cultural_relic"]
        elif relics:
            updates["last_cultural_relic"] = relics[0]

        return updates

    def clarify_relic_choice(state: AgentState) -> dict:
        ir = state.get("intent_result") or {}
        prefix = ir.get("relic_prefix")
        candidates = ir.get("relic_candidates") or []
        body = format_disambiguation_prompt(prefix, candidates)
        meta = _format_meta_line(ir, [])
        return {"messages": [AIMessage(content=f"{body}\n\n{meta}")]}

    def load_wiki(state: AgentState) -> dict:
        ir = state.get("intent_result")
        if not ir:
            return {"wiki_context": "", "wiki_paths": []}
        context, paths = load_wiki_for_intent(wiki_index, ir)
        return {"wiki_context": context, "wiki_paths": paths}

    def generate_answer(state: AgentState) -> dict:
        ir = state.get("intent_result") or {}
        focus = ir.get("focus") or {}
        messages = state.get("messages") or []
        history = messages[:-1] if messages else []
        user_query = state.get("user_query") or _last_human_text(messages)

        relics = focus.get("cultural_relics") or []
        relic_label = focus.get("cultural_relic") or (
            "、".join(relics) if relics else state.get("last_cultural_relic")
        )
        guide_messages = build_guide_messages(
            museum=state.get("current_museum") or focus.get("museum"),
            exhibition=focus.get("exhibition") or state.get("last_exhibition"),
            relic=relic_label,
            intent=ir.get("intent", "general"),
            reasoning=ir.get("reasoning", ""),
            wiki_context=state.get("wiki_context") or "",
            history=history,
            user_query=user_query,
        )
        response = chat_llm.invoke(guide_messages)
        content = response.content if hasattr(response, "content") else str(response)
        meta = _format_meta_line(ir, state.get("wiki_paths") or [])
        full = f"{content}\n\n{meta}" if meta else content
        return {"messages": [AIMessage(content=full)]}

    def route_after_intent(state: AgentState) -> Literal["clarify", "continue"]:
        ir = state.get("intent_result") or {}
        if ir.get("needs_disambiguation"):
            return "clarify"
        return "continue"

    graph = StateGraph(AgentState)
    graph.add_node("recognize_intent", recognize_intent)
    graph.add_node("update_session_context", update_session_context)
    graph.add_node("clarify_relic_choice", clarify_relic_choice)
    graph.add_node("load_wiki", load_wiki)
    graph.add_node("generate_answer", generate_answer)

    graph.add_edge(START, "recognize_intent")
    graph.add_conditional_edges(
        "recognize_intent",
        route_after_intent,
        {"clarify": "clarify_relic_choice", "continue": "update_session_context"},
    )
    graph.add_edge("clarify_relic_choice", END)
    graph.add_edge("update_session_context", "load_wiki")
    graph.add_edge("load_wiki", "generate_answer")
    graph.add_edge("generate_answer", END)

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


def create_agent(**kwargs):
    """构建可 invoke 的编译图（带多轮 memory）。"""
    return build_graph(**kwargs)


def _last_human_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, dict) and m.get("role") == "user":
            return m.get("content", "")
    return ""


def _format_meta_line(intent_result: dict, wiki_paths: list[str]) -> str:
    focus = intent_result.get("focus") or {}
    parts = [
        f"〔意图:{intent_result.get('intent')}｜"
        f"博物馆:{focus.get('museum') or '-'}｜"
        f"展厅:{focus.get('exhibition') or '-'}｜"
        f"文物:{focus.get('cultural_relic') or '-'}｜"
        f"置信:{intent_result.get('confidence', 0):.2f}〕",
    ]
    if intent_result.get("relic_candidates"):
        n = len(intent_result["relic_candidates"])
        parts.append(f"〔待选文物:{n}件〕")
    if wiki_paths:
        short = ", ".join(Path(p).name for p in wiki_paths[:3])
        parts.append(f"〔Wiki:{short}〕")
    return "".join(parts)
