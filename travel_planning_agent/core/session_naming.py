"""Session title generation for resumable chat sessions."""

from __future__ import annotations

import re
from typing import Any

from travel_planning_agent.types import Constraints

_MAX_TITLE_LENGTH = 28


def generate_session_title(llm: Any, constraints: Constraints, user_message: str = "") -> str:
    fallback = fallback_session_title(constraints)
    if not llm:
        return fallback

    try:
        result = llm.generate(
            "You name travel planning chat sessions. Return JSON only.",
            (
                "Create a short Chinese session title, no punctuation, no quotes, "
                "no more than 14 Chinese characters or 28 ASCII characters.\n"
                f"Origin: {constraints.origin or ''}\n"
                f"Destination: {constraints.destination}\n"
                f"Days: {constraints.days}\n"
                f"Pace: {constraints.pace}\n"
                f"Transport: {constraints.transport_mode or ''}\n"
                f"Must have: {', '.join(constraints.interests or [])}\n"
                f"User message: {user_message or ''}\n"
                'Return exactly: {"title":"..."}'
            ),
            tools=None,
        )
    except Exception:
        return fallback

    title = ""
    if getattr(result, "success", False):
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            title = str(data.get("title") or "").strip()
        if not title:
            title = str(getattr(result, "text", "") or "").strip()
    return clean_session_title(title) or fallback


def fallback_session_title(constraints: Constraints) -> str:
    destination = (constraints.destination or "Trip").strip()
    origin = (constraints.origin or "").strip()
    days = constraints.days or 1
    if origin and origin != destination:
        return f"{origin} to {destination} {days}d"
    return f"{destination} {days}d Trip"


def clean_session_title(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    text = text.strip("\"'`“”‘’ ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text.startswith("{"):
        return ""
    if len(text) > _MAX_TITLE_LENGTH:
        text = text[:_MAX_TITLE_LENGTH].rstrip()
    return text
