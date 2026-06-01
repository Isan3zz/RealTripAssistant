"""RevisionAgent — local plan patch generation for existing itineraries."""

from __future__ import annotations

import json
import logging
from typing import Any

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import AgentRequest, AgentResponse, ContextRequirement

logger = logging.getLogger(__name__)


class RevisionAgent(BaseAgent):
    """Generate a replacement day for a bounded change request.

    Tool use is intentionally disabled here. The runtime gathers any required
    evidence first, then gives the agent a closed context for one JSON response.
    """

    agent_name = "revision"
    context_required = ContextRequirement(levels=[0, 2, 4, 5, 6])

    def handle(self, request: AgentRequest) -> AgentResponse:
        try:
            day = self.revise_day(
                plan_data=request.params.get("plan_data") or {},
                trip_info=request.params.get("trip_info") or {},
                intent=request.params.get("intent") or {},
                evidence=request.params.get("evidence") or [],
            )
            if not day:
                return AgentResponse(request_id=request.request_id, status="failed", data={}, error="修订生成失败")
            return AgentResponse(request_id=request.request_id, status="success", data={"day": day})
        except Exception as e:
            logger.exception("RevisionAgent failed")
            return AgentResponse(request_id=request.request_id, status="failed", data={}, error=str(e))

    def revise_day(
        self,
        plan_data: dict[str, Any],
        trip_info: dict[str, Any],
        intent: dict[str, Any],
        evidence: list[Any],
    ) -> dict[str, Any]:
        target_day = int(intent.get("target_day") or 1)
        original_day = _find_day(plan_data, target_day) or {}
        system_prompt = _build_revision_prompt()
        payload = {
            "trip": trip_info,
            "intent": intent,
            "target_day": original_day,
            "all_days_summary": [
                {
                    "day_number": d.get("day_number"),
                    "theme": d.get("theme"),
                    "segments": [
                        {
                            "type": s.get("type"),
                            "title": s.get("title"),
                            "start_time": s.get("start_time"),
                            "end_time": s.get("end_time"),
                        }
                        for s in d.get("segments", [])
                    ],
                }
                for d in plan_data.get("days", [])
            ],
            "evidence": evidence,
        }
        result = self.llm_client.generate(system_prompt, json.dumps(payload, ensure_ascii=False, indent=2), tools=None)
        if not result.success or not result.data:
            return {}
        return _extract_day(result.data, target_day)


def _find_day(plan_data: dict[str, Any], day_number: int) -> dict[str, Any] | None:
    for day in plan_data.get("days", []):
        if int(day.get("day_number") or 0) == day_number:
            return day
    return None


def _extract_day(data: dict[str, Any], target_day: int) -> dict[str, Any]:
    if isinstance(data.get("day"), dict):
        return data["day"]
    if isinstance(data.get("replacement_day"), dict):
        return data["replacement_day"]
    if isinstance(data.get("days"), list):
        for day in data["days"]:
            if int(day.get("day_number") or 0) == target_day:
                return day
    if isinstance(data.get("segments"), list):
        return {
            "day_number": data.get("day_number") or target_day,
            "theme": data.get("theme") or data.get("day_theme") or "行程修订",
            "day_note": data.get("day_note", ""),
            "segments": data["segments"],
        }
    if isinstance(data.get("modules"), dict):
        segments = []
        for module_name in ("morning", "afternoon", "evening"):
            mod = data["modules"].get(module_name) or {}
            mod_segments = mod.get("segments", mod if isinstance(mod, list) else [])
            for seg in mod_segments:
                seg.setdefault("module", module_name)
                segments.append(seg)
        return {
            "day_number": data.get("day_number") or target_day,
            "theme": data.get("day_theme") or data.get("theme") or "行程修订",
            "day_note": data.get("day_note", ""),
            "segments": segments,
        }
    return data if isinstance(data, dict) else {}


def _build_revision_prompt() -> str:
    return """你是 RealTrip 的局部行程修订 Agent。你只根据给定的原计划、用户修改意图和证据，重写目标日行程。

硬性规则：
1. 只输出纯 JSON，不要 markdown。
2. 只生成目标日 replacement_day，不生成整套行程。
3. 不要调用工具；证据已经在输入中。
4. 尽量保留不受影响的餐饮/活动，但必须让目标日时间连续、无重叠。
5. 若 intent.type=return_time_change，返程交通必须是最后一个 segment，且不得保留返程后的住宿、回酒店、晚餐、夜游。
6. 若 intent.type=replace_activity，必须移除 remove，加入 add，并根据 evidence 安排合理时段。
7. 每个 segment 必须包含 type/title/start_time/end_time/location/estimated_cost/tags/evidence_ids/note/module 字段，未知费用填 0。

输出格式：
{
  "replacement_day": {
    "day_number": 2,
    "theme": "修订后的主题",
    "day_note": "",
    "segments": [
      {
        "segment_id": "可复用原 id 或留空",
        "type": "transport/activity/meal/accommodation",
        "title": "名称",
        "start_time": "HH:MM",
        "end_time": "HH:MM",
        "location": {"name": "地点", "city": "城市"},
        "estimated_cost": {"amount": 0, "currency": "CNY"},
        "tags": [],
        "evidence_ids": [],
        "note": "",
        "module": "morning/afternoon/evening"
      }
    ]
  }
}
"""
