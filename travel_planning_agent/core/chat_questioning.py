from typing import Optional


def normalize_followup_question(question: str) -> str:
    """Keep user-facing follow-up wording aligned with V1 profile options."""
    text = question or "请提供更多信息"
    asks_old_pace = (
        "慢/适中/快" in text
        or "slow/moderate/fast" in text
        or ("节奏" in text and "慢" in text and "适中" in text and "快" in text)
    )
    if asks_old_pace:
        return "请问你更偏向哪种旅行方式：轻松慢游、经典初游、美食深度，还是省钱优先？"
    return text


def normalize_known_field_question(question: str, extracted: dict) -> str:
    """Prevent the assistant from asking again for fields already extracted."""
    text = question or "请提供更多信息"
    asked_field = question_field(text)
    if asked_field and extracted.get(asked_field):
        return next_missing_question(extracted)
    return text


def question_field(question: str) -> Optional[str]:
    text = question or ""
    field_tokens = {
        "destination": ("目的地", "去哪里", "去哪", "城市"),
        "origin": ("出发城市", "从哪里", "从哪", "哪里出发", "哪个城市出发"),
        "start_date": ("出发日期", "日期", "哪天", "什么时候", "几号"),
        "days": ("天数", "几天", "多少天"),
        "budget": ("预算", "多少钱", "花费", "费用"),
        "travelers": ("几个人", "人数", "同行人", "人员"),
        "pace": ("节奏", "旅行方式", "偏向哪种"),
    }
    for field, tokens in field_tokens.items():
        if any(token in text for token in tokens):
            return field
    return None


def next_missing_question(extracted: dict) -> str:
    required_questions = [
        ("origin", "请问您从哪个城市出发？"),
        ("destination", "请问您想去哪个目的地？"),
        ("start_date", "请问您的出发日期是哪天？"),
        ("days", "请问您计划玩几天？"),
        ("budget", "请问您的预算是多少？"),
    ]
    for field, prompt in required_questions:
        if not extracted.get(field):
            return prompt
    if not extracted.get("pace") and not extracted.get("preferences_detail"):
        return "请问你更偏向哪种旅行方式：轻松慢游、经典初游、美食深度，还是省钱优先？"
    return "请补充还有哪些特别偏好，比如住宿、餐饮、交通或必去地点。"
