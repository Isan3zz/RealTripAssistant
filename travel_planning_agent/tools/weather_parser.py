"""Parse verbose weather payloads into concise travel guidance."""

from __future__ import annotations

import json
from typing import Any


RAIN_KEYWORDS = ("雨", "雪", "雷", "阵雨")
HOT_TEMP = 30
COLD_TEMP = 8
LARGE_TEMP_DIFF = 10


def summarize_weather(raw: Any, city: str, date: str = "", limit: int = 3) -> str:
    payload = _extract_payload(raw)
    forecasts = _extract_forecasts(payload)
    if not forecasts:
        return f"【天气】{city}: 暂未查到天气预报"

    selected = _select_forecasts(forecasts, date, limit)
    city_name = _city_name(payload, city)
    lines = [f"【天气】{city_name}："]
    for forecast in selected:
        brief = _normalize_forecast(forecast)
        line = (
            f"- {brief['date']} {brief['dayweather']}/{brief['nightweather']}，"
            f"{brief['nighttemp']}~{brief['daytemp']}°C，"
            f"{brief['daywind']}风{brief['daypower']}级"
        )
        advice = _weather_advice(brief)
        if advice:
            line += f"；{advice}"
        lines.append(line)
    return "\n".join(lines)


def parse_weather_briefs(raw: Any) -> list[dict[str, str]]:
    payload = _extract_payload(raw)
    return [_normalize_forecast(f) for f in _extract_forecasts(payload)]


def _extract_payload(raw: Any) -> Any:
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


def _extract_forecasts(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        forecasts = payload.get("forecasts") or []
        return forecasts if isinstance(forecasts, list) else []
    return []


def _select_forecasts(forecasts: list[dict], date: str, limit: int) -> list[dict]:
    if date:
        for idx, forecast in enumerate(forecasts):
            if str(forecast.get("date", "")) == date:
                return forecasts[idx:idx + limit]
    return forecasts[:limit]


def _city_name(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        return str(payload.get("city") or fallback)
    return fallback


def _normalize_forecast(forecast: dict) -> dict[str, str]:
    return {
        "date": str(forecast.get("date") or ""),
        "dayweather": str(forecast.get("dayweather") or ""),
        "nightweather": str(forecast.get("nightweather") or ""),
        "daytemp": str(forecast.get("daytemp") or forecast.get("daytemp_float") or ""),
        "nighttemp": str(forecast.get("nighttemp") or forecast.get("nighttemp_float") or ""),
        "daywind": str(forecast.get("daywind") or ""),
        "daypower": str(forecast.get("daypower") or ""),
    }


def _weather_advice(brief: dict[str, str]) -> str:
    advice = []
    weather_text = brief.get("dayweather", "") + brief.get("nightweather", "")
    daytemp = _to_float(brief.get("daytemp"))
    nighttemp = _to_float(brief.get("nighttemp"))

    if any(keyword in weather_text for keyword in RAIN_KEYWORDS):
        advice.append("带伞，室外活动留备选")
    if daytemp is not None and daytemp >= HOT_TEMP:
        advice.append("注意防晒补水")
    if nighttemp is not None and nighttemp <= COLD_TEMP:
        advice.append("早晚偏冷")
    if daytemp is not None and nighttemp is not None and daytemp - nighttemp >= LARGE_TEMP_DIFF:
        advice.append("温差较大")
    return "；".join(advice)


def _to_float(value: str) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
