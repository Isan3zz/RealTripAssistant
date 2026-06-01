"""Parse verbose POI payloads into concise planning-friendly summaries."""

from __future__ import annotations

import json
from typing import Any


CATEGORY_LABELS = {
    "cultural": "景点",
    "natural": "景点",
    "food": "美食",
    "shopping": "购物",
    "accommodation": "酒店",
}


def summarize_poi_search(raw: Any, destination: str, category: str, limit: int = 6) -> str:
    """Return a short POI list from Gaode MCP text-search results."""
    label = CATEGORY_LABELS.get(category, category or "POI")
    pois = parse_poi_briefs(raw, limit=limit)
    if not pois:
        return f"【POI】{destination}{label}: 暂未查到精确结果"

    lines = [f"【POI】{destination}{label}（取前{len(pois)}条）："]
    for poi in pois:
        parts = [poi["name"]]
        if poi.get("address"):
            parts.append(poi["address"])
        if poi.get("area"):
            parts.append(poi["area"])
        if poi.get("rating"):
            parts.append(f"评分{poi['rating']}")
        if poi.get("cost"):
            parts.append(f"人均¥{poi['cost']}")
        lines.append("- " + "｜".join(parts))
    return "\n".join(lines)


def parse_poi_briefs(raw: Any, limit: int = 8) -> list[dict[str, str]]:
    """Extract normalized POI records from MCP content or legacy POI lists."""
    payload = _extract_payload(raw)
    pois = _extract_pois(payload)
    briefs = []
    seen = set()
    for poi in pois:
        if not isinstance(poi, dict):
            continue
        brief = _normalize_poi(poi)
        if not brief.get("name"):
            continue
        key = brief.get("id") or f"{brief.get('name')}|{brief.get('address')}"
        if key in seen:
            continue
        seen.add(key)
        briefs.append(brief)
        if len(briefs) >= limit:
            break
    return briefs


def _extract_payload(raw: Any) -> Any:
    if isinstance(raw, list) and raw:
        if all(isinstance(item, dict) and ("name" in item or "_name" in item) for item in raw):
            return raw
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


def _extract_pois(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        pois = payload.get("pois") or payload.get("data") or payload.get("list") or []
        return pois if isinstance(pois, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _normalize_poi(poi: dict) -> dict[str, str]:
    biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    address = _stringify(poi.get("address") or poi.get("_address"))
    city = _stringify(poi.get("cityname") or poi.get("city") or "")
    area = _stringify(poi.get("adname") or poi.get("business_area") or "")
    if city and area and city not in area:
        area = f"{city}{area}"

    return {
        "id": _stringify(poi.get("id")),
        "name": _stringify(poi.get("name") or poi.get("_name")),
        "address": address,
        "area": area,
        "type": _stringify(poi.get("type") or poi.get("typecode")),
        "location": _stringify(poi.get("location")),
        "rating": _stringify(biz_ext.get("rating")),
        "cost": _stringify(biz_ext.get("cost")),
    }


def _stringify(value: Any) -> str:
    if value is None or value == []:
        return ""
    if isinstance(value, list):
        return "、".join(str(v) for v in value if v)
    return str(value).strip()
