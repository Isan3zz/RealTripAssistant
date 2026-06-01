from __future__ import annotations

import re


def format_plan_view(plan_data: dict, *, trip=None, summary: dict | None = None) -> dict:
    origin = (getattr(trip, "origin", "") or "").strip()
    destination = (getattr(trip, "destination", "") or "").strip()
    days = [_format_day(day) for day in plan_data.get("days") or []]
    total_cost = sum(
        segment["estimated_cost"]["amount"]
        for day in days
        for segment in day["segments"]
        if segment.get("estimated_cost")
    )
    if summary and summary.get("total_cost") is not None:
        total_cost = float(summary.get("total_cost") or 0)

    day_count = int(getattr(trip, "days", 0) or len(days))
    budget_amount = float(getattr(trip, "budget", 0) or 0)
    title_parts = [part for part in [origin, destination] if part]
    title = f"{'至'.join(title_parts)}{day_count}日游" if title_parts else "行程规划"

    return {
        "schema_version": "plan.v1",
        "title": title,
        "origin": origin,
        "destination": destination,
        "day_count": day_count,
        "budget": {"amount": _clean_number(budget_amount), "currency": "CNY"},
        "total_cost": {"amount": _clean_number(total_cost), "currency": "CNY"},
        "summary": _format_summary(origin, destination, day_count, budget_amount, total_cost),
        "days": days,
    }


def _format_day(day: dict) -> dict:
    day_number = int(day.get("day_number") or 0)
    return {
        "day_number": day_number,
        "title": day.get("theme") or f"Day {day_number}",
        "note": day.get("day_note") or "",
        "segments": [_format_segment(segment) for segment in day.get("segments") or []],
    }


def _format_segment(segment: dict) -> dict:
    start = segment.get("start_time") or ""
    end = segment.get("end_time") or ""
    return {
        "segment_id": segment.get("segment_id") or "",
        "type": segment.get("type") or "activity",
        "module": segment.get("module") or _module_from_time(start),
        "start_time": start,
        "end_time": end,
        "time": f"{start}-{end}" if start or end else "",
        "title": segment.get("title") or "",
        "location": _format_location(segment.get("location")),
        "estimated_cost": _format_cost(segment.get("estimated_cost")),
        "tags": list(segment.get("tags") or []),
        "note": segment.get("note") or "",
        "why": segment.get("why") or "",
        "attention": _format_attention(segment),
    }


def _format_location(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {"name": value.get("name") or "", "city": value.get("city") or ""}
    return {"name": str(value), "city": ""}


def _format_cost(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {
            "amount": _clean_number(float(value.get("amount") or 0)),
            "currency": value.get("currency") or "CNY",
        }
    return {"amount": _clean_number(float(value or 0)), "currency": "CNY"}


def _format_attention(segment: dict) -> str:
    attention = (segment.get("attention") or "").strip()
    if attention:
        return attention

    note = (segment.get("note") or "").strip()
    if note and not _is_internal_note(note):
        return note

    if segment.get("type") == "transport" and _is_big_transport(segment):
        return "请以实际出票信息为准，提前确认出发站、检票口和到站交通。"
    return ""


def _is_internal_note(note: str) -> bool:
    return any(
        token in note
        for token in (
            "系统补齐",
            "用户明确要求",
            "根据用户修订",
        )
    )


def _is_big_transport(segment: dict) -> bool:
    text = f"{segment.get('title') or ''} {segment.get('note') or ''}"
    tags = set(segment.get("tags") or [])
    return bool({"intercity", "arrival", "return"} & tags) or bool(_extract_train_no(text) or _extract_flight_no(text)) or any(
        token in text for token in ("高铁", "动车", "列车", "火车", "航班", "飞机", "机场")
    )


def _extract_train_no(text: str) -> str:
    match = re.search(r"([GDCZKT]\d{1,5})", text or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _extract_flight_no(text: str) -> str:
    match = re.search(r"([A-Z]{2}\d{3,4})", text or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _module_from_time(value: str) -> str:
    if not value or ":" not in value:
        return "afternoon"
    hour = int(value.split(":", 1)[0])
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def _format_summary(origin: str, destination: str, days: int, budget: float, total: float) -> list[str]:
    route = " → ".join([part for part in [origin, destination] if part])
    items = []
    if route:
        items.append(route)
    if days:
        items.append(f"{days}天")
    if budget:
        items.append(f"预算 ¥{budget:,.0f}")
    items.append(f"预计 ¥{total:,.0f}")
    return items


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value
