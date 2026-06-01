"""Unified revision intent classifier: LLM first, rule fallback."""

from __future__ import annotations

import json
import logging
from typing import Optional

from travel_planning_agent.core.plan_revision import format_plan_data_days_text

logger = logging.getLogger(__name__)

_INTENT_ALIASES = {
    "change_return_time": "return_time_change",
}

REVISION_CLASSIFY_SYSTEM_PROMPT = """\
你是一个旅行行程修订意图分类器。根据用户消息和当前行程摘要，判断修改意图。

返回严格 JSON，不包含额外文本：

{
  "is_revision": true或false,
  "intent_type": "lighten_day|remove_segment|return_time_change|null",
  "target_day": 数字或null,
  "target_module": "morning|afternoon|evening|return|null",
  "target_segment": "具体景点/活动名"或null,
  "scope_type": "segment|day_module|day|unknown",
  "impact_level": "low|medium|high",
  "confidence": 0.0到1.0,
  "clarification_needed": true或false,
  "clarification_question": "追问内容"或"",
  "detail": "一句话描述修改意图"
}

规则：
- 与行程修改无关 → is_revision=false, intent_type=null。
- 意图明确（定位到天/时段/具体项目） → confidence >= 0.8, clarification_needed=false。
- 有修改意愿但范围模糊 → confidence < 0.8, clarification_needed=true。
- "不要太累/轻松一点/少走路/慢一点/别太赶" → intent_type: lighten_day
- "不去X/换掉X/取消X/不要X" → intent_type: remove_segment
- "晚点回/早点回/返程改X/改到下午回" → intent_type: return_time_change
- 以下情形均设为 clarification_needed=true：
  - "加一天/多待一天" → is_revision=true, intent_type=null
  - "下雨/雨天/室内" → is_revision=true, intent_type=null
  - "预算降/便宜一点" → is_revision=true, intent_type=null
  - "X换成Y/改X" → is_revision=true, intent_type=null
  - "改一下/调整一下/不太行" → is_revision=true, intent_type=null
"""


def _build_classify_message(message: str, plan_summary: str) -> str:
    return (
        f"当前行程摘要：\n{plan_summary}\n\n"
        f"用户消息：{message}\n\n"
        f"请分类修订意图。"
    )


def _validate_and_normalize(raw: dict) -> Optional[dict]:
    """Validate the classifier JSON strictly enough to reject normal plan JSON."""
    if "is_revision" not in raw:
        return None

    is_revision = bool(raw.get("is_revision", False))
    intent_raw = raw.get("intent_type")
    if is_revision and not intent_raw and not raw.get("clarification_needed"):
        return None

    intent_type = _INTENT_ALIASES.get(intent_raw, intent_raw) if intent_raw else None
    valid_types = {"lighten_day", "remove_segment", "return_time_change", None}
    if intent_type not in valid_types:
        return None

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None

    return {
        "is_revision": is_revision,
        "intent_type": intent_type,
        "target_day": raw.get("target_day") if isinstance(raw.get("target_day"), int) else None,
        "target_module": raw.get("target_module"),
        "target_segment": raw.get("target_segment"),
        "scope_type": raw.get("scope_type", "unknown"),
        "impact_level": raw.get("impact_level", "high"),
        "confidence": float(confidence),
        "clarification_needed": bool(raw.get("clarification_needed", False)),
        "clarification_question": raw.get("clarification_question", ""),
        "detail": raw.get("detail", ""),
        "classification_failed": False,
        "_source": "llm",
    }


def _classify_via_llm(llm_client, message: str, plan_summary: str) -> Optional[dict]:
    try:
        result = llm_client.generate(
            REVISION_CLASSIFY_SYSTEM_PROMPT,
            _build_classify_message(message, plan_summary),
            tools=None,
        )
        if not result.success:
            logger.warning("LLM revision intent classification failed: %s", result.error)
            return None

        raw = result.data
        if raw is None:
            raw = _extract_json_from_text(result.text)
        if raw is None:
            return None
        return _validate_and_normalize(raw)
    except Exception as exc:
        logger.warning("LLM revision intent classification raised: %s", exc)
        return None


def _extract_json_from_text(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if "```json" in text:
        try:
            inner = text.split("```json")[1].split("```")[0].strip()
            return json.loads(inner)
        except (json.JSONDecodeError, IndexError):
            pass
    if "```" in text:
        try:
            inner = text.split("```")[1].split("```")[0].strip()
            return json.loads(inner)
        except (json.JSONDecodeError, IndexError):
            pass
    return None


def _classify_via_rules(message: str, plan_data: dict, context: dict) -> dict:
    from travel_planning_agent.core.plan_revision import looks_like_plan_revision
    from travel_planning_agent.core.revision_scope_parser import parse_revision_scope

    is_revision = looks_like_plan_revision(message, context)
    parsed = parse_revision_scope(message, plan_data)
    change_type = parsed.get("change_type")
    intent_type = _INTENT_ALIASES.get(change_type, change_type) if change_type else None

    return {
        "is_revision": bool(is_revision and (parsed.get("matched") or parsed.get("clarification_needed"))),
        "intent_type": intent_type,
        "target_day": parsed.get("target_day"),
        "target_module": parsed.get("target_module"),
        "target_segment": parsed.get("target_segment"),
        "scope_type": parsed.get("scope_type", "unknown"),
        "impact_level": parsed.get("impact_level", "high"),
        "confidence": 0.70 if is_revision else 0.30,
        "clarification_needed": bool(parsed.get("clarification_needed")),
        "clarification_question": parsed.get("clarification_question", ""),
        "detail": "",
        "classification_failed": False,
        "_source": "rules",
    }


def classify_revision_intent(llm_client, message: str, plan_data: dict, context: dict) -> dict:
    plan_summary = format_plan_data_days_text(plan_data)
    result: Optional[dict] = None

    if llm_client is not None:
        result = _classify_via_llm(llm_client, message, plan_summary)
        if result is not None and result["confidence"] >= 0.5:
            return result
        if result is None:
            logger.info("LLM revision classification failed; falling back to rules")

    fallback = _classify_via_rules(message, plan_data, context)
    if result is not None:
        fallback["classification_failed"] = True
    return fallback
