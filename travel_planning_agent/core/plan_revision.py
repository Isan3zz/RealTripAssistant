"""Rule-based revisions for already generated plans."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from travel_planning_agent.core.revision_append import append_one_day_plan


def looks_like_plan_revision(message: str, context: dict) -> bool:
    if not context.get("last_trip_id"):
        return False

    text = message or ""
    day_or_time_pattern = re.compile(
        r"第[一二三四五六七八九十\d]+天|\bday\s*\d+\b|\u4e0a\u5348|\u4e0b\u5348|\u665a\u4e0a|\u4e2d\u5348",
        re.I,
    )
    has_day_or_time = bool(day_or_time_pattern.search(text))

    legacy_tokens = (
        "回去", "返程", "返回", "回家", "离开",
        "提前", "改", "换", "删", "取消", "不要",
    )
    personal_tokens = (
        "太累", "轻松一点", "少走路", "慢一点",
        "下雨", "雨天", "室内", "天气不好",
        "预算降", "便宜一点", "省钱", "花费少",
    )
    explicit_revision_tokens = ("改一下", "调整一下", "换一下")
    append_tokens = ("多玩一天", "多待一天", "还能玩一天", "加一天", "新增一天")
    transport_tokens = ("坐飞机", "改飞机", "改高铁", "改动车")

    has_legacy_revision_intent = any(token in text for token in legacy_tokens)
    has_personal_revision_intent = any(token in text for token in personal_tokens)
    has_explicit_revision_intent = any(token in text for token in explicit_revision_tokens)
    has_append_intent = any(token in text for token in append_tokens)
    has_transport_intent = any(token in text for token in transport_tokens)

    return (
        (has_day_or_time and has_legacy_revision_intent)
        or has_personal_revision_intent
        or has_explicit_revision_intent
        or has_append_intent
        or has_transport_intent
    )

def is_return_revision(message: str) -> bool:
    return any(token in (message or "") for token in ("回去", "返程", "返回", "回家", "离开"))


def apply_change_request_to_plan(
    plan_data: dict,
    trip,
    message: str,
    context: dict | None = None,
    revision_agent=None,
    tool_executor=None,
    parsed_scope: dict | None = None,
    append_day: dict | None = None,
) -> bool:
    """Apply a supported change request through bounded research + one day replacement."""
    intent = analyze_change_intent(message, plan_data, parsed_scope=parsed_scope)
    if not intent:
        return False
    if intent.get("type") == "append_day" and append_day:
        updated = append_one_day_plan(plan_data, append_day)
        plan_data["days"] = updated["days"]
        return True
    if intent.get("type") == "remove_segment" and intent.get("target_segment"):
        return _remove_target_segment(plan_data, intent["target_segment"])
    if revision_agent is None:
        return apply_return_revision_to_plan(plan_data, trip, message, context) if intent["type"] == "return_time_change" else False

    evidence = _collect_revision_evidence(intent, trip, tool_executor)
    day_patch = revision_agent.revise_day(
        plan_data=plan_data,
        trip_info={
            "destination": getattr(trip, "destination", ""),
            "origin": trip_origin(trip, context),
            "days": getattr(trip, "days", len(plan_data.get("days", []))),
        },
        intent=intent,
        evidence=evidence,
    )
    if not day_patch:
        return apply_return_revision_to_plan(plan_data, trip, message, context) if intent["type"] == "return_time_change" else False

    original_days = list(plan_data.get("days") or [])
    target_day = int(intent.get("target_day") or len(original_days) or 1)
    replacement = _normalize_replacement_day(day_patch, target_day, intent, trip, context, original_days)
    if not replacement.get("segments"):
        return False

    merged_days = []
    for day in original_days:
        day_number = int(day.get("day_number", 0) or 0)
        if day_number < target_day:
            merged_days.append(day)
        elif day_number == target_day:
            merged_days.append(_merge_day_by_scope(day, replacement, intent))
        elif intent["type"] != "return_time_change":
            merged_days.append(day)
    if not any(int(d.get("day_number", 0) or 0) == target_day for d in merged_days):
        merged_days.append(replacement)

    plan_data["days"] = sorted(merged_days, key=lambda d: int(d.get("day_number", 0) or 0))
    return True


def analyze_change_intent(
    message: str,
    plan_data: dict,
    parsed_scope: dict | None = None,
) -> dict[str, Any]:
    if parsed_scope:
        change_type = parsed_scope.get("change_type")
        if not change_type:
            return {}
        intent = {
            "type": change_type,
            "target_day": parsed_scope.get("target_day") or len(plan_data.get("days", []) or [1]),
            "target_module": parsed_scope.get("target_module"),
            "target_segment": parsed_scope.get("target_segment"),
            "requires_tools": change_type in {"rainy_day_backup", "replace_activity"},
        }
        if change_type == "return_time_change":
            return_start, return_end = return_window_from_message(message)
            intent["return_start"] = parsed_scope.get("return_start") or return_start
            intent["return_end"] = parsed_scope.get("return_end") or return_end
        return intent

    target_day = extract_target_day(message) or len(plan_data.get("days", []) or [1])
    if is_return_revision(message):
        return_start, return_end = return_window_from_message(message)
        return {
            "type": "return_time_change",
            "target_day": target_day,
            "return_start": return_start,
            "return_end": return_end,
            "requires_tools": False,
        }

    if any(token in message for token in ("太累", "轻松一点", "少走路", "慢一点")):
        return {
            "type": "lighten_day",
            "target_day": target_day,
            "requires_tools": False,
        }

    if any(token in message for token in ("下雨", "雨天", "室内", "天气不好")):
        return {
            "type": "rainy_day_backup",
            "target_day": target_day,
            "requires_tools": True,
        }

    if any(token in message for token in ("预算降", "便宜一点", "省钱", "花费少")):
        return {
            "type": "reduce_budget",
            "target_day": target_day,
            "requires_tools": False,
        }

    replacement = extract_replacement_activity(message)
    if replacement:
        remove, add = replacement
        return {
            "type": "replace_activity",
            "target_day": target_day,
            "remove": remove,
            "add": add,
            "requires_tools": True,
        }
    return {}


def extract_replacement_activity(message: str) -> Optional[tuple[str, str]]:
    text = message or ""
    patterns = [
        r"(?:别去|不要去|不去|取消)(?P<remove>.+?)(?:了)?[，,。；;\s]*(?:换成|改成|替换成|换)(?P<add>.+)",
        r"(?:把)?(?P<remove>.+?)(?:换成|改成|替换成)(?P<add>.+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        remove = _clean_place_phrase(m.group("remove"))
        add = _clean_place_phrase(m.group("add"))
        if remove and add and remove != add:
            return remove, add
    return None


def _collect_revision_evidence(intent: dict, trip, tool_executor) -> list[dict]:
    if not intent.get("requires_tools"):
        return []
    if tool_executor is None:
        from travel_planning_agent.tool_runtime import execute_registered_tool
        tool_executor = execute_registered_tool

    if intent.get("type") == "rainy_day_backup":
        result = tool_executor("search_poi", {
            "destination": getattr(trip, "destination", ""),
            "category": "cultural",
            "context": "室内 博物馆 展览 商场",
        })
        return [{
            "tool": "search_poi",
            "status": getattr(result, "status", ""),
            "data": getattr(result, "data", ""),
            "evidence": getattr(result, "evidence", []),
        }]

    if intent.get("type") != "replace_activity" or not intent.get("add"):
        return []

    result = tool_executor("search_poi", {
        "destination": getattr(trip, "destination", ""),
        "category": "cultural",
        "context": intent["add"],
    })
    return [{
        "tool": "search_poi",
        "status": getattr(result, "status", ""),
        "data": getattr(result, "data", ""),
        "evidence": getattr(result, "evidence", []),
    }]


def apply_return_revision_to_plan(plan_data: dict, trip, message: str, context: dict | None = None) -> bool:
    days = list(plan_data.get("days") or [])
    if not days:
        return False

    target_day = extract_target_day(message) or len(days)
    target_day = max(1, min(target_day, len(days)))
    return_start, return_end = return_window_from_message(message)

    kept_days = [d for d in days if int(d.get("day_number", 0) or 0) <= target_day]
    target = next((d for d in kept_days if int(d.get("day_number", 0) or 0) == target_day), kept_days[-1])

    existing_return_cost = find_existing_return_cost(days)
    segments = []
    for seg in target.get("segments", []):
        if seg.get("type") == "accommodation":
            continue
        if dict_is_return_transport(seg, trip, context) or dict_is_hotel_return_transport(seg):
            continue
        start_min = time_to_minutes(seg.get("start_time"))
        if start_min is not None and start_min >= time_to_minutes(return_start):
            continue
        segments.append(seg)

    origin = trip_origin(trip, context)
    return_title = f"从{trip.destination}返回{origin}" if origin else f"离开{trip.destination}返程"
    segments.append({
        "segment_id": f"rev_return_{uuid.uuid4().hex[:8]}",
        "type": "transport",
        "title": return_title,
        "start_time": return_start,
        "end_time": return_end,
        "location": None,
        "estimated_cost": {"amount": existing_return_cost, "currency": "CNY"} if existing_return_cost else None,
        "tags": ["return"],
        "evidence_ids": [],
        "note": "根据用户修订：下午返程",
        "module": "afternoon",
    })
    target["segments"] = sorted(segments, key=lambda s: s.get("start_time") or "")
    target["theme"] = target.get("theme") or f"{trip.destination}返程日"

    plan_data["days"] = kept_days
    return True


def _normalize_replacement_day(
    day: dict,
    target_day: int,
    intent: dict,
    trip,
    context: dict | None,
    original_days: list[dict],
) -> dict:
    replacement = dict(day or {})
    replacement["day_number"] = int(replacement.get("day_number") or target_day)
    replacement["theme"] = replacement.get("theme") or replacement.get("day_theme") or f"{getattr(trip, 'destination', '')}修订日"
    replacement["day_note"] = replacement.get("day_note", "")

    segments = [dict(seg) for seg in replacement.get("segments", []) if isinstance(seg, dict)]
    for seg in segments:
        _normalize_segment_shape(seg)

    if intent.get("type") == "return_time_change":
        segments = _cleanup_return_day_segments(segments, intent, trip, context, original_days)

    replacement["segments"] = sorted(segments, key=lambda s: s.get("start_time") or "")
    return replacement


def _merge_day_by_scope(original_day: dict, replacement_day: dict, intent: dict) -> dict:
    target_module = intent.get("target_module")
    if not target_module:
        return replacement_day

    preserved = [
        dict(seg)
        for seg in original_day.get("segments", [])
        if seg.get("module") != target_module
    ]
    injected = [
        dict(seg)
        for seg in replacement_day.get("segments", [])
        if seg.get("module") == target_module or target_module == "return"
    ]

    merged = dict(original_day)
    merged["theme"] = replacement_day.get("theme") or original_day.get("theme")
    merged["day_note"] = replacement_day.get("day_note", original_day.get("day_note", ""))
    merged["segments"] = sorted(preserved + injected, key=lambda s: s.get("start_time") or "")
    return merged


def _remove_target_segment(plan_data: dict, target_segment: str) -> bool:
    changed = False
    for day in plan_data.get("days") or []:
        before = list(day.get("segments") or [])
        after = [seg for seg in before if seg.get("title") != target_segment]
        if len(after) != len(before):
            day["segments"] = after
            changed = True
    return changed


def _normalize_segment_shape(seg: dict) -> None:
    seg.setdefault("segment_id", f"rev_{uuid.uuid4().hex[:8]}")
    seg.setdefault("location", None)
    seg.setdefault("estimated_cost", {"amount": 0, "currency": "CNY"})
    if seg.get("estimated_cost") is None:
        seg["estimated_cost"] = {"amount": 0, "currency": "CNY"}
    seg.setdefault("tags", [])
    seg.setdefault("evidence_ids", [])
    seg.setdefault("note", "")
    seg.setdefault("module", _module_from_time(seg.get("start_time")))


def _cleanup_return_day_segments(
    segments: list[dict],
    intent: dict,
    trip,
    context: dict | None,
    original_days: list[dict],
) -> list[dict]:
    return_start = intent.get("return_start") or "15:00"
    return_end = intent.get("return_end") or "17:00"
    return_start_min = time_to_minutes(return_start) or 15 * 60
    cleaned = []
    return_seg = None
    for seg in segments:
        if seg.get("type") == "accommodation":
            continue
        if dict_is_hotel_return_transport(seg):
            continue
        if dict_is_return_transport(seg, trip, context):
            return_seg = seg
            continue
        start_min = time_to_minutes(seg.get("start_time"))
        if start_min is not None and start_min >= return_start_min:
            continue
        cleaned.append(seg)

    if return_seg is None:
        origin = trip_origin(trip, context)
        return_seg = {
            "segment_id": f"rev_return_{uuid.uuid4().hex[:8]}",
            "type": "transport",
            "title": f"从{getattr(trip, 'destination', '')}返回{origin}" if origin else f"离开{getattr(trip, 'destination', '')}返程",
            "estimated_cost": {"amount": find_existing_return_cost(original_days), "currency": "CNY"},
            "tags": ["return"],
            "evidence_ids": [],
            "note": "根据用户修订：返程",
            "location": None,
        }
    return_seg["start_time"] = return_start
    return_seg["end_time"] = return_end
    return_seg["type"] = "transport"
    return_seg.setdefault("estimated_cost", {"amount": find_existing_return_cost(original_days), "currency": "CNY"})
    return_seg.setdefault("tags", [])
    if "return" not in return_seg["tags"]:
        return_seg["tags"].append("return")
    return_seg["module"] = _module_from_time(return_start)
    _normalize_segment_shape(return_seg)
    cleaned.append(return_seg)
    return cleaned


def _module_from_time(value: Optional[str]) -> str:
    minutes = time_to_minutes(value)
    if minutes is None:
        return "afternoon"
    if minutes < 12 * 60:
        return "morning"
    if minutes < 18 * 60:
        return "afternoon"
    return "evening"


def _clean_place_phrase(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^第[一二三四五六七八九十\d]+天", "", text).strip()
    text = re.sub(r"^(上午|下午|晚上|中午|早上|先|再|去|把|我想|想|要)", "", text).strip()
    text = re.sub(r"(这个|那个|景点|活动|安排)$", "", text).strip()
    text = re.split(r"[，,。；;！!？?\n]", text, maxsplit=1)[0].strip()
    return text.strip(" ：:（）()[]【】")


def extract_target_day(message: str) -> Optional[int]:
    text = message or ""
    m = re.search(r"第(\d+)天", text)
    if m:
        return int(m.group(1))
    m = re.search(r"第([一二三四五六七八九十])天", text)
    if m:
        return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(m.group(1))
    return None


def return_window_from_message(message: str) -> tuple[str, str]:
    text = message or ""
    m = re.search(r"(\d{1,2})[:：点](\d{2})?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        start = f"{hour:02d}:{minute:02d}"
        end_hour = min(hour + 2, 23)
        return start, f"{end_hour:02d}:{minute:02d}"
    if "中午" in text:
        return "12:30", "14:30"
    if "下午" in text:
        return "15:00", "17:00"
    if "晚上" in text:
        return "18:00", "20:00"
    return "15:00", "17:00"


def find_existing_return_cost(days: list[dict]) -> float:
    for day in reversed(days):
        for seg in reversed(day.get("segments", [])):
            if seg.get("type") == "transport" and any(token in (seg.get("title") or "") for token in ("返程", "返回", "离开", "高铁", "航班")):
                cost = seg.get("estimated_cost") or {}
                return float(cost.get("amount") or 0)
    return 0


def dict_is_return_transport(seg: dict, trip, context: dict | None = None) -> bool:
    text = f"{seg.get('title') or ''} {seg.get('note') or ''}"
    origin = trip_origin(trip, context)
    if "返程" in text or "离开" in text:
        return True
    if origin and origin in text and any(token in text for token in ("返回", "回", "前往", "至", "到", "乘坐")):
        return True
    return False


def dict_is_hotel_return_transport(seg: dict) -> bool:
    text = f"{seg.get('title') or ''} {seg.get('note') or ''}"
    return any(token in text for token in ("返回", "回到", "回")) and any(token in text for token in ("酒店", "饭店", "宾馆", "民宿", "住宿"))


def trip_origin(trip, context: dict | None = None) -> str:
    extracted = (context or {}).get("extracted", {})
    return (getattr(trip, "origin", "") or extracted.get("origin") or "").strip()


def time_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value or ":" not in value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def format_plan_data_summary(plan_data: dict, trip) -> dict:
    total_cost = 0
    activity_count = 0
    for day in plan_data.get("days", []):
        for seg in day.get("segments", []):
            cost = seg.get("estimated_cost") or {}
            total_cost += float(cost.get("amount") or 0)
            if seg.get("type") == "activity":
                activity_count += 1
    return {
        "total_cost": total_cost,
        "activity_count": activity_count,
        "day_count": len(plan_data.get("days", [])),
        "destination": trip.destination,
    }


def format_plan_data_days_text(plan_data: dict) -> str:
    cat_map = {"transport": "路程", "activity": "游玩", "meal": "用餐", "accommodation": "住宿"}
    lines = []
    for day in plan_data.get("days", []):
        lines.append(f"📅 Day {day.get('day_number')} — {day.get('theme', '')}")
        if day.get("day_note"):
            lines.append(f"   {day['day_note']}")
        prev_type = None
        for seg in day.get("segments", []):
            seg_type = seg.get("type")
            if seg_type != prev_type:
                cat_name = cat_map.get(seg_type)
                if cat_name:
                    lines.append(f"  —— {cat_name} ——")
                prev_type = seg_type
            cost_data = seg.get("estimated_cost") or {}
            cost = f" ¥{float(cost_data.get('amount')):,.0f}" if cost_data.get("amount") else ""
            note = f" {seg.get('note')}" if seg.get("note") else ""
            lines.append(f"   {seg.get('start_time') or ''}-{seg.get('end_time') or ''} {seg.get('title') or ''}{cost}{note}")
        lines.append("")
    return "\n".join(lines).strip()
