"""
agent/supervisor.py — Supervisor Agent (Phase 3.5 流水线并行)

管理流水线规划循环：按天 Draft → 并行 Research + 下一天 Draft → 模块 Refine/Verify/Lock。
"""

import json
import logging
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Optional

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    PlanState, PlanPhase, TripStatus, Constraints,
    AgentRequest, AgentResponse, ContextRequirement,
    Assumption, AssumptionStatus,
    Evidence,
    RuleResult, VerificationReport,
)
from travel_planning_agent.engine import run_rule_engine
from travel_planning_agent.storage import init_trip_dir, save_state, save_trip_md, save_evidence
from travel_planning_agent.models.assumption import get_default_assumptions

logger = logging.getLogger(__name__)


def _sort_evidence(ev_dict: dict[str, Evidence]) -> list[Evidence]:
    """按置信度排序证据（high→medium→low），同置信度保持插入顺序。"""
    priority = {"high": 0, "medium": 1, "low": 2}
    ev_list = list(ev_dict.values())
    ev_list.sort(key=lambda e: priority.get(e.confidence, 99))
    return ev_list


class SupervisorAgent(BaseAgent):
    """
    Supervisor — 调度中枢。

    管理整个规划流程的状态机流转、Agent 调度、异常降级。
    """

    agent_name = "supervisor"
    context_required = ContextRequirement(levels=[0, 1, 2, 3, 4])

    def __init__(self, llm_client, agents: dict):
        super().__init__(llm_client)
        self.agents = agents

    def handle(self, request: AgentRequest) -> AgentResponse:
        """启动模块化规划循环。"""
        constraints = request.params.get("constraints")
        if not constraints:
            return AgentResponse(
                request_id=request.request_id, status="failed", data={},
                error="缺少 constraints 参数",
            )
        state = self.run_planning_loop(constraints)
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={"trip_id": state.trip_id, "status": state.status.value},
        )

    # ═══════════════════════════════════════════════════
    #  降级策略
    # ═══════════════════════════════════════════════════
    #  降级策略
    # ═══════════════════════════════════════════════════

    def dispatch_with_degrade(self, agent_name: str, request: AgentRequest) -> AgentResponse:
        """
        分发请求到指定 Agent，含降级策略。

        L1: 重试 1 次（间隔 2s）
        L2: 降级（Researcher 用 LLM 知识兜底）
        L3: 请求用户
        L4: 标记失败
        """
        agent = self.agents.get(agent_name)
        if not agent:
            return AgentResponse(
                request_id=request.request_id, status="failed", data={},
                error=f"未知 Agent: {agent_name}",
            )

        # 自动组装上下文
        from travel_planning_agent.agent.context import ContextAssembler
        current_state = getattr(self, "_state", None)
        if current_state:
            request.context = ContextAssembler.assemble(current_state, agent)

        # L1: 首次调用
        try:
            response = agent.handle(request)
            if response.status in ("success", "degraded"):
                return response
        except Exception as e:
            logger.warning("%s 首次调用失败: %s", agent_name, str(e))

        # L1 Retry: 延迟重试 1 次
        try:
            logger.info("%s L1 重试...", agent_name)
            time.sleep(2)
            response = agent.handle(request)
            if response.status == "success":
                return response
        except Exception as e:
            logger.warning("%s 重试失败: %s", agent_name, str(e))

        # L2 降级: 对 Researcher 用 LLM 知识兜底
        if agent_name == "researcher":
            logger.info("%s L2 降级: 使用 LLM 知识兜底", agent_name)
            return AgentResponse(
                request_id=request.request_id,
                status="degraded",
                data={"evidence": [], "source_note": "model_knowledge"},
                source_note="model_knowledge",
            )

        # L4 失败
        return AgentResponse(
            request_id=request.request_id, status="failed", data={},
            error=f"{agent_name} 多次调用失败",
        )

    # ═══════════════════════════════════════════════════
    #  主入⼝
    # ═══════════════════════════════════════════════════

    def run_planning_loop(
        self,
        constraints: Constraints,
        initial_evidence: list[dict] | None = None,
        execution_plan=None,
        tool_call_registry: dict | None = None,
    ) -> PlanState:
        """启动模块化规划循环。"""
        trip_id = f"trip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        init_trip_dir(trip_id)

        state = PlanState(
            trip_id=trip_id,
            status=TripStatus.PLANNING,
            constraints=constraints,
        )
        state.assumptions = get_default_assumptions(constraints)
        for ev_data in initial_evidence or []:
            if isinstance(ev_data, dict) and ev_data.get("evidence_id"):
                state.evidence[ev_data["evidence_id"]] = Evidence(**ev_data)
        if execution_plan is not None:
            state.module_context["execution_plan"] = execution_plan.to_dict()
        if tool_call_registry is not None:
            state.module_context["_tool_calls"] = tool_call_registry

        self._run_pipeline_loop(state)
        return state

    # ═══════════════════════════════════════════════════════
    #  流水线按天规划循环（Phase 3.5 并行）
    # ═══════════════════════════════════════════════════════

    def _run_pipeline_loop(self, state: PlanState):
        return self._run_pipeline_loop_impl(state)

    def _run_pipeline_loop_impl(self, state: PlanState):
        """
        流水线按天规划：
        Day1 Draft → 并行[Day1 Research + Day2 Draft] → 并行[Day1 RefineVerify + Day2 Research + Day3 Draft] → ...
        每步产出实时写回 state，主线程串行 lock，worker 线程为纯函数。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self._state = state
        constraints = state.constraints
        days = constraints.days

        # 预取共享数据
        self._prefetch_shared_data(state)

        # Research 去重追踪
        pending_rk: set = set()
        completed_rk: set = set()

        # 按天 Draft 结果缓存
        draft_results: dict = {}
        # 住宿信息映射：day → accommodation dict
        accommodation_map: dict = {}

        # 天级模块锁定计数：day → set of locked module names
        day_locked_modules: dict = {d: set() for d in range(1, days + 1)}

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures: dict = {}

            # 提交 Day1 Draft
            snapshot = self._state_snapshot(state)
            fut = ex.submit(self._pipeline_draft_day,
                constraints, snapshot["locked_segments_text"],
                snapshot["budget"], snapshot["trip_id"], 1, None)
            futures[fut] = ("draft", 1)

            while futures:
                # 每次处理最先完成的一个 future
                done_futures = []
                for fut in list(futures.keys()):
                    if fut.done():
                        done_futures.append(fut)
                        if len(done_futures) >= 3:  # 一次最多处理3个
                            break
                if not done_futures:
                    # 没有已完成的，等下一个
                    import time as _time
                    _time.sleep(0.1)
                    continue

                for fut in done_futures:
                    task_type, *args = futures.pop(fut)
                    try:
                        result = fut.result()
                    except Exception as e:
                        logger.error("流水线任务 (%s, %s) 失败: %s", task_type, args, e)
                        continue

                    if task_type == "draft":
                        day = args[0]
                        draft_results[day] = result
                        acc = self._extract_accommodation(result)
                        accommodation_map[day] = acc
                        logger.info("📝 Day %d Draft 完成 (theme: %s)", day, result.get("day_theme", "?"))

                        # 提交 Research（去重）
                        rn = result.get("research_needs", [])
                        if rn:
                            deduped = self._dedup_research_needs(rn, pending_rk, completed_rk)
                            if deduped:
                                for item in deduped:
                                    pending_rk.add(_research_key(item))
                                fut_r = ex.submit(self._pipeline_research_day,
                                    constraints, deduped, state.trip_id, result,
                                    state.module_context.get("_tool_calls", {}))
                                futures[fut_r] = ("research", day)
                                logger.info("🔍 Day %d Research 已提交 (%d 项)", day, len(deduped))

                        # 提交下一天 Draft（带前一天行程上下文，避免重复）
                        if day < days:
                            prev_ctx = self._format_previous_days_context(draft_results, upto_day=day)
                            snapshot2 = self._state_snapshot(state)
                            fut_d = ex.submit(self._pipeline_draft_day,
                                constraints, snapshot2["locked_segments_text"],
                                snapshot2["budget"], state.trip_id, day + 1, acc, prev_ctx)
                            futures[fut_d] = ("draft", day + 1)

                        # 如果本天没有 research_needs，直接进入模块 refine+verify
                        if not rn:
                            dr = draft_results.get(day)
                            if dr:
                                self._submit_module_tasks(
                                    ex, futures, state, dr, day, day_locked_modules)

                    elif task_type == "research":
                        day = args[0]
                        ev_list = result.get("evidence", []) if isinstance(result, dict) else []
                        research_keys = result.get("_keys", []) if isinstance(result, dict) else []
                        for ev_data in ev_list:
                            if isinstance(ev_data, dict) and "evidence_id" in ev_data:
                                state.evidence[ev_data["evidence_id"]] = Evidence(**ev_data)
                        for k in research_keys:
                            pending_rk.discard(k)
                            completed_rk.add(k)
                        save_state(state)
                        logger.info("📊 Day %d Research 完成 (%d 条证据)", day, len(ev_list))

                        # 提交模块 refine+verify
                        dr = draft_results.get(day)
                        if dr:
                            self._submit_module_tasks(
                                ex, futures, state, dr, day, day_locked_modules)

                    elif task_type == "module":
                        day, mod_name = args[0], args[1]
                        final_segs, passed = result
                        if not final_segs:
                            logger.warning("⚠ Day %d %s 产出为空，跳过锁定", day, mod_name)
                            continue

                        self._strip_revision_tags(final_segs)
                        day_theme = draft_results.get(day, {}).get("day_theme", "")
                        self._lock_module(state, day, mod_name, final_segs, day_theme=day_theme)
                        day_locked_modules[day].add(mod_name)
                        state.days.sort(key=lambda d: d.day_number)
                        save_state(state)
                        if passed:
                            logger.info("🔒 Day %d %s 已锁定", day, mod_name)
                        else:
                            logger.warning("⚠ Day %d %s 校验未通过（重试耗尽），已保留最后一版避免行程缺失", day, mod_name)

        # Polish
        self._run_polish(state)

        # Finalize
        state.phase = PlanPhase.FINALIZING
        state.status = TripStatus.COMPLETED
        state.days.sort(key=lambda d: d.day_number)
        state.validation = run_rule_engine(state)
        save_trip_md(state)
        save_evidence(state)
        state.phase = PlanPhase.DONE
        save_state(state)
        logger.info("流水线按天规划完成")

    def _submit_module_tasks(self, ex, futures, state, draft_result, day, day_locked_modules):
        """为一天的所有未锁定模块提交 refine+verify 任务。"""
        modules_data = draft_result.get("modules", {})
        snapshot = self._state_snapshot(state)
        for mod_name in ("morning", "afternoon", "evening"):
            if mod_name in day_locked_modules.get(day, set()):
                continue
            mod_segs = modules_data.get(mod_name, [])
            if not mod_segs:
                continue
            fut = ex.submit(self._pipeline_refine_verify_module,
                snapshot, day, mod_name, mod_segs)
            futures[fut] = ("module", day, mod_name)

    # ── 流水线 Worker 方法（纯函数，不修改 state）──

    def _pipeline_draft_day(self, constraints, locked_text, budget_snapshot,
                             trip_id, day_number, prev_accommodation, prev_day_context=""):
        """Worker: 按天 Draft。纯函数，返回 draft dict。"""
        total_budget = constraints.budget
        spent = budget_snapshot.get("spent", 0.0)
        available = total_budget - spent
        remaining = constraints.days - day_number + 1

        planner = self.agents.get("planner")
        req = AgentRequest(
            request_id=f"pd_{uuid.uuid4().hex[:8]}",
            agent="planner", context={}, context_summary="",
            params={
                "mode": "day_draft",
                "day_number": day_number,
                "constraints": constraints,
                "previous_day_accommodation": prev_accommodation,
                "prev_day_plan_text": prev_day_context,
                "locked_segments_text": locked_text,
                "total_budget": total_budget,
                "spent_budget": spent,
                "available_budget": available,
                "remaining_days": remaining,
                "trip_id": trip_id,
            },
        )
        resp = self.dispatch_with_degrade("planner", req)
        if resp.status != "success":
            logger.error("Day %d Draft 失败: %s", day_number, resp.error)
            return {"day_theme": "", "modules": {}, "research_needs": [], "evidence": {}}
        return resp.data

    def _pipeline_research_day(self, constraints, research_needs, trip_id, draft_result=None, tool_call_registry=None):
        """Worker: 按天 Research。纯函数，返回 evidence 列表。"""
        researcher = self.agents.get("researcher")
        req = AgentRequest(
            request_id=f"pr_{uuid.uuid4().hex[:8]}",
            agent="researcher", context={}, context_summary="",
            params={
                "constraints": constraints,
                "destination": constraints.destination,
                "research_needs": research_needs,
                "draft_result": draft_result or {},
                "tool_call_registry": tool_call_registry,
            },
        )
        resp = self.dispatch_with_degrade("researcher", req)
        evidence = resp.data.get("evidence", []) if resp.status in ("success", "degraded") else []
        return {"evidence": evidence, "_keys": [_research_key(r) for r in research_needs]}

    def _pipeline_refine_verify_module(self, snapshot, day_num, module_name, segments_data):
        """
        Worker: 单模块 Refine → Verify（含本地重试）。
        纯函数，不修改 state。返回 (final_segments, passed)。
        """
        from copy import deepcopy
        import uuid as _uuid

        planner = self.agents.get("planner")

        # --- Refine ---
        # 从 snapshot 中提取相关 evidence
        evidence_snapshot = snapshot.get("evidence", {})
        ev_list = _sort_evidence(evidence_snapshot)

        refine_req = AgentRequest(
            request_id=f"rf_{_uuid.uuid4().hex[:8]}",
            agent="planner", context={}, context_summary="",
            params={
                "mode": "module_refine",
                "day_number": day_num,
                "module_name": module_name,
                "segments": segments_data,
                "evidence": ev_list,
                "trip_id": snapshot.get("trip_id", "unknown"),
            },
        )
        refine_resp = self.dispatch_with_degrade("planner", refine_req)
        if refine_resp.status == "success":
            refined = refine_resp.data.get("segments", [])
            if refined:
                segments_data = refined

        # --- Verify（含本地重试） ---
        max_retries = 2
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info("模块 %s_%s 重试 %d/%d", day_num, module_name, attempt, max_retries)

            # 构建临时 state 用于 verify
            temp_state = PlanState(
                trip_id=snapshot.get("trip_id", "unknown"),
                constraints=snapshot.get("constraints"),
                evidence=deepcopy(evidence_snapshot),
            )
            from travel_planning_agent.types import ItineraryDay
            locked_segs = snapshot.get("locked_segments", {}).get(day_num, [])
            temp_day = ItineraryDay(
                day_id=f"{temp_state.trip_id}_day_{day_num}",
                day_number=day_num,
                segments=locked_segs + list(segments_data),
            )
            temp_state.days = [temp_day]

            report = _run_module_rule_check(temp_state)
            if report.overall_pass:
                return (segments_data, True)

            for cr in report.correction_requests:
                logger.warning("  规则 %s: %s", cr.get("rule_id", "?"), cr.get("detail", ""))

            if attempt < max_retries:
                correction_text = "\n".join(
                    f"  {cr.get('rule_id', '?')}: {cr.get('detail', '')}"
                    for cr in report.correction_requests
                )
                budget_summary = f"本模块预算: 剩余 {snapshot.get('budget',{}).get('available',0)} 元"

                revise_req = AgentRequest(
                    request_id=f"rv_{_uuid.uuid4().hex[:8]}",
                    agent="planner", context={}, context_summary="",
                    params={
                        "mode": "module_revise",
                        "day_number": day_num,
                        "module_name": module_name,
                        "segments": segments_data,
                        "validation_errors": correction_text,
                        "budget_summary": budget_summary,
                        "revision_count": attempt + 1,
                        "max_revisions": max_retries,
                        "trip_id": snapshot.get("trip_id", "unknown"),
                    },
                )
                revise_resp = self.dispatch_with_degrade("planner", revise_req)
                if revise_resp.status == "success":
                    new_segs = revise_resp.data.get("segments", [])
                    if new_segs:
                        segments_data = new_segs

        return (segments_data, False)

    # ── 流水线辅助方法 ──

    def _state_snapshot(self, state: PlanState) -> dict:
        """生成 state 的不可变快照，供 worker 线程安全读取。"""
        locked_segs_text = self._format_locked_segments(state)
        spent = self._calc_spent_budget(state)
        # 按天组装的锁定段（供 verify 用）
        locked_by_day = {}
        for d in state.days:
            locked_by_day[d.day_number] = [s for s in d.segments if s.module]
        return {
            "locked_segments_text": locked_segs_text,
            "locked_segments": locked_by_day,
            "budget": {"spent": spent, "available": state.constraints.budget - spent if state.constraints else 0},
            "evidence": dict(state.evidence),
            "trip_id": state.trip_id,
            "constraints": state.constraints,
        }

    def _extract_accommodation(self, draft_result: dict) -> Optional[dict]:
        """从按天 Draft 结果中提取住宿信息（evening 最后一个 accommodation）。"""
        modules = draft_result.get("modules", {})
        evening = modules.get("evening", [])
        if isinstance(evening, dict):
            evening = evening.get("segments", [])
        # 找最后一个 accommodation
        for seg in reversed(evening):
            if hasattr(seg, 'type') and seg.type and seg.type.value == "accommodation":
                return {
                    "end_time": seg.end_time or "18:00",
                    "end_location": {"name": seg.location.name if seg.location else "", "city": seg.location.city if seg.location else ""},
                    "hotel_name": seg.title,
                    "hotel_city": seg.location.city if seg.location else "",
                }
            elif isinstance(seg, dict) and seg.get("type") == "accommodation":
                loc = seg.get("location", {})
                return {
                    "end_time": seg.get("end_time", "18:00"),
                    "end_location": {"name": loc.get("name", ""), "city": loc.get("city", "")},
                    "hotel_name": seg.get("title", ""),
                    "hotel_city": loc.get("city", ""),
                }
        # 无 accommodation，返回 evening 最后一段
        last = evening[-1] if evening else None
        if last:
            if hasattr(last, 'location'):
                loc = last.location
                return {"end_time": last.end_time or "18:00", "end_location": {"name": loc.name if loc else "", "city": loc.city if loc else ""}, "hotel_name": last.title if hasattr(last, 'title') else "", "hotel_city": loc.city if loc else ""}
            elif isinstance(last, dict):
                loc = last.get("location", {})
                return {"end_time": last.get("end_time", "18:00"), "end_location": {"name": loc.get("name", ""), "city": loc.get("city", "")}, "hotel_name": last.get("title", ""), "hotel_city": loc.get("city", "")}
        return None

    def _format_previous_day_context(self, draft_result: dict) -> str:
        """将前一天 draft 结果格式化为可读文本，供下一天 prompt 避免重复。"""
        if not draft_result:
            return "（行程起始，无前一天行程）"
        modules = draft_result.get("modules", {})
        lines = [f"主题：{draft_result.get('day_theme', '未知')}"]
        for mod_name in ("morning", "afternoon", "evening"):
            mod_data = modules.get(mod_name, [])
            if isinstance(mod_data, dict):
                mod_data = mod_data.get("segments", [])
            if not mod_data:
                continue
            labels = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}
            lines.append(f"  {labels.get(mod_name, mod_name)}：")
            for seg in mod_data:
                if isinstance(seg, dict):
                    title = seg.get("title", "")
                    loc = seg.get("location", {})
                    loc_name = loc.get("name", "") if isinstance(loc, dict) else ""
                    lines.append(f"    - {title} @ {loc_name}")
                elif hasattr(seg, 'title'):
                    loc_name = seg.location.name if seg.location else ""
                    lines.append(f"    - {seg.title} @ {loc_name}")
        lines.append("  → 当天行程禁止与以上景点/餐厅/活动重复。")
        return "\n".join(lines)

    def _format_previous_days_context(self, draft_results: dict, upto_day: int) -> str:
        """汇总截至指定天数的全部草案摘要，供后续天数保持连续性并避免重复。"""
        if not draft_results or upto_day <= 0:
            return "\uff08\u884c\u7a0b\u8d77\u59cb\uff0c\u6682\u65e0\u524d\u5e8f\u8349\u6848\uff09"

        parts = []
        for day in range(1, upto_day + 1):
            draft_result = draft_results.get(day)
            if not draft_result:
                continue
            parts.append(f"Day {day}")
            parts.append(self._format_previous_day_context(draft_result))

        if not parts:
            return "\uff08\u884c\u7a0b\u8d77\u59cb\uff0c\u6682\u65e0\u524d\u5e8f\u8349\u6848\uff09"
        return "\n".join(parts)

    def _dedup_research_needs(self, research_needs: list, pending: set, completed: set) -> list:
        """过滤 research_needs，移除已在 pending 或 completed 中的重复项。"""
        result = []
        for item in research_needs:
            key = _research_key(item)
            if key and key not in pending and key not in completed:
                result.append(item)
        return result

    # ═══════════════════════════════════════════════════════
    #  全局预取共享数据
    # ═══════════════════════════════════════════════════════

    def _prefetch_shared_data(self, state: PlanState):
        """规划开始前只预取全局天气，其他信息由 ResearchPlan 按草案精准查询。"""
        from travel_planning_agent.core.planning_state_service import PlanningStateService
        from travel_planning_agent.core.tool_dedup import (
            find_tool_call,
            get_tool_call_registry,
            remember_tool_call,
        )
        from travel_planning_agent.tools import execute_tool

        c = state.constraints
        if not c:
            return
        destination = c.destination
        start_date = c.start_date.isoformat() if hasattr(c.start_date, "isoformat") else str(c.start_date)
        days = max(int(c.days or 1), 1)
        trip_id = state.trip_id

        logger.info("预取共享数据: 天气 for %s (%s 起 %d 天)", destination, start_date, days)
        weather_args = {"city": destination, "date": start_date, "days": days}
        tool_calls = get_tool_call_registry(state.module_context)
        reused = find_tool_call(tool_calls, "get_weather_forecast", weather_args)
        if reused:
            logger.info(
                "跳过天气预取，复用已有工具调用 %s evidence=%s",
                reused.get("fingerprint"),
                reused.get("evidence_ids"),
            )
            try:
                from travel_planning_agent.core.tracing import record_trace_event

                record_trace_event(
                    "prefetch_skipped_duplicate",
                    "supervisor",
                    {
                        "tool": "get_weather_forecast",
                        "args": weather_args,
                        "fingerprint": reused.get("fingerprint"),
                        "reused_evidence_ids": list(reused.get("evidence_ids") or []),
                    },
                )
            except Exception:
                pass
            return

        try:
            result_text = execute_tool("get_weather_forecast", weather_args)
        except Exception as e:
            logger.warning("天气预取失败 [%s]: %s", destination, e)
            return
        if not result_text or "查询失败" in result_text or "暂未查到" in result_text:
            logger.info("天气预取无有效结果: %s", destination)
            return

        ev_id = PlanningStateService().remember_prefetched_weather(state, result_text)
        if not ev_id:
            return
        remember_tool_call(
            tool_calls,
            "get_weather_forecast",
            weather_args,
            status="success",
            evidence_ids=[ev_id],
            task_id="supervisor_prefetch_weather",
        )
        logger.info("预取完成: 1/1 项成功 (weather, %d days)", days)

    def _format_locked_segments(self, state: PlanState) -> str:
        """格式化已锁定的段为文本。"""
        locked_parts = []
        for d in state.days:
            for s in d.segments:
                if s.module and s.segment_id:
                    locked_parts.append(
                        f"  Day{d.day_number} {s.module}: {s.title} "
                        f"({s.start_time}-{s.end_time}) ¥{s.estimated_cost.amount if s.estimated_cost else 0}"
                    )
        if not locked_parts:
            return "（无已锁定行程）"
        return "\n".join(locked_parts)

    def _calc_spent_budget(self, state: PlanState) -> float:
        """计算已锁定的段的总花费。"""
        total = 0.0
        for d in state.days:
            for s in d.segments:
                # 只算已锁定模块的段（即 module 非空）
                if s.module and s.estimated_cost:
                    total += s.estimated_cost.amount
        return total

    def _lock_module(self, state: PlanState, day_num: int, module_name: str, segments: list, day_theme: str = ""):
        from travel_planning_agent.core.planning_state_service import PlanningStateService

        PlanningStateService().lock_module(state, day_num, module_name, segments, day_theme=day_theme)
        module_key = f"{day_num}_{module_name}"
        end_time = state.module_context[module_key]["end_time"]
        logger.info("模块 %s 已锁定，结束时间: %s", module_key, end_time)

    # ═══════════════════════════════════════════════════
    #  辅助方法
    # ═══════════════════════════════════════════════════

    def run_revision(self, state: PlanState, modification: str, constraints: Constraints) -> PlanState:
        """根据用户的新要求重新规划。"""
        logger.info("修订请求: %s", modification)
        return self.run_planning_loop(constraints)

    def confirm_assumption(self, state: PlanState, assumption_id: str, confirmed: bool):
        """用户确认或拒绝假设。"""
        for a in state.assumptions:
            if a.assumption_id == assumption_id:
                a.status = AssumptionStatus.CONFIRMED if confirmed else AssumptionStatus.REJECTED
                break
        save_state(state)

    def pin_segment(self, state: PlanState, segment_id: str) -> bool:
        """用户锁定一个 segment。"""
        from travel_planning_agent.models.pin import create_pin
        for p in state.pins:
            if p.target_id == segment_id and not p.mutable:
                return False
        pin = create_pin(target_type="segment", target_id=segment_id)
        state.pins.append(pin)
        save_state(state)
        return True

    @staticmethod
    def _strip_revision_tags(segments: list):
        """清洗 LLM 修订时可能残留的"（已修正）"标记。"""
        for s in segments:
            if "（已修正）" in s.title:
                s.title = s.title.replace("（已修正）", "").strip()

    def _run_polish(self, state: PlanState):
        """规划完成后调用 Polish Agent 润色（天气建议等）。"""
        try:
            from travel_planning_agent.agent.polisher import PolishAgent
            polisher = PolishAgent(self.llm_client)
            req = AgentRequest(
                request_id=f"polish_{uuid.uuid4().hex[:8]}",
                agent="polisher",
                context={},
                params={"state": state},
            )
            polisher.handle(req)
        except Exception as e:
            logger.warning("Polish Agent 失败: %s", e)

    @staticmethod
    def _extract_attractions(days: list) -> list[str]:
        """从行程中提取景点名列表。"""
        from travel_planning_agent.types import SegmentType
        seen = set()
        names = []
        for day in days:
            for seg in day.segments:
                if seg.type == SegmentType.ACTIVITY and seg.title and seg.title not in seen:
                    seen.add(seg.title)
                    names.append(seg.title)
                    if len(names) >= 5:
                        return names
        return names


def _research_key(item: dict) -> str:
    """生成 research_need 的去重 key，格式: type::item。"""
    if not isinstance(item, dict):
        return str(item)
    return f"{item.get('type', 'unknown')}::{item.get('item', '').strip()}"


def _run_module_rule_check(state: PlanState) -> VerificationReport:
    """Fast local checks for a module; whole-plan rules run at finalization."""
    import uuid
    results: list[RuleResult] = []

    for day in state.days:
        timed = [s for s in day.segments if s.start_time and s.end_time]
        timed.sort(key=lambda s: s.start_time)
        for i in range(len(timed) - 1):
            cur, nxt = timed[i], timed[i + 1]
            if nxt.start_time < cur.end_time:
                results.append(RuleResult(
                    rule_id="M01",
                    name="模块时间不重叠",
                    result="FAIL",
                    detail=f"Day {day.day_number} {cur.title} 与 {nxt.title} 时间重叠",
                    affected_segments=[cur.segment_id, nxt.segment_id],
                ))
                break

        for seg in day.segments:
            if not seg.title.strip():
                results.append(RuleResult(
                    rule_id="M02",
                    name="模块字段完整",
                    result="FAIL",
                    detail=f"Day {day.day_number} 存在标题为空的 segment",
                    affected_segments=[seg.segment_id],
                ))
                break

    if not results:
        results.append(RuleResult(rule_id="M00", name="模块局部校验", result="PASS"))

    failures = [r for r in results if r.result == "FAIL"]
    return VerificationReport(
        verification_id=f"verify_{uuid.uuid4().hex[:8]}",
        overall_pass=not failures,
        rule_checks=results,
        semantic_checks=[],
        risk_checks=[],
        correction_requests=[
            {"rule_id": r.rule_id, "target_segments": r.affected_segments, "detail": r.detail}
            for r in failures
        ],
        module_checks=[
            {"rule_id": r.rule_id, "result": r.result, "detail": r.detail}
            for r in results
        ],
    )
