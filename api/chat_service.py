"""博物馆对话服务（流式 / 非流式，基于 history 的意图识别）。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage

from agent.bundle import AgentBundle, create_agent_bundle
from agent.conversation_context import derive_context_from_history
from agent.prompts import build_guide_messages
from agent.relic_matcher import format_disambiguation_prompt, is_pending_selection_reply
from agent.state import IntentType
from agent.wiki_loader import load_wiki_for_intent
from api.schemas import ChatMessage, ChatRequest


def _history_to_messages(history: list[ChatMessage]) -> list:
    msgs = []
    for item in history:
        if item.role == "user":
            msgs.append(HumanMessage(content=item.content))
        else:
            msgs.append(AIMessage(content=item.content))
    return msgs


def _apply_recognize_updates(
    state: dict, intent_result: dict, user_query: str, pending_user_question: str | None
) -> None:
    state["intent_result"] = intent_result
    state["user_query"] = user_query

    if intent_result.get("needs_disambiguation"):
        state["pending_relic_choices"] = intent_result.get("relic_candidates")
        state["pending_relic_prefix"] = intent_result.get("relic_prefix")
        if not is_pending_selection_reply(user_query):
            state["pending_user_question"] = user_query
    elif intent_result.get("intent") == IntentType.CULTURAL_RELIC.value:
        state["pending_relic_choices"] = None
        state["pending_relic_prefix"] = None
        if pending_user_question and is_pending_selection_reply(user_query):
            state["user_query"] = pending_user_question
        state["pending_user_question"] = None
    else:
        state["pending_relic_choices"] = None
        state["pending_relic_prefix"] = None
        state["pending_user_question"] = None


def _apply_context_updates(state: dict) -> None:
    ir = state.get("intent_result") or {}
    if ir.get("needs_disambiguation"):
        return

    focus = ir.get("focus") or {}
    museum = focus.get("museum")
    if museum:
        state["current_museum"] = museum

    if focus.get("exhibition"):
        state["last_exhibition"] = focus["exhibition"]
    relics = focus.get("cultural_relics") or []
    if focus.get("cultural_relic"):
        state["last_cultural_relic"] = focus["cultural_relic"]
    elif relics:
        state["last_cultural_relic"] = relics[0]


def _build_initial_state(req: ChatRequest, bundle: AgentBundle) -> dict:
    history_messages = _history_to_messages(req.history)
    ctx = derive_context_from_history(
        bundle.wiki_index,
        req.museum_name,
        req.history,
    )
    messages = list(history_messages)
    messages.append(HumanMessage(content=req.question))
    return {
        "messages": messages,
        "history_messages": history_messages,
        "user_query": req.question,
        "current_museum": req.museum_name,
        "conversation_ctx": ctx,
        "last_exhibition": ctx.last_exhibition,
        "last_cultural_relic": ctx.last_cultural_relic,
        "pending_relic_choices": ctx.pending_relic_choices,
        "pending_relic_prefix": ctx.pending_relic_prefix,
        "pending_user_question": ctx.pending_user_question,
        "intent_result": None,
        "wiki_context": "",
        "wiki_paths": [],
    }


def _run_intent_and_wiki(bundle: AgentBundle, state: dict) -> str | None:
    """执行意图识别与 Wiki 加载。若需消歧则返回引导文案，否则返回 None。"""
    ctx = state.get("conversation_ctx")
    pending_q = ctx.pending_user_question if ctx else state.get("pending_user_question")

    use_llm = os.getenv("MUSEUM_AGENT_NO_LLM_INTENT", "") != "1"
    intent_result = bundle.intent_recognizer.recognize(
        state["user_query"],
        current_museum=state.get("current_museum"),
        history_messages=state.get("history_messages") or None,
        use_llm_fallback=use_llm,
    )
    _apply_recognize_updates(
        state, intent_result, state["user_query"], pending_q
    )
    _apply_context_updates(state)

    if intent_result.get("needs_disambiguation"):
        prefix = intent_result.get("relic_prefix")
        candidates = intent_result.get("relic_candidates") or []
        state["wiki_context"] = ""
        state["wiki_paths"] = []
        return format_disambiguation_prompt(prefix, candidates)

    wiki_context, wiki_paths = load_wiki_for_intent(
        bundle.wiki_index, intent_result
    )
    state["wiki_context"] = wiki_context
    state["wiki_paths"] = wiki_paths
    return None


def _build_llm_messages(bundle: AgentBundle, state: dict) -> list:
    ir = state.get("intent_result") or {}
    focus = ir.get("focus") or {}
    messages = state.get("messages") or []
    history = messages[:-1] if messages else []
    user_query = state.get("user_query") or ""

    relics = focus.get("cultural_relics") or []
    relic_label = focus.get("cultural_relic") or (
        "、".join(relics) if relics else state.get("last_cultural_relic")
    )
    return build_guide_messages(
        museum=state.get("current_museum") or focus.get("museum"),
        exhibition=focus.get("exhibition") or state.get("last_exhibition"),
        relic=relic_label,
        intent=ir.get("intent", "general"),
        reasoning=ir.get("reasoning", ""),
        wiki_context=state.get("wiki_context") or "",
        history=history,
        user_query=user_query,
    )


async def chat(req: ChatRequest, *, bundle: AgentBundle | None = None) -> str:
    """非流式：仅返回助手回复正文。"""
    bundle = bundle or create_agent_bundle()
    state = _build_initial_state(req, bundle)
    clarify = _run_intent_and_wiki(bundle, state)
    if clarify:
        return clarify

    guide_messages = _build_llm_messages(bundle, state)
    response = bundle.chat_llm.invoke(guide_messages)
    content = response.content if hasattr(response, "content") else str(response)
    return content if isinstance(content, str) else str(content)


async def chat_stream(
    req: ChatRequest,
    *,
    bundle: AgentBundle | None = None,
) -> AsyncIterator[str]:
    """流式：逐段输出 UTF-8 文本（无 JSON 包装）。"""
    bundle = bundle or create_agent_bundle()
    state = _build_initial_state(req, bundle)
    clarify = _run_intent_and_wiki(bundle, state)
    if clarify:
        yield clarify
        return

    guide_messages = _build_llm_messages(bundle, state)
    async for chunk in bundle.chat_llm.astream(guide_messages):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        if text:
            yield text if isinstance(text, str) else str(text)
