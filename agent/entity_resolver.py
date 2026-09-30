"""用户问题中的博物馆 / 展厅 / 文物主体识别。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.relic_matcher import RelicMatcher, is_pending_selection_reply, mask_museum_names
from agent.state import EntityFocus, IntentType

if TYPE_CHECKING:
    from agent.wiki_index import WikiIndex

# 切换博物馆
_SWITCH_PATTERNS = re.compile(
    r"(切换|换到|换成|去|参观|逛逛|看看).{0,6}(博物馆|博物院)|"
    r"(还有|别的|其他).{0,4}博物馆|"
    r"哪个博物馆|博物馆列表|有哪些博物馆",
)

# 展厅类问题（须出现展厅/展馆，或明确问某厅内文物）
_EXHIBITION_HINTS = re.compile(
    r"(展厅|展馆|展馆区|几号厅|哪个厅|在.{0,4}馆.{0,4}层|"
    r"展厅.{0,6}(位置|在哪|路线)|"
    r"展厅.{0,6}(有什么|有哪些).{0,4}文物|"
    r"厅.{0,6}(有什么|有哪些).{0,4}文物|展出什么|展品列表)",
)

# 博物馆整体推荐 / 镇馆之宝（非单件文物）
_MUSEUM_GUIDE_PATTERNS = re.compile(
    r"(镇馆之宝|镇馆|馆藏精品|精品文物|"
    r"值得.{0,6}看|值得.{0,6}参观|必看|推荐.{0,6}看|"
    r"有什么.{0,4}看|打卡|亮点|代表作|"
    r"(有哪些|有什么).{0,8}(文物|藏品|展品).{0,6}(看|推荐|值得|必))",
)

# 指向上一轮主体的指代
_ANAPHORA = re.compile(
    r"^(它|这个|这件|该文物|该展品|上面那个|刚才那个|这个文物|"
    r"这件文物|那个|这款)(呢|的|是|在|有|吗|？|\?)?$|"
    r"(它|这件|这个)(在|属于|位于|放在).{0,8}(哪|什么)",
)

# 文物在哪个展厅 → 仍属文物讲解意图（README 明确要求）
_RELIC_LOCATION_PATTERNS = re.compile(
    r"(哪个展厅|在哪.{0,4}展厅|什么展厅|位于.{0,6}展厅|"
    r"在.{0,4}厅|属于.{0,4}展厅|展出.{0,4}厅)",
)


@dataclass
class ResolveOutcome:
    intent: IntentType
    focus: EntityFocus
    reasoning: str
    rule_matched: bool
    needs_disambiguation: bool = False
    relic_candidates: list[str] = field(default_factory=list)
    relic_prefix: str | None = None


def is_museum_guide_question(text: str) -> bool:
    """是否为博物馆整体推荐/镇馆之宝类问题（非针对单件文物）。"""
    return bool(_MUSEUM_GUIDE_PATTERNS.search(text))


class EntityResolver:
    """规则优先 + 可选 LLM 校验的实体与意图解析。"""

    def __init__(self, wiki_index: WikiIndex) -> None:
        self.index = wiki_index
        self.relic_matcher = RelicMatcher(wiki_index)

    def resolve(
        self,
        query: str,
        *,
        current_museum: str | None,
        last_exhibition: str | None,
        last_cultural_relic: str | None,
        pending_relic_choices: list[str] | None = None,
        pending_relic_prefix: str | None = None,
    ) -> ResolveOutcome:
        text = query.strip()
        focus: EntityFocus = {
            "museum": None,
            "exhibition": None,
            "cultural_relic": None,
        }

        # 新一轮 substantive 问题 → 取消上一轮文物待选
        if pending_relic_choices and not is_pending_selection_reply(text):
            pending_relic_choices = None
            pending_relic_prefix = None

        museum_in_text = self.index.find_museum_in_text(text)
        exhibition_in_text = self.index.find_exhibition_in_text(
            text, museum_in_text or current_museum
        )

        relic_lookup_text = mask_museum_names(text, self.index.museums)
        relic_match = self.relic_matcher.resolve(
            text,
            museum_in_text or current_museum,
            pending_candidates=pending_relic_choices,
            pending_prefix=pending_relic_prefix,
            match_text=relic_lookup_text,
        )
        relic_in_text = relic_match.relic

        if relic_match.match_type == "pending_retry":
            return ResolveOutcome(
                intent=IntentType.DISAMBIGUATE_RELIC,
                focus={
                    "museum": museum_in_text or current_museum,
                    "exhibition": None,
                    "cultural_relic": None,
                },
                reasoning="有待选文物但未识别您的序号/名称，请重新选择",
                rule_matched=True,
                needs_disambiguation=True,
                relic_candidates=relic_match.candidates or [],
                relic_prefix=relic_match.prefix or pending_relic_prefix,
            )

        if relic_in_text and not museum_in_text:
            museum_in_text = self.index.relic_museum(relic_in_text)
        if exhibition_in_text and not museum_in_text:
            museum_in_text = self.index.exhibition_museum(exhibition_in_text)

        if _ANAPHORA.search(text):
            if not relic_in_text and last_cultural_relic:
                relic_in_text = last_cultural_relic
            if not exhibition_in_text and last_exhibition:
                exhibition_in_text = last_exhibition

        focus["museum"] = museum_in_text or current_museum
        focus["exhibition"] = exhibition_in_text
        focus["cultural_relic"] = relic_in_text

        museum_ctx = focus.get("museum") or current_museum
        guide_question = is_museum_guide_question(text)

        # 简称对应多件文物 → 列出候选，引导用户选择
        if relic_match.ambiguous and relic_match.candidates and not guide_question:
            prefix = relic_match.prefix or _common_prefix_from_candidates(relic_match.candidates)
            return ResolveOutcome(
                intent=IntentType.DISAMBIGUATE_RELIC,
                focus={
                    "museum": museum_ctx,
                    "exhibition": None,
                    "cultural_relic": None,
                },
                reasoning=(
                    f"简称「{prefix}」对应 {len(relic_match.candidates)} 件文物，需用户选定"
                ),
                rule_matched=True,
                needs_disambiguation=True,
                relic_candidates=relic_match.candidates,
                relic_prefix=prefix,
            )

        if guide_question and museum_ctx and not relic_in_text:
            return ResolveOutcome(
                intent=IntentType.MUSEUM_OVERVIEW,
                focus={"museum": museum_ctx, "exhibition": None, "cultural_relic": None},
                reasoning=f"博物馆「{museum_ctx}」推荐/镇馆之宝类问题",
                rule_matched=True,
            )

        if _SWITCH_PATTERNS.search(text) or (
            museum_in_text
            and museum_in_text != current_museum
            and not relic_in_text
            and not exhibition_in_text
        ):
            return ResolveOutcome(
                intent=IntentType.SWITCH_MUSEUM,
                focus={"museum": museum_in_text, "exhibition": None, "cultural_relic": None},
                reasoning="识别为切换/选择博物馆",
                rule_matched=True,
            )

        if relic_in_text:
            reason = f"命中文物主体「{relic_in_text}」"
            if relic_match.match_type == "pending":
                reason += "（用户从待选列表中选定）"
            elif relic_match.match_type == "prefix":
                reason += "（简称唯一匹配）"
            if _RELIC_LOCATION_PATTERNS.search(text):
                reason += "；询问文物所在展厅，按文物讲解意图处理"
            return ResolveOutcome(
                intent=IntentType.CULTURAL_RELIC,
                focus=focus,
                reasoning=reason,
                rule_matched=True,
            )

        if exhibition_in_text or _EXHIBITION_HINTS.search(text):
            if not focus["exhibition"] and _EXHIBITION_HINTS.search(text):
                focus["exhibition"] = last_exhibition
            return ResolveOutcome(
                intent=IntentType.EXHIBITION,
                focus=focus,
                reasoning=f"命中展厅主体「{focus.get('exhibition') or '（沿用上下文）'}」",
                rule_matched=exhibition_in_text is not None,
            )

        if museum_ctx and (
            guide_question
            or re.search(
                r"(概况|简介|介绍|有哪些展厅|开放时间|怎么去|馆藏|参观建议)",
                text,
            )
        ):
            return ResolveOutcome(
                intent=IntentType.MUSEUM_OVERVIEW,
                focus={"museum": museum_ctx, "exhibition": None, "cultural_relic": None},
                reasoning=f"博物馆「{museum_ctx}」概况/推荐类问题",
                rule_matched=True,
            )

        if museum_ctx:
            return ResolveOutcome(
                intent=IntentType.GENERAL,
                focus=focus,
                reasoning=f"已锁定博物馆「{museum_ctx}」，未识别具体展厅或文物",
                rule_matched=False,
            )

        return ResolveOutcome(
            intent=IntentType.GENERAL,
            focus=focus,
            reasoning="未识别博物馆/展厅/文物主体",
            rule_matched=False,
        )

    def build_llm_context(
        self,
        query: str,
        *,
        current_museum: str | None,
        last_exhibition: str | None = None,
        last_cultural_relic: str | None = None,
        pending_relic_choices: list[str] | None = None,
    ) -> str:
        museum = current_museum
        relics = self.index.candidate_relics(
            mask_museum_names(query, self.index.museums), museum
        )
        exhibitions = self.index.candidate_exhibitions(query, museum)
        lines = [
            f"当前博物馆：{current_museum or '（未选择）'}",
            f"上一轮文物：{last_cultural_relic or '无'}",
            f"上一轮展厅：{last_exhibition or '无'}",
            f"待选文物列表：{', '.join(pending_relic_choices) if pending_relic_choices else '无'}",
            f"可选博物馆：{', '.join(self.index.museums) or '无'}",
            f"文本命中文物候选：{', '.join(relics) or '无'}",
            f"文本命中展厅候选：{', '.join(exhibitions) or '无'}",
        ]
        return "\n".join(lines)

    def clamp_focus(self, focus: EntityFocus) -> EntityFocus:
        museum = focus.get("museum")
        exhibition = focus.get("exhibition")
        relic = focus.get("cultural_relic")

        if museum and museum not in self.index.museums:
            museum = self.index.find_museum_in_text(museum) or None
        if exhibition:
            if museum and exhibition not in self.index.exhibitions.get(museum, []):
                exhibition = self.index.find_exhibition_in_text(exhibition, museum)
            elif not museum:
                exhibition = self.index.find_exhibition_in_text(exhibition, None)
        if relic:
            if museum and relic not in self.index.cultural_relics.get(museum, []):
                relic = self.relic_matcher.resolve(
                    relic, museum, match_text=relic
                ).relic
            elif not museum:
                relic = self.relic_matcher.resolve(relic, None, match_text=relic).relic
            if relic and not museum:
                museum = self.index.relic_museum(relic)

        return {
            "museum": museum,
            "exhibition": exhibition,
            "cultural_relic": relic,
        }


def _common_prefix_from_candidates(candidates: list[str]) -> str:
    if not candidates:
        return ""
    p = candidates[0]
    for c in candidates[1:]:
        while p and not c.startswith(p):
            p = p[:-1]
    return p
