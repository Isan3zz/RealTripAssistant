"""Parse verbose map route payloads into concise duration summaries."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from travel_planning_agent.types import RouteBrief


MODE_LABELS = {
    "driving": "驾车",
    "walking": "步行",
    "transit": "公交/地铁",
}


def summarize_route_duration(raw: Any, mode: str) -> str:
    """Return a compact Chinese duration summary from a Gaode MCP route result."""
    brief = parse_route_brief(raw, mode)

    if brief.duration_minutes is None:
        return brief.summary

    parts = [f"{MODE_LABELS.get(mode, '路线')}约{brief.duration_minutes}分钟"]
    if brief.duration_minutes >= 60:
        parts = [f"{MODE_LABELS.get(mode, '路线')}{format_duration(brief.duration_minutes * 60)}"]
    if brief.distance_meters is not None:
        parts.append(f"全程{format_distance(brief.distance_meters)}")
    if mode == "transit" and brief.walking_distance_meters is not None:
        parts.append(f"步行{format_distance(brief.walking_distance_meters)}")
    if mode == "transit" and brief.transit_lines:
        parts.append(f"乘坐{' → '.join(brief.transit_lines)}")
    return "，".join(parts)


def parse_route_brief(raw: Any, mode: str, origin: str = "", destination: str = "") -> RouteBrief:
    """Return structured route metrics from a Gaode MCP route result."""
    data = _extract_payload(raw)
    duration_seconds, distance_meters, walking_meters = _extract_route_metrics(data, mode)
    transit_lines = _extract_transit_lines(data) if mode == "transit" else []
    label = MODE_LABELS.get(mode, "路线")

    if duration_seconds is None:
        return RouteBrief(
            mode=mode,
            origin=origin,
            destination=destination,
            summary=f"{label}: 暂未查到路线用时",
        )

    duration_minutes = max(1, math.ceil(duration_seconds / 60))
    summary_parts = [f"{label}{format_duration(duration_seconds)}"]
    if distance_meters is not None:
        summary_parts.append(f"全程{format_distance(distance_meters)}")
    if mode == "transit" and walking_meters is not None:
        summary_parts.append(f"步行{format_distance(walking_meters)}")
    if mode == "transit" and transit_lines:
        summary_parts.append(f"乘坐{' → '.join(transit_lines)}")
    return RouteBrief(
        mode=mode,
        duration_minutes=duration_minutes,
        distance_meters=distance_meters,
        walking_distance_meters=walking_meters,
        transit_lines=transit_lines,
        origin=origin,
        destination=destination,
        summary="，".join(summary_parts),
    )


def format_duration(seconds: int | float | str) -> str:
    total_seconds = _to_number(seconds) or 0
    minutes = max(1, math.ceil(total_seconds / 60))
    if minutes < 60:
        return f"约{minutes}分钟"

    hours = minutes // 60
    remain = minutes % 60
    if remain == 0:
        return f"约{hours}小时"
    return f"约{hours}小时{remain}分钟"


def format_distance(meters: int | float | str) -> str:
    value = _to_number(meters) or 0
    if value >= 1000:
        km = value / 1000
        return f"约{km:.1f}公里"
    return f"约{int(round(value))}米"


def _extract_payload(raw: Any) -> Any:
    """Unwrap MCP content arrays and JSON text payloads."""
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict) and "text" in first:
            return _extract_payload(first["text"])
        return raw

    if isinstance(raw, dict) and "text" in raw:
        return _extract_payload(raw["text"])

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return raw
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw

    return raw


def _extract_route_metrics(data: Any, mode: str) -> tuple[int | None, int | None, int | None]:
    if not isinstance(data, dict):
        return None, None, None

    if mode == "transit":
        fastest = _select_fastest_transit(data)
        if fastest is None:
            return None, _int_or_none(data.get("distance")), None
        return (
            _int_or_none(fastest.get("duration")),
            _int_or_none(data.get("distance")),
            _int_or_none(fastest.get("walking_distance")),
        )

    route = data.get("route") if isinstance(data.get("route"), dict) else data
    paths = route.get("paths") if isinstance(route, dict) else None
    if not isinstance(paths, list) or not paths:
        return None, None, None

    path = next((p for p in paths if isinstance(p, dict) and _to_number(p.get("duration")) is not None), None)
    if path is None:
        return None, None, None
    return _int_or_none(path.get("duration")), _int_or_none(path.get("distance")), None


def _select_fastest_transit(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    transits = data.get("transits") or []
    candidates = [t for t in transits if isinstance(t, dict) and _to_number(t.get("duration")) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda t: _to_number(t.get("duration")) or float("inf"))


def _extract_transit_lines(data: Any) -> list[str]:
    fastest = _select_fastest_transit(data)
    if fastest is None:
        return []

    raw_segments = fastest.get("segments") or []
    segments = raw_segments if isinstance(raw_segments, list) else [raw_segments]
    lines: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for name in _iter_segment_line_names(segment):
            normalized = _normalize_line_name(name)
            if normalized and normalized not in seen:
                seen.add(normalized)
                lines.append(normalized)
    return lines


def _iter_segment_line_names(segment: dict[str, Any]):
    for key in ("bus", "subway", "railway"):
        yield from _iter_line_names_from_container(segment.get(key))
    yield from _iter_line_names_from_container(segment)


def _iter_line_names_from_container(container: Any):
    if not isinstance(container, dict):
        return

    for key in ("buslines", "busline", "lines", "line"):
        lines = container.get(key)
        if lines is None:
            continue
        if isinstance(lines, dict):
            lines = [lines]
        if not isinstance(lines, list):
            lines = [lines]
        for line in lines:
            if isinstance(line, dict):
                for name_key in ("name", "line_name", "busline_name", "title"):
                    if line.get(name_key):
                        yield line[name_key]
                        break
            elif isinstance(line, str):
                yield line

    for name_key in ("name", "line_name", "busline_name"):
        if container.get(name_key):
            yield container[name_key]


def _normalize_line_name(name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    text = re.split(r"[（(]", text, maxsplit=1)[0].strip()
    text = re.sub(r"^(乘坐|搭乘|换乘|转乘)", "", text).strip()
    text = re.split(r"[，,；;。]", text, maxsplit=1)[0].strip()
    text = text.replace("公交车", "").strip()
    return text[:40]


def _to_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _to_number(value)
    if number is None:
        return None
    return int(round(number))
