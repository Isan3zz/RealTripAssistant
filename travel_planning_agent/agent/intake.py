"""
agent/intake.py — Intake Agent

处理多轮对话，逐步从用户自然语言中提取旅行约束。
约束完整后触发 Supervisor 启动规划流程。
"""

import json
import logging
import re
from datetime import date, timedelta
from typing import Optional

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    PlanState, Constraints, Traveler,
)
from travel_planning_agent.prompts import INTAKE_PROMPT
from travel_planning_agent.tools import EXTRACTION_TOOLS

logger = logging.getLogger(__name__)


class IntakeAgent(BaseAgent):
    """对话约束提取 Agent。"""

    agent_name = "intake"
    context_required = ContextRequirement(levels=[0, 4, 6])

    def handle(self, request: AgentRequest) -> AgentResponse:
        params = request.params
        user_message = params.get("message", "")
        deterministic_interests = extract_must_have_interests(user_message)
        deterministic_start_date = extract_relative_start_date(user_message)

        # 当前已提取的约束（展开 chat.py 存储的嵌套结构）
        extracted = params.get("extracted", {})
        if isinstance(extracted.get("extracted"), dict):
            extracted = extracted["extracted"]
        context_summary = request.context_summary

        # 构造 LLM 输入
        today_str = date.today().isoformat()
        parts = [f"[系统时间：{today_str}]"]

        if context_summary:
            parts.append(context_summary)

        if extracted:
            known = []
            labels = {"destination": "目的地", "start_date": "出发日期", "days": "天数",
                      "origin": "出发城市", "budget": "预算", "travelers": "人员",
                      "pace": "节奏", "transport_mode": "交通偏好", "interests": "必去项"}
            for k, v in extracted.items():
                if k == "extracted" or not v:
                    continue
                label = labels.get(k, k)
                known.append(f"{label}：{v}")
            if known:
                parts.append("已了解的信息：" + "，".join(known))

        parts.append(f"用户现在说：{user_message}")
        full_message = "\n\n".join(parts)

        # 调 LLM 提取（带 get_current_date 工具，让 LLM 获取真实日期推算年份）
        result = self.llm_client.generate(INTAKE_PROMPT, full_message, tools=EXTRACTION_TOOLS or None)

        if not result.success or not result.data:
            return AgentResponse(
                request_id=request.request_id,
                status="failed", data={},
                error="意图提取失败",
            )

        data = result.data

        if not data.get("complete"):
            # 还有信息要问 → 合并已提取字段，返回追问
            new_extracted = data.get("extracted", {})
            # 继承旧值，但排除嵌套的 "extracted" 键
            merged = {k: v for k, v in extracted.items() if k != "extracted"}
            for k, v in new_extracted.items():
                if v:  # 非 None 且非空字符串才覆盖，避免 LLM 返回 "" 冲掉旧值
                    merged[k] = v
            if deterministic_start_date and not merged.get("start_date"):
                merged["start_date"] = deterministic_start_date
            merged["interests"] = _merge_interests(merged.get("interests"), deterministic_interests)

            if _has_required_constraints(merged):
                try:
                    constraints = _build_constraints(merged)
                    return AgentResponse(
                        request_id=request.request_id,
                        status="success",
                        data={
                            "complete": True,
                            "constraints": constraints,
                            "raw_constraints_data": merged,
                        },
                        tokens_used=result.tokens_used,
                    )
                except Exception as e:
                    return AgentResponse(
                        request_id=request.request_id,
                        status="failed", data={},
                        error=f"约束解析失败: {e}",
                    )

            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={
                    "complete": False,
                    "question": data.get("question", "请提供更多信息"),
                    "extracted": merged,
                },
                tokens_used=result.tokens_used,
            )

        # 约束完整，构建 Constraints
        constraints_data = data.get("constraints", {})
        # 用历史记忆补充缺失字段（排除嵌套的 extracted 键）
        for k, v in extracted.items():
            if k == "extracted" or k in constraints_data and constraints_data.get(k):
                continue
            if v:
                constraints_data[k] = v
        if deterministic_start_date and not constraints_data.get("start_date"):
            constraints_data["start_date"] = deterministic_start_date
        constraints_data["interests"] = _merge_interests(
            constraints_data.get("interests") or constraints_data.get("must_have"),
            deterministic_interests,
        )

        try:
            constraints = _build_constraints(constraints_data)
            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={
                    "complete": True,
                    "constraints": constraints,
                    "raw_constraints_data": constraints_data,
                },
                tokens_used=result.tokens_used,
            )
        except Exception as e:
            return AgentResponse(
                request_id=request.request_id,
                status="failed", data={},
                error=f"约束解析失败: {e}",
            )


