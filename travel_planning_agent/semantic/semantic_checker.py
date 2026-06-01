"""
semantic/semantic_checker.py — 3 条语义合理性判断

仅在确定性规则全部通过后触发（架构总纲 §Verifier 设计原则）。
每条判断调用 LLM，输出 SemanticCheckResult。
"""

import json
import logging
from typing import Any, Optional

from travel_planning_agent.types import PlanState, SemanticCheckResult
from travel_planning_agent.prompts import build_semantic_check_prompt

logger = logging.getLogger(__name__)


def _build_itinerary_text(state: PlanState) -> str:
    """将行程转换为文本描述。"""
    lines = []
    for day in state.days:
        lines.append(f"\nDay {day.day_number} — {day.theme}")
        for seg in day.segments:
            time_str = f"{seg.start_time or ''}-{seg.end_time or ''}"
            cost = ""
            if seg.estimated_cost and seg.estimated_cost.amount:
                cost = f" ¥{seg.estimated_cost.amount:,.0f}"
            tags = f" [{', '.join(seg.tags)}]" if seg.tags else ""
            lines.append(f"  {time_str} {seg.title}{tags}{cost}")
    return "\n".join(lines)


def _build_travelers_desc(state: PlanState) -> str:
    """格式化人员描述。"""
    if not state.constraints:
        return ""
    parts = []
    for t in state.constraints.travelers:
        labels = {"adult": "成人", "elderly": "老人", "child": "小孩"}
        parts.append(labels.get(t.age_group, t.age_group))
    return "、".join(parts)


def _parse_semantic_response(text: str) -> dict:
    """解析 LLM 返回的 JSON。"""
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if "```json" in text:
        try:
            return json.loads(text.split("```json")[1].split("```")[0].strip())
        except (json.JSONDecodeError, IndexError):
            pass
    if "```" in text:
        try:
            return json.loads(text.split("```")[1].split("```")[0].strip())
        except (json.JSONDecodeError, IndexError):
            pass
    return {}


def run_all_semantic_checks(llm_generate, state: PlanState) -> list[SemanticCheckResult]:
    """
    执行全部 3 条语义检查（S01-S03）。

    通过一次 LLM 调用完成所有判断，减少 token 消耗。
    """
    if not state.days:
        return []

    itinerary_text = _build_itinerary_text(state)
    travelers_desc = _build_travelers_desc(state)

    prompt = build_semantic_check_prompt(
        destination=state.constraints.destination if state.constraints else "",
        days=state.constraints.days if state.constraints else 0,
        travelers=travelers_desc,
        pace=state.constraints.pace if state.constraints else "moderate",
        budget=state.constraints.budget if state.constraints else 0,
        itinerary=itinerary_text,
    )

    # system prompt 已经在模板中内联，此处传空
    result = llm_generate("", prompt)

    if not result.success or not result.data:
        logger.warning("语义检查 LLM 调用失败: %s", result.error)
        return []

    data = result.data

    checks = []
    # S01 节奏合理性
    rhythm = data.get("rhythm", {})
    checks.append(SemanticCheckResult(
        check_id="S01",
        result=rhythm.get("result", "WARN"),
        detail=rhythm.get("detail", "无法判断"),
    ))

    # S02 多样性
    diversity = data.get("diversity", {})
    checks.append(SemanticCheckResult(
        check_id="S02",
        result=diversity.get("result", "WARN"),
        detail=diversity.get("detail", "无法判断"),
        affected_days=list(range(1, len(state.days) + 1)) if diversity.get("result") == "FAIL" else [],
    ))

    # S03 逻辑连贯
    flow = data.get("flow", {})
    checks.append(SemanticCheckResult(
        check_id="S03",
        result=flow.get("result", "WARN"),
        detail=flow.get("detail", "无法判断"),
    ))

    return checks
