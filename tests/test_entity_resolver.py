"""实体与意图规则识别单元测试（不依赖 LLM）。"""

from pathlib import Path

import pytest

from agent.entity_resolver import EntityResolver, is_museum_guide_question
from agent.relic_matcher import mask_museum_names
from agent.relic_matcher import (
    RelicMatcher,
    is_pending_selection_reply,
    resolve_pending_choice,
)
from agent.state import IntentType
from agent.wiki_index import WikiIndex

WIKI_ROOT = Path(__file__).resolve().parent.parent / "wiki"

YOU_TAO_NAMES = ["釉陶壶2", "釉陶壶6", "釉陶壶7", "釉陶壶8", "釉陶壶16"]


@pytest.fixture(scope="module")
def wiki_index() -> WikiIndex:
    return WikiIndex.build(WIKI_ROOT)


@pytest.fixture(scope="module")
def resolver(wiki_index: WikiIndex) -> EntityResolver:
    return EntityResolver(wiki_index)


@pytest.fixture(scope="module")
def matcher(wiki_index: WikiIndex) -> RelicMatcher:
    return RelicMatcher(wiki_index)


def _resolve(resolver, query, **kwargs):
    o = resolver.resolve(query, current_museum="南京博物院", last_exhibition=None, last_cultural_relic=None, **kwargs)
    return o.intent, o.focus, o


def test_find_relic(resolver: EntityResolver):
    intent, focus, o = _resolve(resolver, "请讲解一下蝙蝠虫")
    assert o.rule_matched
    assert intent == IntentType.CULTURAL_RELIC
    assert focus["cultural_relic"] == "蝙蝠虫"


def test_relic_location_is_cultural_relic_intent(resolver: EntityResolver):
    intent, focus, o = _resolve(resolver, "蝙蝠虫在哪个展厅")
    assert intent == IntentType.CULTURAL_RELIC
    assert focus["cultural_relic"] == "蝙蝠虫"


def test_exhibition_list_relics(resolver: EntityResolver):
    intent, focus, _ = _resolve(resolver, "历史馆1展厅有哪些文物")
    assert intent == IntentType.EXHIBITION
    assert focus["exhibition"] == "历史馆1展厅"


def test_anaphora_relic(resolver: EntityResolver):
    o = resolver.resolve(
        "它在哪个展厅",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic="蝙蝠虫",
    )
    assert o.focus["cultural_relic"] == "蝙蝠虫"
    assert o.intent == IntentType.CULTURAL_RELIC


def test_switch_museum(resolver: EntityResolver):
    intent, _, o = _resolve(resolver, "有哪些博物馆可以参观")
    assert intent == IntentType.SWITCH_MUSEUM
    assert o.rule_matched


def test_disambiguation_hint_uses_current_candidates():
    from agent.relic_matcher import format_disambiguation_prompt

    text = format_disambiguation_prompt("三彩马", ["三彩马6", "三彩马7"])
    assert "三彩马6" in text
    assert "釉陶壶" not in text
    assert "如「2」" in text or '如「2」' in text


def test_sancai_horse_disambiguate(resolver: EntityResolver):
    o = resolver.resolve(
        "介绍下三彩马",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
    )
    assert o.intent == IntentType.DISAMBIGUATE_RELIC
    assert set(o.relic_candidates) == {"三彩马6", "三彩马7"}


def test_shorthand_relic_ambiguous(resolver: EntityResolver, matcher: RelicMatcher):
    """简称「釉陶壶」应对应多件文物并进入消歧。"""
    m = matcher.resolve("介绍一下釉陶壶", "南京博物院")
    assert m.ambiguous
    assert set(m.candidates or []) >= set(YOU_TAO_NAMES)

    o = resolver.resolve(
        "介绍一下釉陶壶",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
    )
    assert o.intent == IntentType.DISAMBIGUATE_RELIC
    assert o.needs_disambiguation
    assert len(o.relic_candidates) >= 5


def test_exact_relic_name(resolver: EntityResolver):
    o = resolver.resolve(
        "讲解釉陶壶6",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
    )
    assert o.intent == IntentType.CULTURAL_RELIC
    assert o.focus["cultural_relic"] == "釉陶壶6"
    assert not o.needs_disambiguation


def test_museum_name_does_not_trigger_relic_disambiguation(resolver: EntityResolver):
    """「南京博物院」不应因「南京」二字触发城墙砖消歧。"""
    o = resolver.resolve(
        "南京博物院有哪些镇馆之宝",
        current_museum=None,
        last_exhibition=None,
        last_cultural_relic=None,
    )
    assert o.intent == IntentType.MUSEUM_OVERVIEW
    assert not o.needs_disambiguation
    assert o.focus["museum"] == "南京博物院"


def test_worth_seeing_is_museum_overview(resolver: EntityResolver):
    o = resolver.resolve(
        "有哪些文物值得一看",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
    )
    assert o.intent == IntentType.MUSEUM_OVERVIEW
    assert not o.needs_disambiguation


def test_new_question_clears_wrong_pending(resolver: EntityResolver):
    o = resolver.resolve(
        "有哪些文物值得一看",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
        pending_relic_choices=["南京城墙砖", "南京明故宫模型"],
        pending_relic_prefix="南京",
    )
    assert o.intent == IntentType.MUSEUM_OVERVIEW
    assert not o.needs_disambiguation


def test_mask_museum_names():
    assert "南京" not in mask_museum_names("南京博物院有哪些镇馆之宝", ["南京博物院"])


def test_pending_choice_by_number(resolver: EntityResolver):
    assert resolve_pending_choice("选 3", YOU_TAO_NAMES, "釉陶壶") == "釉陶壶7"
    assert resolve_pending_choice("3", YOU_TAO_NAMES, "釉陶壶") == "釉陶壶7"
    assert is_pending_selection_reply("3")

    o = resolver.resolve(
        "3",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
        pending_relic_choices=YOU_TAO_NAMES,
        pending_relic_prefix="釉陶壶",
    )
    assert o.intent == IntentType.CULTURAL_RELIC
    assert o.focus["cultural_relic"] == "釉陶壶7"

    o = resolver.resolve(
        "釉陶壶8",
        current_museum="南京博物院",
        last_exhibition=None,
        last_cultural_relic=None,
        pending_relic_choices=YOU_TAO_NAMES,
        pending_relic_prefix="釉陶壶",
    )
    assert o.intent == IntentType.CULTURAL_RELIC
    assert o.focus["cultural_relic"] == "釉陶壶8"