def _build_constraints(data: dict) -> Constraints:
    """从 LLM 提取的 dict 构建 Constraints 对象。"""
    start_date_str = data.get("start_date", "")
    try:
        start_date = date.fromisoformat(start_date_str) if start_date_str else date.today()
    except ValueError:
        start_date = date.today()

    travelers_str = data.get("travelers", "2位成人")
    travelers = _parse_travelers_simple(travelers_str)

    return Constraints(
        destination=data.get("destination", ""),
        start_date=start_date,
        days=data.get("days", 3),
        travelers=travelers,
        budget=float(data.get("budget", 5000)),
        origin=data.get("origin", ""),
        pace=data.get("pace", "moderate"),
        preferences_detail=data.get("preferences_detail", ""),
        transport_mode=data.get("transport_mode", ""),
        interests=_normalize_interests(data.get("interests") or data.get("must_have")),
    )


def extract_relative_start_date(text: str) -> str:
    value = text or ""
    relative_days = (
        ("大后天", 3),
        ("后天", 2),
        ("明天", 1),
        ("明早", 1),
        ("明日", 1),
        ("今天", 0),
        ("今日", 0),
    )
    for token, delta in relative_days:
        if token in value:
            return (date.today() + timedelta(days=delta)).isoformat()
    return ""


def _has_required_constraints(data: dict) -> bool:
    required = ("destination", "start_date", "days", "origin", "budget")
    return all(data.get(field) not in (None, "") for field in required)


def extract_must_have_interests(text: str) -> list[str]:
    """Extract simple Chinese must-visit phrases from raw user text."""
    value = (text or "").strip()
    if not value:
        return []

    interests: list[str] = []
    for marker in ("我必须去", "必须去", "一定要去", "一定去", "必去", "想去"):
        start = 0
        while True:
            idx = value.find(marker, start)
            if idx == -1:
                break
            before = value[:idx]
            after = value[idx + len(marker):]
            if marker in ("我必须去", "必须去", "一定去", "必去"):
                candidate = _clean_interest_clause(before, take_last=True)
            else:
                candidate = _clean_interest_clause(after, take_last=False)
            if candidate:
                interests.append(candidate)
            start = idx + len(marker)

    return _normalize_interests(interests)


def _clean_interest_clause(text: str, take_last: bool) -> str:
    parts = [p.strip() for p in re.split(r"[，,。；;！!？?\n]", text or "") if p.strip()]
    if not parts:
        return ""
    candidate = parts[-1] if take_last else parts[0]
    candidate = re.sub(r"^(我|我们|还|也|另外|然后|最好|希望|想|要|去)", "", candidate).strip()
    candidate = re.sub(r"(我|我们|也|还|一定|必须|想|要|去)$", "", candidate).strip()
    candidate = re.sub(r"^(参观|游览|看看|打卡)", "", candidate).strip()
    candidate = re.split(r"(?:玩|逛|吃|住|坐|预算|喜欢|跟|和|从|到)", candidate, maxsplit=1)[0].strip() or candidate
    if len(candidate) < 2 or len(candidate) > 30:
        return ""
    return candidate


def _merge_interests(*values) -> list[str]:
    merged: list[str] = []
    for value in values:
        for item in _normalize_interests(value):
            if item not in merged:
                merged.append(item)
    return merged


def _normalize_interests(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[、,，;；\n]", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    interests: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        text = re.sub(r"^(必须|一定|必去|想去|去|参观|游览)", "", text).strip()
        text = re.sub(r"(必须去|一定要去|必去|我必须去)$", "", text).strip()
        if text and text not in interests:
            interests.append(text)
    return interests


def _parse_travelers_simple(text: str) -> list[Traveler]:
    """简单解析人员描述。"""
    from travel_planning_agent.utils import parse_travelers
    try:
        return parse_travelers(text) if text else [Traveler(age_group="adult")]
    except Exception:
        return [Traveler(age_group="adult")]
