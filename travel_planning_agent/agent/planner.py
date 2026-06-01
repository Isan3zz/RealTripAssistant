"""
agent/planner.py — Planner Agent (Phase 3 模块化)

模块级规划：每次只规划一个 (天, 时间段) 的行程。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    Constraints, Segment, SegmentType,
    Location, Cost, Evidence, Pin,
)
from travel_planning_agent.prompts import (
    ConstraintsMessage,
    get_module_prompt,
    get_day_prompt,
)
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.utils import make_segment_id

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """行程编排 Agent。"""

    agent_name = "planner"
    context_required = ContextRequirement(levels=[0, 2, 3, 4, 5])

    def handle(self, request: AgentRequest) -> AgentResponse:
        params = request.params
        mode = params.get("mode", "day_draft")

        try:
            if mode == "module_refine":
                plan_data = self._refine_module(params)
            elif mode == "module_revise":
                plan_data = self._revise_module(params)
            elif mode == "day_draft":
                plan_data = self._draft_day(params)
                return AgentResponse(
                    request_id=request.request_id,
                    status="success",
                    data=plan_data,
                    tokens_used=plan_data.get("tokens_used", 0),
                )
            else:
                return AgentResponse(
                    request_id=request.request_id,
                    status="failed", data={},
                    error=f"未知规划模式: {mode}",
                )

            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={
                    "segments": plan_data.get("segments", []),
                    "evidence": plan_data.get("evidence", {}),
                    "research_needs": plan_data.get("research_needs", []),
                },
                tokens_used=plan_data.get("tokens_used", 0),
            )

        except Exception as e:
            logger.error("Planner 失败: %s", str(e))
            return AgentResponse(
                request_id=request.request_id,
                status="failed", data={},
                error=str(e),
            )

    # ═══════════════════════════════════════════════════════
    #  按天规划方法（Phase 3.5 流水线并行）
    # ═══════════════════════════════════════════════════════

    def _draft_day(self, params: dict) -> dict:
        """为单天生成完整行程（morning+afternoon+evening三个模块）。"""
        day_number = params.get("day_number", 1)
        constraints: Constraints = params.get("constraints")
        if not constraints:
            return {"day_theme": "", "modules": {}, "research_needs": [], "evidence": {}, "tokens_used": 0}

        locked_segments_text = params.get("locked_segments_text", "")
        total_budget = params.get("total_budget", 0.0)
        spent_budget = params.get("spent_budget", 0.0)
        available_budget = params.get("available_budget", total_budget)
        remaining_days = params.get("remaining_days", 1)
        trip_id = params.get("trip_id", "unknown")

        # 前一天住宿信息
        prev_accommodation = params.get("previous_day_accommodation") or {}
        if prev_accommodation:
            # 格式化结束状态文本
            end_time = prev_accommodation.get("end_time", "18:00")
            loc = prev_accommodation.get("end_location", {})
            loc_name = loc.get("name", "") if loc else ""
            hotel = prev_accommodation.get("hotel_name", loc_name)
            prev_state = f"前一天结束时间：{end_time}，当晚入住：{hotel}（{loc.get('city','')}）。当天第一个活动从{hotel}出发。"
        else:
            origin = constraints.origin if constraints else ""
            prev_state = f"行程起始{'，从'+origin+'出发' if origin else ''}。"

        # 第一天/最后一天特殊指令
        is_last = (remaining_days == 1)
        first_day_special = ""
        last_day_special = ""
        first_day_constraint = ""
        last_day_constraint = ""

        if day_number == 1 and not prev_accommodation:
            origin = constraints.origin if constraints else ""
            is_local = origin and constraints.destination and origin == constraints.destination
            if is_local:
                first_day_special = "- 本地游，无需到达交通，直接安排上午活动。"
            elif constraints.transport_mode:
                first_day_special = f"- 第1天 morning 需包含从出发地到目的地的到达交通（用户指定{constraints.transport_mode}）"
            else:
                first_day_special = "- 第1天 morning 需包含从出发地到目的地的到达交通。"
            first_day_constraint = "8a. 第1天 morning 必须包含从出发地到目的地的到达交通（transport 段）"

        if is_last:
            last_day_special = "- 最后一天：需在 afternoon 或 evening 安排返程交通。"
            last_day_constraint = "15a. 最后一天必须包含返程交通（transport 段）"

        constraints_text = ConstraintsMessage.build(constraints).to_text()
        prev_day_plan_text = params.get("prev_day_plan_text", "") or "（行程起始，无前一天行程）"

        prompt = get_day_prompt("draft",
            day_number=day_number,
            constraints_text=constraints_text,
            previous_day_end_state_text=prev_state,
            previous_day_plan_text=prev_day_plan_text,
            locked_segments_text=locked_segments_text or "（无已锁定行程）",
            total_budget=total_budget,
            spent_budget=spent_budget,
            available_budget=available_budget,
            remaining_days=remaining_days,
            first_day_special=first_day_special,
            last_day_special=last_day_special,
            first_day_constraint=first_day_constraint,
            last_day_constraint=last_day_constraint,
        )

        result = self.llm_client.generate(prompt, f"请规划第{day_number}天的完整行程。", tools=None)

        if not result.success:
            logger.error("按天初稿生成失败: %s", result.error)
            if result.text:
                logger.warning("LLM 原始返回前 500 字: %s", result.text[:500])
            return {"day_theme": "", "modules": {}, "research_needs": [], "evidence": {}, "tokens_used": 0}

        day_data = self._parse_day_segments(result, trip_id, day_number)
        if not day_data.get("modules"):
            logger.warning("按天初稿解析出 0 个模块，LLM 原始返回前 300 字: %s",
                          (result.text or "")[:300])

        day_data["research_needs"] = result.data.get("research_needs", []) if result.data else []
        day_data["day_theme"] = result.data.get("day_theme", "") if result.data else ""
        day_data["tokens_used"] = result.tokens_used
        return day_data

    def _refine_module(self, params: dict) -> dict:
        """用 Researcher 数据精修单个时间段的段。"""
        module_name = params.get("module_name", "morning")
        day_number = params.get("day_number", 1)
        segments_data = params.get("segments", [])
        evidence_list = params.get("evidence", [])

        # 构建初稿 JSON
        segs_json = []
        for s in segments_data:
            item = {"type": s.type.value, "title": s.title,
                    "start_time": s.start_time, "end_time": s.end_time}
            if s.estimated_cost:
                item["estimated_cost"] = {"amount": s.estimated_cost.amount, "currency": s.estimated_cost.currency}
            if s.tags:
                item["tags"] = s.tags
            segs_json.append(item)
        draft_text = json.dumps({"segments": segs_json}, ensure_ascii=False, indent=2)

        # 构建证据文本
        ev_parts = []
        for ev in evidence_list:
            claim = ev.get("claim", "") if isinstance(ev, dict) else ev.claim
            if claim:
                ev_parts.append(f"  {claim}")
        evidence_text = "\n".join(ev_parts) if ev_parts else "（无新参考信息）"

        prompt = get_module_prompt("refine",
            day_number=day_number,
            module_name=module_name,
            draft_segments_text=draft_text,
            evidence_text=evidence_text,
        )

        from travel_planning_agent.tools import PLANNER_TOOLS
        result = self.llm_client.generate(prompt, "请精修当前时间段的行程。", tools=PLANNER_TOOLS or None)

        if not result.success or not result.data:
            logger.error("模块精修失败: %s", result.error)
            return {"segments": segments_data, "evidence": {}, "tokens_used": 0}

        segments, evidence = self._parse_module_segments(
            result, params.get("trip_id", "unknown"), day_number, module_name
        )

        if not segments:
            logger.warning("模块精修产出空段，回退到初稿")
            segments = segments_data

        return {
            "segments": segments,
            "evidence": evidence,
            "tokens_used": result.tokens_used,
        }

    def _revise_module(self, params: dict) -> dict:
        """根据校验错误修正单个时间段的段。"""
        module_name = params.get("module_name", "morning")
        day_number = params.get("day_number", 1)
        segments_data = params.get("segments", [])
        validation_errors = params.get("validation_errors", "")
        budget_summary = params.get("budget_summary", "无")
        revision_count = params.get("revision_count", 0)
        max_revisions = params.get("max_revisions", 2)

        prompt = get_module_prompt("revise",
            day_number=day_number,
            module_name=module_name,
            validation_errors=validation_errors,
            budget_summary=budget_summary,
            revision_count=revision_count,
            max_revisions=max_revisions,
        )

        # 传给 LLM 看看当前段的结构
        segs_json = []
        for s in segments_data:
            item = {"type": s.type.value, "title": s.title,
                    "start_time": s.start_time, "end_time": s.end_time}
            if s.estimated_cost:
                item["estimated_cost"] = {"amount": s.estimated_cost.amount, "currency": s.estimated_cost.currency}
            if s.tags:
                item["tags"] = s.tags
            segs_json.append(item)
        current_text = json.dumps({"segments": segs_json}, ensure_ascii=False, indent=2)

        messages = [
            {"role": "user", "content": f"当前第{day_number}天{module_name}的行程：\n\n{current_text}"},
            {"role": "user", "content": prompt},
        ]

        result = self.llm_client.generate_with_context("", messages, tools=None)

        if not result.success or not result.data:
            logger.error("模块修订失败: %s", result.error)
            return {"segments": segments_data, "evidence": {}, "tokens_used": 0}

        segments, evidence = self._parse_module_segments(
            result, params.get("trip_id", "unknown"), day_number, module_name
        )

        if not segments:
            segments = segments_data

        return {
            "segments": segments,
            "evidence": evidence,
            "tokens_used": result.tokens_used,
        }

    def _parse_module_segments(self, result: LLMResult, trip_id: str, day_number: int, module_name: str) -> tuple:
        """
        解析模块级 LLM 输出的 segments。
        模块级输出格式: {"segments": [...]}（无 days 包装）
        """
        import uuid
        from datetime import datetime

        segments = []
        evidence_dict = {}

        if not result.data:
            return segments, evidence_dict, {}

        # 兼容两种格式：直接 segments 或包在 day 里
        segs_data = result.data.get("segments", [])
        if not segs_data and "days" in result.data:
            for d in result.data["days"]:
                segs_data.extend(d.get("segments", []))

        for seg_data in segs_data:
            seg_id = make_segment_id(
                trip_id,
                seg_data.get("title", ""),
                seg_data.get("start_time", ""),
                seg_data.get("end_time", ""),
                day_number,
            )

            # 解析证据
            ev_ids = []
            for ev_data in seg_data.get("evidence", []):
                ev_id = f"{trip_id}_ev_{uuid.uuid4().hex[:6]}"
                evidence_dict[ev_id] = Evidence(
                    evidence_id=ev_id,
                    source=ev_data.get("source", "模型知识"),
                    retrieved_at=datetime.now().isoformat(),
                    claim=ev_data.get("claim", ""),
                )
                ev_ids.append(ev_id)

            loc = None
            if seg_data.get("location"):
                loc = Location(**seg_data["location"])

            cost = None
            if seg_data.get("estimated_cost"):
                cost_data = seg_data["estimated_cost"]
                cost = Cost(
                    amount=float(cost_data["amount"]),
                    currency=cost_data.get("currency", "CNY"),
                )

            seg = Segment(
                segment_id=seg_id,
                type=SegmentType(seg_data.get("type", "activity")),
                title=seg_data.get("title", ""),
                start_time=seg_data.get("start_time"),
                end_time=seg_data.get("end_time"),
                location=loc,
                estimated_cost=cost,
                tags=seg_data.get("tags", []),
                evidence_ids=ev_ids,
                module=module_name,
                note=seg_data.get("note", ""),
            )
            segments.append(seg)

        return segments, evidence_dict

    def _parse_day_segments(self, result: LLMResult, trip_id: str, day_number: int) -> dict:
        """
        解析按天 LLM 输出的 modules 结构。
        输出: {"modules": {"morning": [Segment,...], "afternoon": [...], "evening": [...]}, "evidence": {...}, "day_theme": "..."}
        """
        modules_result = {"morning": [], "afternoon": [], "evening": []}
        all_evidence = {}

        if not result.data:
            return {"modules": modules_result, "evidence": all_evidence, "day_theme": ""}

        modules_data = result.data.get("modules")
        if not modules_data:
            logger.warning("按天输出缺少 modules 字段，尝试回退解析")
            segs_data = result.data.get("segments", [])
            if not segs_data and isinstance(result.data.get("days"), list):
                for day_data in result.data["days"]:
                    if day_data.get("day_number") == day_number:
                        segs_data = day_data.get("segments", [])
                        break
            if segs_data:
                fake = _FakeResult({"segments": segs_data})
                segs, ev = self._parse_module_segments(fake, trip_id, day_number, "morning")
                modules_result["morning"] = segs
                all_evidence.update(ev)
            day_theme = result.data.get("day_theme", "")
            if not day_theme and isinstance(result.data.get("days"), list):
                for day_data in result.data["days"]:
                    if day_data.get("day_number") == day_number:
                        day_theme = day_data.get("theme", "")
                        break
            return {"modules": modules_result, "evidence": all_evidence, "day_theme": day_theme}

        for mod_name in ("morning", "afternoon", "evening"):
            mod_data = modules_data.get(mod_name, {})
            if isinstance(mod_data, list):
                mod_segs = mod_data
            elif isinstance(mod_data, dict):
                mod_segs = mod_data.get("segments", [])
            else:
                mod_segs = []

            if mod_segs:
                fake = _FakeResult({"segments": mod_segs})
                segs, ev = self._parse_module_segments(fake, trip_id, day_number, mod_name)
                modules_result[mod_name] = segs
                all_evidence.update(ev)

        return {"modules": modules_result, "evidence": all_evidence, "day_theme": result.data.get("day_theme", "")}


class _FakeResult:
    """轻量包装，兼容 _parse_module_segments 的 LLMResult 接口。"""
    def __init__(self, data: dict):
        self.data = data
        self.text = ""
