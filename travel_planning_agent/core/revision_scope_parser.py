from __future__ import annotations

import re


DAY_PATTERNS = [
    (re.compile(r"最后一天"), lambda plan: len(plan.get("days") or [])),
    (re.compile(r"第([一二三四五六七八九十\d]+)天"), None),
    (re.compile(r"\bday\s*(\d+)\b", re.I), None),
]

MODULE_MAP = {
    "上午": "morning",
    "中午": "afternoon",
    "下午": "afternoon",
    "晚上": "evening",
    "返程": "return",
}

LIGHTEN_TOKENS = ("轻松一点", "少走路", "慢一点", "别太赶")
RAINY_TOKENS = ("下雨", "雨天", "室内")
REMOVE_TOKENS = ("换掉", "不要", "去掉", "取消")
RETURN_TOKENS = ("晚一点回去", "改到下午", "返程改晚")
APPEND_DAY_TOKENS = ("多玩一天", "多待一天", "还能玩一天", "加一天", "新增一天")
GLOBAL_TRANSPORT_TOKENS = ("坐飞机", "改飞机", "改高铁", "改动车")
AMBIGUOUS_FEEDBACK_TOKENS = ("感觉不太对", "改一下", "调整一下", "不太行")


def parse_revision_scope(message: str, plan_data: dict) -> dict:
    text = (message or "").strip()
    parsed = {
        "matched": False,
        "target_day": _extract_day(text, plan_data),
        "target_module": _extract_module(text),
        "target_segment": _extract_unique_segment(text, plan_data),
        "change_type": _extract_change_type(text),
        "scope_type": "unknown",
        "impact_level": "high",
        "replacement_text": None,
        "clarification_needed": False,
        "clarification_question": "",
    }

    if any(token in text for token in APPEND_DAY_TOKENS):
        parsed.update(
            {
                "matched": True,
                "change_type": "append_day",
                "scope_type": "append",
                "impact_level": "high",
                "clarification_needed": True,
                "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
            }
        )
        return parsed

    if any(token in text for token in GLOBAL_TRANSPORT_TOKENS):
        parsed.update(
            {
                "matched": True,
                "change_type": "change_transport_mode",
                "scope_type": "global",
                "impact_level": "high",
                "clarification_needed": True,
                "clarification_question": "你是想只改返程，还是整趟交通方式都调整？",
            }
        )
        return parsed

    if any(token in text for token in AMBIGUOUS_FEEDBACK_TOKENS):
        parsed.update(
            {
                "matched": False,
                "change_type": "ambiguous_feedback",
                "scope_type": "unknown",
                "impact_level": "high",
                "clarification_needed": True,
                "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
            }
        )
        return parsed

    if parsed["target_segment"] and parsed["change_type"] is None:
        parsed["change_type"] = "remove_segment"

    if parsed["change_type"] and (
        parsed["target_day"] or parsed["target_module"] or parsed["target_segment"]
    ):
        if parsed["target_segment"]:
            parsed["scope_type"] = "segment"
            parsed["impact_level"] = "low"
        elif parsed["target_day"] and parsed["target_module"]:
            parsed["scope_type"] = "day_module"
            parsed["impact_level"] = "low"
        elif parsed["target_day"]:
            parsed["scope_type"] = "day"
            parsed["impact_level"] = "medium"
        parsed["matched"] = True
        return parsed

    parsed["clarification_needed"] = True
    parsed["clarification_question"] = "你想改哪一天，还是改某个具体景点/时段？"
    return parsed


def _extract_day(text: str, plan_data: dict) -> int | None:
    for pattern, resolver in DAY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if resolver is not None:
            return resolver(plan_data)
        return _cn_number_to_int(match.group(1))
    return None


def _extract_module(text: str) -> str | None:
    for token, module in MODULE_MAP.items():
        if token in text:
            return module
    return None


def _extract_unique_segment(text: str, plan_data: dict) -> str | None:
    matches: list[str] = []
    for day in plan_data.get("days") or []:
        for seg in day.get("segments") or []:
            title = (seg.get("title") or "").strip()
            if title and title in text:
                matches.append(title)
    unique_matches = list(dict.fromkeys(matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def _extract_change_type(text: str) -> str | None:
    if any(token in text for token in LIGHTEN_TOKENS):
        return "lighten_day"
    if any(token in text for token in RAINY_TOKENS):
        return "rainy_day_backup"
    if any(token in text for token in REMOVE_TOKENS):
        return "remove_segment"
    if any(token in text for token in RETURN_TOKENS):
        return "change_return_time"
    return None


def _cn_number_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)

    mapping = {
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
    return mapping.get(token)
