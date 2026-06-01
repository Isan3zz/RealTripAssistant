"""
agent/context.py — 上下文组装器

根据 Agent 声明的 context_required 自动拼装 L0-L6 上下文。
各层 loader 按需添加，无 consumer 的层不留空壳。
"""

from travel_planning_agent.types import PlanState, PlanningContext, SegmentType


class ContextAssembler:
    """
    按 Agent 声明的层级自动组装上下文。

    用法（Supervisor.dispatch_with_degrade 中）：
        request.context = ContextAssembler.assemble(state, agent)

    新增 loader 示例：
        @staticmethod
        def _load_l2(state: PlanState) -> dict:
            return {"constraints": {...}}
    """

    @classmethod
    def assemble(cls, state: PlanState, agent) -> dict:
        ctx = {}
        for level in getattr(agent.context_required, "levels", [0]):
            method = getattr(cls, f"_load_l{level}", None)
            if method:
                data = method(state)
                if data:
                    ctx[f"l{level}"] = data
        return ctx

    @classmethod
    def assemble_layered(cls, state: PlanState, agent) -> PlanningContext:
        return PlanningContext(layers=cls.assemble(state, agent))

    @staticmethod
    def _load_l0(state: PlanState) -> dict:
        return {
            "system_rules": [
                "规划优先，不执行预订、支付、退改签",
                "硬约束优先于软偏好",
                "关键推荐需要证据或标明降级来源",
                "用户锁定项不得擅自修改",
                "数值和时间约束由规则引擎校验",
            ],
        }

    @staticmethod
    def _load_l1(state: PlanState) -> dict:
        c = state.constraints
        if not c:
            return {}
        return {
            "user_preferences": {
                "pace": c.pace,
                "interests": list(getattr(c, "interests", [])),
                "transport_mode": c.transport_mode,
            },
        }

    @staticmethod
    def _load_l2(state: PlanState) -> dict:
        c = state.constraints
        if not c:
            return {}
        return {
            "constraints": {
                "origin": c.origin,
                "destination": c.destination,
                "start_date": c.start_date.isoformat(),
                "days": c.days,
                "travelers": [{"age_group": t.age_group, "note": t.note} for t in c.travelers],
                "budget": c.budget,
                "pace": c.pace,
                "transport_mode": c.transport_mode,
                "preferences_detail": c.preferences_detail,
            },
        }

    @staticmethod
    def _load_l3(state: PlanState) -> dict:
        return {
            "dynamic_state": {
                "trip_id": state.trip_id,
                "status": state.status.value,
                "phase": state.phase.value,
                "current_module": state.current_module,
                "planning_queue": state.planning_queue,
                "tasks": [
                    {"task_id": t.task_id, "desc": t.desc, "status": t.status.value}
                    for t in state.tasks
                ],
                "pending_questions": state.pending_questions,
            },
        }

    @staticmethod
    def _load_l4(state: PlanState) -> dict:
        return {"message_history": state.message_history[-10:]}

    @staticmethod
    def _load_l5(state: PlanState) -> dict:
        return {
            "evidence": [
                {
                    "evidence_id": ev.evidence_id,
                    "source": ev.source,
                    "source_type": ev.source_type,
                    "confidence": ev.confidence,
                    "claim": ev.claim,
                    "retrieved_at": ev.retrieved_at,
                }
                for ev in state.evidence.values()
            ]
        }

    @staticmethod
    def _load_l6(state: PlanState) -> dict:
        segments_by_day = []
        for day in state.days:
            segments_by_day.append({
                "day_number": day.day_number,
                "theme": day.theme,
                "segments": [
                    {
                        "segment_id": s.segment_id,
                        "type": s.type.value if isinstance(s.type, SegmentType) else str(s.type),
                        "title": s.title,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "module": s.module,
                    }
                    for s in day.segments
                ],
            })
        return {"agent_workspace": {"days": segments_by_day, "module_context": state.module_context}}
