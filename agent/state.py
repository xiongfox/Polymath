"""LangGraph 会话状态定义。"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class IntentType(str, Enum):
    SWITCH_MUSEUM = "switch_museum"
    MUSEUM_OVERVIEW = "museum_overview"
    EXHIBITION = "exhibition"
    CULTURAL_RELIC = "cultural_relic"
    DISAMBIGUATE_RELIC = "disambiguate_relic"
    GENERAL = "general"


class EntityFocus(TypedDict, total=False):
    museum: str | None
    exhibition: str | None
    cultural_relic: str | None
    cultural_relics: list[str]


class IntentResult(TypedDict, total=False):
    intent: str
    focus: EntityFocus
    confidence: float
    reasoning: str
    rule_matched: bool
    needs_disambiguation: bool
    relic_candidates: list[str]
    relic_prefix: str | None
    pending_user_question: str | None


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_museum: str | None
    last_exhibition: str | None
    last_cultural_relic: str | None
    pending_relic_choices: list[str] | None
    pending_relic_prefix: str | None
    pending_user_question: str | None
    intent_result: IntentResult | None
    wiki_paths: list[str]
    wiki_context: str
    user_query: str
