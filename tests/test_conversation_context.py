"""历史消息会话上下文推导测试。"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.conversation_context import derive_context_from_messages
from agent.relic_matcher import format_disambiguation_prompt
from agent.wiki_index import WikiIndex

WIKI_ROOT = Path(__file__).resolve().parent.parent / "wiki"


@pytest.fixture(scope="module")
def wiki_index() -> WikiIndex:
    return WikiIndex.build(WIKI_ROOT)


def test_parse_pending_from_disambiguation_reply(wiki_index: WikiIndex):
    clarify = format_disambiguation_prompt("三彩马", ["三彩马6", "三彩马7"])
    messages = [
        HumanMessage(content="介绍下三彩马，什么时期的"),
        AIMessage(content=clarify),
    ]
    ctx = derive_context_from_messages(wiki_index, "南京博物院", messages)
    assert ctx.pending_relic_choices == ["三彩马6", "三彩马7"]
    assert ctx.pending_relic_prefix == "三彩马"
    assert ctx.pending_user_question == "介绍下三彩马，什么时期的"


def test_selection_after_disambiguation(wiki_index: WikiIndex):
    clarify = format_disambiguation_prompt("三彩马", ["三彩马6", "三彩马7"])
    messages = [
        HumanMessage(content="介绍下三彩马"),
        AIMessage(content=clarify),
        HumanMessage(content="2"),
    ]
    ctx = derive_context_from_messages(wiki_index, "南京博物院", messages[:-1])
    assert ctx.pending_relic_choices is not None
    assert "2" not in (ctx.last_cultural_relic or "")
