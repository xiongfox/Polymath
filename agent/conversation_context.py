"""从多轮历史消息推导意图识别所需的会话上下文。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent.relic_matcher import RelicMatcher, mask_museum_names
from agent.wiki_index import WikiIndex

_DISAMBIG_HINT = re.compile(r"请问您想了解哪一件|待选文物")
_DISAMBIG_PREFIX = re.compile(r"与[「\"]([^」\"]+)[」\"]相关")
_LIST_ITEM = re.compile(r"^\s*\d+\.\s*(.+?)\s*$")


@dataclass
class ConversationContext:
    """供意图识别使用的会话快照。"""

    current_museum: str | None = None
    last_exhibition: str | None = None
    last_cultural_relic: str | None = None
    pending_relic_choices: list[str] | None = None
    pending_relic_prefix: str | None = None
    pending_user_question: str | None = None


def derive_context_from_messages(
    wiki_index: WikiIndex,
    museum_name: str,
    messages: list[BaseMessage],
) -> ConversationContext:
    """
    根据 history（不含当前轮用户问题）推导会话上下文。
    供 API 无状态对接与 LangGraph 多轮消息列表共用。
    """
    ctx = ConversationContext(current_museum=museum_name or None)
    if not messages:
        return ctx

    matcher = RelicMatcher(wiki_index)
    museum = museum_name or None

    last_assistant_text = _last_message_text(messages, AIMessage)
    if last_assistant_text and _DISAMBIG_HINT.search(last_assistant_text):
        candidates, prefix = _parse_disambiguation_list(
            last_assistant_text, wiki_index, museum
        )
        if candidates:
            ctx.pending_relic_choices = candidates
            ctx.pending_relic_prefix = prefix
            ctx.pending_user_question = _last_user_before_disambiguation(messages)

    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        text = _message_content(msg)
        if not text:
            continue
        lookup = mask_museum_names(text, wiki_index.museums)
        relic = matcher.resolve(lookup, museum).relic
        if relic and not ctx.pending_relic_choices:
            ctx.last_cultural_relic = relic
            break

    if not ctx.last_cultural_relic:
        for msg in reversed(messages):
            if not isinstance(msg, AIMessage):
                continue
            text = _message_content(msg)
            if not text or _DISAMBIG_HINT.search(text):
                continue
            lookup = mask_museum_names(text, wiki_index.museums)
            relic = matcher.resolve(lookup, museum).relic
            if relic:
                ctx.last_cultural_relic = relic
                break

    for msg in reversed(messages):
        text = _message_content(msg)
        if not text:
            continue
        if isinstance(msg, HumanMessage):
            lookup = mask_museum_names(text, wiki_index.museums)
        else:
            lookup = text
        hall = wiki_index.find_exhibition_in_text(lookup, museum)
        if hall:
            ctx.last_exhibition = hall
            break

    return ctx


def derive_context_from_history(
    wiki_index: WikiIndex,
    museum_name: str,
    history: list,
) -> ConversationContext:
    """接受 API ChatMessage 列表（role/content）。"""
    messages: list[BaseMessage] = []
    for item in history:
        role = getattr(item, "role", None) or item.get("role")
        content = getattr(item, "content", None) or item.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    return derive_context_from_messages(wiki_index, museum_name, messages)


def _parse_disambiguation_list(
    assistant_text: str,
    wiki_index: WikiIndex,
    museum: str | None,
) -> tuple[list[str], str | None]:
    names: list[str] = []
    for line in assistant_text.splitlines():
        m = _LIST_ITEM.match(line)
        if m:
            names.append(m.group(1).strip())
    prefix_m = _DISAMBIG_PREFIX.search(assistant_text)
    prefix = prefix_m.group(1) if prefix_m else None

    if museum and names:
        valid = set(wiki_index.cultural_relics.get(museum, []))
        names = [n for n in names if n in valid]
    return names, prefix


def _last_user_before_disambiguation(messages: list[BaseMessage]) -> str | None:
    seen_disambig = False
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            text = _message_content(msg)
            if text and _DISAMBIG_HINT.search(text):
                seen_disambig = True
            continue
        if seen_disambig and isinstance(msg, HumanMessage):
            return _message_content(msg)
    return None


def _last_message_text(messages: list[BaseMessage], cls: type) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, cls):
            return _message_content(msg)
    return None


def _message_content(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()
