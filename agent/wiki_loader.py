"""按意图加载对应 Wiki 文档。"""

from __future__ import annotations

from pathlib import Path

from agent.state import IntentResult, IntentType
from agent.wiki_index import WikiIndex


def load_wiki_for_intent(index: WikiIndex, intent_result: IntentResult) -> tuple[str, list[str]]:
    """
    根据意图与主体加载 Wiki 正文。
    返回 (合并后的 markdown 文本, 已加载文件路径列表)。
    """
    intent = intent_result["intent"]
    focus = intent_result.get("focus") or {}
    museum = focus.get("museum")
    exhibition = focus.get("exhibition")
    relic = focus.get("cultural_relic")
    relics = focus.get("cultural_relics") or []

    paths: list[Path] = []
    chunks: list[str] = []

    if intent == IntentType.SWITCH_MUSEUM.value:
        p = index.global_index_path()
        if p.exists():
            paths.append(p)
            chunks.append(_read(p))

    elif intent == IntentType.MUSEUM_OVERVIEW.value:
        if museum:
            p = index.museum_path(museum)
            if p.exists():
                paths.append(p)
                chunks.append(_read(p))
        else:
            p = index.global_index_path()
            if p.exists():
                paths.append(p)
                chunks.append(_read(p))

    elif intent == IntentType.EXHIBITION.value:
        if museum and exhibition:
            p = index.exhibition_path(museum, exhibition)
            if p.exists():
                paths.append(p)
                chunks.append(_read(p))
        if museum and not chunks:
            p = index.museum_path(museum)
            if p.exists():
                paths.append(p)
                chunks.append(_read(p, max_chars=8000))

    elif intent == IntentType.CULTURAL_RELIC.value:
        targets = relics if relics else ([relic] if relic else [])
        for name in targets:
            m = museum or index.relic_museum(name)
            if not m:
                continue
            p = index.relic_path(m, name)
            if p.exists():
                paths.append(p)
                chunks.append(_read(p))

    else:
        if museum:
            p = index.museum_path(museum)
            if p.exists():
                paths.append(p)
                chunks.append(_read(p, max_chars=6000))
        if not chunks:
            p = index.global_index_path()
            if p.exists():
                paths.append(p)
                chunks.append(_read(p))

    if not chunks:
        return "（未找到匹配的 Wiki 文档，请根据已有对话礼貌说明并引导用户指定博物馆/展厅/文物。）", []

    header = _format_focus_header(intent, focus)
    body = "\n\n---\n\n".join(chunks)
    return f"{header}\n\n{body}", [str(p) for p in paths]


def _read(path: Path, max_chars: int = 12000) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n…（下文已截断）"
    return text


def _format_focus_header(intent: str, focus: dict) -> str:
    parts = [f"【当前意图】{intent}"]
    if focus.get("museum"):
        parts.append(f"【博物馆】{focus['museum']}")
    if focus.get("exhibition"):
        parts.append(f"【展厅】{focus['exhibition']}")
    if focus.get("cultural_relics"):
        parts.append(f"【文物（多件）】{'、'.join(focus['cultural_relics'])}")
    elif focus.get("cultural_relic"):
        parts.append(f"【文物】{focus['cultural_relic']}")
    return "\n".join(parts)
