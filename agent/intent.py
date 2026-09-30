"""意图识别：规则解析 + LLM 结构化补全。"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from agent.conversation_context import ConversationContext, derive_context_from_messages
from agent.entity_resolver import EntityResolver, ResolveOutcome
from agent.state import IntentResult, IntentType

if TYPE_CHECKING:
    from agent.wiki_index import WikiIndex

logger = logging.getLogger(__name__)

INTENT_LABELS = {e.value: e for e in IntentType}


class LLMIntentOutput(BaseModel):
    intent: str = Field(
        description="switch_museum | museum_overview | exhibition | cultural_relic | general"
    )
    museum: str | None = None
    exhibition: str | None = None
    cultural_relic: str | None = None
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""


INTENT_SYSTEM = """你是博物馆讲解系统的意图识别模块。根据用户问题和上下文，判断意图并提取主体。

## 意图类型（必须选其一）
- switch_museum：切换/选择博物馆（如「换个博物馆」「有哪些博物馆」）
- museum_overview：博物馆整体介绍、展厅列表、开放信息等（未指向具体文物或单一展厅细节）
- exhibition：展厅相关问题（展厅位置、展厅内有哪些文物）；注意：若用户问的是「某件文物在哪个展厅」，intent 必须是 cultural_relic
- cultural_relic：围绕具体文物的讲解、年代、工艺、价值，以及该文物位于哪个展厅
- general：无法归类或与文博无关

## 主体提取规则（极其重要）
1. museum：用户明确提到的博物馆名，或可从文物/展厅反推的博物馆；无则 null
2. exhibition：用户提到的展厅名（如「历史馆1展厅」）；无则 null
3. cultural_relic：用户提到的文物/展品名称；无则 null
4. 文物名 > 展厅名 > 博物馆名：同时出现时，以最小粒度主体为准定 intent
5. 仅能从给定候选列表中选择实体名，不要编造 Wiki 中不存在的名称
6. 指代「它/这件」时，结合上一轮文物/展厅补全

只输出 JSON，不要 markdown。"""


class IntentRecognizer:
    def __init__(
        self,
        wiki_index: WikiIndex,
        *,
        model: str = "qwen3:8b",
        base_url: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.resolver = EntityResolver(wiki_index)
        self.llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)

    def recognize(
        self,
        query: str,
        *,
        current_museum: str | None,
        last_exhibition: str | None = None,
        last_cultural_relic: str | None = None,
        pending_relic_choices: list[str] | None = None,
        pending_relic_prefix: str | None = None,
        history_messages: list[BaseMessage] | None = None,
        use_llm_fallback: bool = True,
    ) -> IntentResult:
        ctx = self._resolve_session_context(
            query,
            current_museum=current_museum,
            last_exhibition=last_exhibition,
            last_cultural_relic=last_cultural_relic,
            pending_relic_choices=pending_relic_choices,
            pending_relic_prefix=pending_relic_prefix,
            history_messages=history_messages,
        )
        outcome = self.resolver.resolve(
            query,
            current_museum=ctx.current_museum,
            last_exhibition=ctx.last_exhibition,
            last_cultural_relic=ctx.last_cultural_relic,
            pending_relic_choices=ctx.pending_relic_choices,
            pending_relic_prefix=ctx.pending_relic_prefix,
        )
        return self._from_outcome(
            outcome,
            query,
            use_llm_fallback=use_llm_fallback,
            current_museum=ctx.current_museum,
            last_exhibition=ctx.last_exhibition,
            last_cultural_relic=ctx.last_cultural_relic,
            pending_relic_choices=ctx.pending_relic_choices,
            pending_relic_prefix=ctx.pending_relic_prefix,
            pending_user_question=ctx.pending_user_question,
            history_messages=history_messages,
        )

    def _resolve_session_context(
        self,
        query: str,
        *,
        current_museum: str | None,
        last_exhibition: str | None,
        last_cultural_relic: str | None,
        pending_relic_choices: list[str] | None,
        pending_relic_prefix: str | None,
        history_messages: list[BaseMessage] | None,
    ) -> ConversationContext:
        """优先从历史消息推导上下文；无历史时使用显式字段（CLI 兼容）。"""
        if history_messages:
            derived = derive_context_from_messages(
                self.resolver.index,
                current_museum or "",
                history_messages,
            )
            if last_exhibition:
                derived.last_exhibition = last_exhibition
            if last_cultural_relic:
                derived.last_cultural_relic = last_cultural_relic
            if pending_relic_choices:
                derived.pending_relic_choices = pending_relic_choices
                derived.pending_relic_prefix = pending_relic_prefix
            return derived

        return ConversationContext(
            current_museum=current_museum,
            last_exhibition=last_exhibition,
            last_cultural_relic=last_cultural_relic,
            pending_relic_choices=pending_relic_choices,
            pending_relic_prefix=pending_relic_prefix,
        )

    def _from_outcome(
        self,
        outcome: ResolveOutcome,
        query: str,
        *,
        use_llm_fallback: bool,
        current_museum: str | None = None,
        last_exhibition: str | None = None,
        last_cultural_relic: str | None = None,
        pending_relic_choices: list[str] | None = None,
        pending_relic_prefix: str | None = None,
        pending_user_question: str | None = None,
        history_messages: list[BaseMessage] | None = None,
    ) -> IntentResult:
        if outcome.needs_disambiguation:
            return {
                "intent": outcome.intent.value,
                "focus": outcome.focus,
                "confidence": 0.98,
                "reasoning": outcome.reasoning,
                "rule_matched": True,
                "needs_disambiguation": True,
                "relic_candidates": outcome.relic_candidates,
                "relic_prefix": outcome.relic_prefix,
            }

        if outcome.rule_matched:
            return {
                "intent": outcome.intent.value,
                "focus": outcome.focus,
                "confidence": 0.95,
                "reasoning": outcome.reasoning,
                "rule_matched": True,
                "needs_disambiguation": False,
            }

        if not use_llm_fallback:
            return {
                "intent": outcome.intent.value,
                "focus": outcome.focus,
                "confidence": 0.5,
                "reasoning": outcome.reasoning,
                "rule_matched": False,
                "needs_disambiguation": False,
            }

        return self._llm_recognize(
            query,
            current_museum=current_museum,
            last_exhibition=last_exhibition,
            last_cultural_relic=last_cultural_relic,
            pending_relic_choices=pending_relic_choices or (
                outcome.relic_candidates if outcome.needs_disambiguation else None
            ),
            history_messages=history_messages,
            rule_hint=outcome,
        )

    def _llm_recognize(
        self,
        query: str,
        *,
        current_museum: str | None,
        last_exhibition: str | None,
        last_cultural_relic: str | None,
        pending_relic_choices: list[str] | None = None,
        history_messages: list[BaseMessage] | None = None,
        rule_hint: ResolveOutcome,
    ) -> IntentResult:
        rule_intent = rule_hint.intent
        rule_focus = rule_hint.focus
        rule_reason = rule_hint.reasoning
        context = self.resolver.build_llm_context(
            query,
            current_museum=current_museum,
            last_exhibition=last_exhibition,
            last_cultural_relic=last_cultural_relic,
            pending_relic_choices=pending_relic_choices,
        )
        history_block = _format_history_for_intent(history_messages)

        user_prompt = f"""{context}
{history_block}
规则层初步判断：intent={rule_intent.value}，reason={rule_reason}
focus={json.dumps(rule_focus, ensure_ascii=False)}

