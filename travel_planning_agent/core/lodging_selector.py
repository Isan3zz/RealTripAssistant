"""Choose where hotel searches should be anchored."""

from __future__ import annotations

from collections import Counter
from typing import Any

from travel_planning_agent.types import Constraints, Segment, SegmentType


def select_lodging_anchor(
    constraints: Constraints,
    draft_result: dict | None = None,
    research_needs: list[dict] | None = None,
) -> str:
    """Pick a stable hotel-search anchor from draft activities and needs."""
    candidates = []
    candidates.extend(_activity_names_from_draft(draft_result or {}))
    candidates.extend(_poi_names_from_needs(research_needs or []))
    candidates.extend(getattr(constraints, "interests", []) or [])

    cleaned = [_clean_anchor(c, constraints.destination) for c in candidates]
    cleaned = [c for c in cleaned if c]
    if not cleaned:
        return "市中心"

    counts = Counter(cleaned)
    return counts.most_common(1)[0][0]


def _activity_names_from_draft(draft_result: dict) -> list[str]:
    modules = draft_result.get("modules", {}) if isinstance(draft_result, dict) else {}
    names: list[str] = []
    if not isinstance(modules, dict):
        return names

    for segments in modules.values():
        if not isinstance(segments, list):
            continue
        for seg in segments:
            if isinstance(seg, Segment):
                if seg.type == SegmentType.ACTIVITY:
                    names.append((seg.location.name if seg.location else "") or seg.title)
                continue
            if not isinstance(seg, dict) or seg.get("type") != "activity":
                continue
            loc = seg.get("location") or {}
            names.append(loc.get("name") or seg.get("title") or "")
    return names


def _poi_names_from_needs(research_needs: list[dict]) -> list[str]:
    names = []
    for need in research_needs:
        if not isinstance(need, dict):
            continue
        if need.get("type") in {"poi_detail", "ticket_price"}:
            names.append(str(need.get("item", "")))
    return names


def _clean_anchor(text: Any, destination: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for token in (
        destination, "附近", "周边", "旁边", "酒店", "住宿", "宾馆", "民宿",
        "推荐", "查询", "查找", "核实", "价格", "评分", "位置", "目的地",
        "游览", "活动", "前往", "入住",
    ):
        value = value.replace(token, "")
    value = value.strip(" ：:，,。()（）[]【】")
    return "" if value in {"", "市区", "城区", "当地"} else value
