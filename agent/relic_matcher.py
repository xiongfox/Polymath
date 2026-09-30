"""文物名称匹配：全称命中与简称多候选消歧。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.wiki_index import WikiIndex

# 简称匹配最短长度，避免单字误触
_MIN_PREFIX_LEN = 2
# 待选列表超过此数量时折叠展示
_MAX_LIST_DISPLAY = 12

_ORDINAL_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class RelicMatchResult:
    """文物主体解析结果。"""

    relic: str | None = None
    ambiguous: bool = False
    candidates: list[str] | None = None
    prefix: str | None = None
    match_type: str = "none"  # exact | prefix | pending | none


def natural_sort_key(name: str) -> tuple:
    """釉陶壶2 < 釉陶壶16 的数字序排序。"""
    parts = re.split(r"(\d+)", name)
    key: list = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p)
    return tuple(key)


def mask_museum_names(text: str, museums: list[str]) -> str:
    """去掉博物馆全称，避免「南京博物院」中的「南京」误匹配文物。"""
    result = text
    for name in sorted(museums, key=len, reverse=True):
        result = result.replace(name, " ")
    return re.sub(r"\s+", " ", result).strip()


class RelicMatcher:
    def __init__(self, wiki_index: WikiIndex) -> None:
        self.index = wiki_index

    def resolve(
        self,
        text: str,
        museum: str | None,
        *,
        pending_candidates: list[str] | None = None,
        pending_prefix: str | None = None,
        match_text: str | None = None,
    ) -> RelicMatchResult:
        if pending_candidates:
            chosen = resolve_pending_choice(
                text, pending_candidates, pending_prefix
            )
            if chosen:
                return RelicMatchResult(
                    relic=chosen,
                    match_type="pending",
                )
            # 有待选列表但未能解析用户输入 → 不再做简称模糊匹配，交由上层再次引导
            return RelicMatchResult(
                ambiguous=True,
                candidates=_sort_names(pending_candidates),
                prefix=pending_prefix,
                match_type="pending_retry",
            )

        lookup = match_text if match_text is not None else text
        if not lookup.strip():
            return RelicMatchResult()

        museums = [museum] if museum else list(self.index._sorted_relics.keys())
        all_exact: list[tuple[int, str, str]] = []

        for m in museums:
            for name in self.index._sorted_relics.get(m, []):
                if name in lookup:
                    if not any(
                        len(other) > len(name) and other in lookup
                        for other in self.index._sorted_relics.get(m, [])
                    ):
                        all_exact.append((len(name), m, name))

        if all_exact:
            all_exact.sort(reverse=True)
            top_len = all_exact[0][0]
            top = [t for t in all_exact if t[0] == top_len]
            if len(top) == 1:
                return RelicMatchResult(relic=top[0][2], match_type="exact")
            names = [t[2] for t in top]
            return RelicMatchResult(
                ambiguous=True,
                candidates=_sort_names(names),
                prefix=_common_prefix(names),
                match_type="exact",
            )

        best_stem: str | None = None
        best_cands: list[str] = []

        for m in museums:
            names = self.index._sorted_relics.get(m, [])
            stems: dict[str, list[str]] = {}
            for name in names:
                for length in range(len(name), _MIN_PREFIX_LEN - 1, -1):
                    stem = name[:length]
                    if stem in lookup:
                        stems.setdefault(stem, []).append(name)
                        break
            if not stems:
                continue
            stem = max(stems.keys(), key=len)
            cands = stems[stem]
            if best_stem is None or len(stem) > len(best_stem):
                best_stem = stem
                best_cands = cands
            elif len(stem) == len(best_stem):
                best_cands = list(dict.fromkeys(best_cands + cands))

        if not best_cands:
            return RelicMatchResult()

        best_cands = _sort_names(best_cands)
        if len(best_cands) == 1:
            return RelicMatchResult(relic=best_cands[0], match_type="prefix")

        return RelicMatchResult(
            ambiguous=True,
            candidates=best_cands,
            prefix=best_stem,
            match_type="prefix",
        )


def is_pending_selection_reply(query: str) -> bool:
    """当前输入是否仅为待选列表的序号/选项回复。"""
    text = query.strip()
    if not text:
        return False
    if re.fullmatch(r"\d+", text):
        return True
    if text in _ORDINAL_MAP:
        return True
    if re.match(r"^(选|第)\s*[\d一二三四五六七八九十]", text):
        return True
    if re.fullmatch(r"\d+\s*号", text):
        return True
    return False


def resolve_pending_choice(
    query: str,
    candidates: list[str],
    prefix: str | None = None,
) -> str | None:
    """用户从上一轮待选列表中选定一件文物。"""
    text = query.strip()
    if not text or not candidates:
        return None

    sorted_cands = _sort_names(candidates)

    # 1. 完整文物名
    for name in sorted_cands:
        if name in text:
            return name

    # 2. 纯序号（与列表展示 1. 2. 3. 对应，优先于编号后缀匹配）
    if re.fullmatch(r"\d+", text):
        idx = int(text) - 1
        if 0 <= idx < len(sorted_cands):
            return sorted_cands[idx]

    # 3. 中文序号：三、第三个
    if text in _ORDINAL_MAP:
        idx = _ORDINAL_MAP[text] - 1
        if 0 <= idx < len(sorted_cands):
            return sorted_cands[idx]

    m = re.search(r"第\s*(\d+|[一二三四五六七八九十]+)\s*[个件名号]?", text)
    if m:
        raw = m.group(1)
        idx = int(raw) - 1 if raw.isdigit() else _ORDINAL_MAP.get(raw, 0) - 1
        if 0 <= idx < len(sorted_cands):
            return sorted_cands[idx]

    m = re.search(r"选\s*(\d+)", text)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(sorted_cands):
            return sorted_cands[idx]

    # 4. 简称+编号：釉陶壶6 / 6号
    if prefix and prefix in text:
        nums = re.findall(r"\d+", text)
        for num in nums:
            for name in sorted_cands:
                if name == f"{prefix}{num}" or name.endswith(num):
                    return name

    m = re.search(r"(\d+)\s*号", text)
    if m:
        num = m.group(1)
        for name in sorted_cands:
            if name.endswith(num) or (prefix and name == f"{prefix}{num}"):
                return name

    return None


def _disambiguation_selection_hint(sorted_cands: list[str]) -> str:
    """根据当前待选列表生成选择说明（示例名称与序号与列表一致）。"""
    if not sorted_cands:
        return "请回复完整文物名称或列表序号。"
    example_name = sorted_cands[0]
    # 序号示例：有 2 件时用「2」，否则用「1」，避免列只有 2 项时示例写「3」
    index_example = min(2, len(sorted_cands))
    return (
        f"请回复完整文物名称（如「{example_name}」），"
        f"或直接回复列表序号（如「{index_example}」），"
        f"也可以说「选 {index_example}」「第 {index_example} 个」。"
    )


def format_disambiguation_prompt(prefix: str | None, candidates: list[str]) -> str:
    """生成引导用户选择文物的回复文案。"""
    sorted_cands = _sort_names(candidates)
    label = f"「{prefix}」" if prefix else "该名称"
    lines = [
        f"馆藏中有 {len(sorted_cands)} 件文物与{label}相关，请问您想了解哪一件？",
        "",
    ]
    display = sorted_cands[:_MAX_LIST_DISPLAY]
    for i, name in enumerate(display, 1):
        lines.append(f"  {i}. {name}")
    if len(sorted_cands) > _MAX_LIST_DISPLAY:
        lines.append(f"  … 另有 {len(sorted_cands) - _MAX_LIST_DISPLAY} 件未列出")
    lines.extend(["", _disambiguation_selection_hint(sorted_cands)])
    return "\n".join(lines)


def _sort_names(names: list[str]) -> list[str]:
    return sorted(names, key=natural_sort_key)


def _common_prefix(names: list[str]) -> str | None:
    if not names:
        return None
    prefix = names[0]
    for n in names[1:]:
        while prefix and not n.startswith(prefix):
            prefix = prefix[:-1]
    return prefix or None
