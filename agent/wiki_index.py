"""从 Wiki 目录构建博物馆 / 展厅 / 文物实体索引。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class WikiIndex:
    """可检索的 Wiki 实体目录。"""

    wiki_root: Path
    museums: list[str] = field(default_factory=list)
    exhibitions: dict[str, list[str]] = field(default_factory=dict)
    cultural_relics: dict[str, list[str]] = field(default_factory=dict)
    _sorted_museums: list[str] = field(default_factory=list, repr=False)
    _sorted_exhibitions: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _sorted_relics: dict[str, list[str]] = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, wiki_root: Path | str) -> WikiIndex:
        root = Path(wiki_root)
        index = cls(wiki_root=root)
        index._load_museums()
        for museum in index.museums:
            index._load_exhibitions(museum)
            index._load_relics(museum)
        index._prepare_sorted()
        return index

    def _load_museums(self) -> None:
        global_index = self.wiki_root / "index.md"
        names: list[str] = []
        if global_index.exists():
            names.extend(self._parse_wiki_links(global_index.read_text(encoding="utf-8")))
        museum_dir = self.wiki_root / "museum"
        if museum_dir.is_dir():
            for sub in sorted(museum_dir.iterdir()):
                if sub.is_dir() and (sub / "index.md").exists():
                    names.append(sub.name)
        self.museums = list(dict.fromkeys(names))

    def _load_exhibitions(self, museum: str) -> None:
        ex_dir = self.wiki_root / "exhibition" / museum
        if not ex_dir.is_dir():
            self.exhibitions[museum] = []
            return
        names = sorted(p.stem for p in ex_dir.glob("*.md"))
        self.exhibitions[museum] = names

    def _load_relics(self, museum: str) -> None:
        rel_dir = self.wiki_root / "cultural_relic" / museum
        if not rel_dir.is_dir():
            self.cultural_relics[museum] = []
            return
        names = sorted(p.stem for p in rel_dir.glob("*.md"))
        self.cultural_relics[museum] = names

    def _prepare_sorted(self) -> None:
        self._sorted_museums = sorted(self.museums, key=len, reverse=True)
        self._sorted_exhibitions = {
            m: sorted(names, key=len, reverse=True)
            for m, names in self.exhibitions.items()
        }
        self._sorted_relics = {
            m: sorted(names, key=len, reverse=True)
            for m, names in self.cultural_relics.items()
        }

    @staticmethod
    def _parse_wiki_links(text: str) -> list[str]:
        return [m.group(1).strip() for m in WIKI_LINK_RE.finditer(text)]

    def museum_path(self, museum: str) -> Path:
        return self.wiki_root / "museum" / museum / "index.md"

    def exhibition_path(self, museum: str, exhibition: str) -> Path:
        return self.wiki_root / "exhibition" / museum / f"{exhibition}.md"

    def relic_path(self, museum: str, relic: str) -> Path:
        return self.wiki_root / "cultural_relic" / museum / f"{relic}.md"

    def global_index_path(self) -> Path:
        return self.wiki_root / "index.md"

    def find_museum_in_text(self, text: str) -> str | None:
        return _longest_substring_match(text, self._sorted_museums)

    def find_exhibition_in_text(self, text: str, museum: str | None) -> str | None:
        museums = [museum] if museum else list(self._sorted_exhibitions.keys())
        best: tuple[int, str, str] | None = None
        for m in museums:
            for name in self._sorted_exhibitions.get(m, []):
                if name in text:
                    if best is None or len(name) > best[0]:
                        best = (len(name), m, name)
        return best[2] if best else None

    def find_relic_in_text(self, text: str, museum: str | None) -> str | None:
        museums = [museum] if museum else list(self._sorted_relics.keys())
        best: tuple[int, str] | None = None
        for m in museums:
            for name in self._sorted_relics.get(m, []):
                if name in text:
                    if best is None or len(name) > best[0]:
                        best = (len(name), name)
        return best[1] if best else None

    def relic_museum(self, relic: str) -> str | None:
        for museum, names in self.cultural_relics.items():
            if relic in names:
                return museum
        return None

    def exhibition_museum(self, exhibition: str) -> str | None:
        for museum, names in self.exhibitions.items():
            if exhibition in names:
                return museum
        return None

    def candidate_relics(self, text: str, museum: str | None, limit: int = 8) -> list[str]:
        """返回文本中可能涉及的文物名（用于 LLM 消歧）。"""
        museums = [museum] if museum else list(self._sorted_relics.keys())
        hits: list[tuple[int, str]] = []
        for m in museums:
            for name in self._sorted_relics.get(m, []):
                if name in text:
                    hits.append((len(name), name))
        hits.sort(reverse=True)
        seen: set[str] = set()
        result: list[str] = []
        for _, name in hits:
            if name not in seen:
                seen.add(name)
                result.append(name)
            if len(result) >= limit:
                break
        return result

    def candidate_exhibitions(self, text: str, museum: str | None, limit: int = 5) -> list[str]:
        museums = [museum] if museum else list(self._sorted_exhibitions.keys())
        hits: list[tuple[int, str]] = []
        for m in museums:
            for name in self._sorted_exhibitions.get(m, []):
                if name in text:
                    hits.append((len(name), name))
        hits.sort(reverse=True)
        seen: set[str] = set()
        result: list[str] = []
        for _, name in hits:
            if name not in seen:
                seen.add(name)
                result.append(name)
            if len(result) >= limit:
                break
        return result


def _longest_substring_match(text: str, candidates: list[str]) -> str | None:
    best: str | None = None
    for name in candidates:
        if name in text and (best is None or len(name) > len(best)):
            best = name
    return best