用户问题：{query}

请输出 JSON 字段：intent, museum, exhibition, cultural_relic, confidence, reasoning"""

        try:
            structured = self.llm.with_structured_output(LLMIntentOutput)
            out: LLMIntentOutput = structured.invoke(
                [
                    SystemMessage(content=INTENT_SYSTEM),
                    HumanMessage(content=user_prompt),
                ]
            )
            focus = self.resolver.clamp_focus(
                {
                    "museum": out.museum or rule_focus.get("museum"),
                    "exhibition": out.exhibition,
                    "cultural_relic": out.cultural_relic,
                }
            )
            intent_key = out.intent if out.intent in INTENT_LABELS else rule_intent.value
            # README：文物在哪个展厅 → cultural_relic
            if focus.get("cultural_relic"):
                intent_key = IntentType.CULTURAL_RELIC.value
            elif focus.get("exhibition") and intent_key == IntentType.GENERAL.value:
                intent_key = IntentType.EXHIBITION.value
            elif focus.get("museum") and intent_key == IntentType.GENERAL.value:
                intent_key = rule_intent.value

            return {
                "intent": intent_key,
                "focus": focus,
                "confidence": out.confidence,
                "reasoning": out.reasoning or rule_reason,
                "rule_matched": False,
                "needs_disambiguation": False,
            }
        except Exception as exc:
            logger.warning("LLM 意图识别失败，回退规则结果: %s", exc)
            return {
                "intent": rule_intent.value,
                "focus": rule_focus,
                "confidence": 0.6,
                "reasoning": f"{rule_reason}（LLM 回退）",
                "rule_matched": False,
                "needs_disambiguation": False,
            }


def _format_history_for_intent(messages: list[BaseMessage] | None) -> str:
    if not messages:
        return ""
    lines = []
    for msg in messages[-10:]:
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "助手"
        else:
            continue
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines.append(f"{role}：{text.strip()}")
    return "\n## 近期对话\n" + "\n".join(lines) + "\n" if lines else ""
