"""
models/assumption.py — Assumption 操作辅助函数
"""

from travel_planning_agent.types import Assumption, AssumptionLevel, AssumptionStatus


def create_assumption(
    level: AssumptionLevel,
    content: str,
    impact: str = "high",
    affected_rules: list[str] = None,
) -> Assumption:
    """创建新的假设。"""
    import uuid
    return Assumption(
        assumption_id=f"asm_{uuid.uuid4().hex[:8]}",
        level=level,
        content=content,
        status=AssumptionStatus.PENDING,
        impact=impact,
        affected_rules=affected_rules or [],
    )


def get_pending_explicit(assumptions: list[Assumption], max_count: int = 3) -> list[Assumption]:
    """获取待确认的显式假设（最多 max_count 条）。"""
    pending = [
        a for a in assumptions
        if a.level == AssumptionLevel.EXPLICIT
        and a.status == AssumptionStatus.PENDING
    ]
    return pending[:max_count]


def confirm_assumption(assumptions: list[Assumption], assumption_id: str) -> bool:
    """确认一条假设。"""
    for a in assumptions:
        if a.assumption_id == assumption_id:
            a.status = AssumptionStatus.CONFIRMED
            return True
    return False


def get_default_assumptions(constraints) -> list[Assumption]:
    """根据约束生成默认假设列表。"""
    assumptions = []

    # 隐式假设
    assumptions.append(create_assumption(
        AssumptionLevel.IMPLICIT,
        "默认午餐时间 12:00-13:00",
        impact="low",
    ))
    assumptions.append(create_assumption(
        AssumptionLevel.IMPLICIT,
        "默认景点游玩时长 2 小时",
        impact="medium",
    ))

    # 显式假设（基于约束条件）
    has_elderly = any(t.age_group == "elderly" for t in constraints.travelers)
    if has_elderly:
        assumptions.append(create_assumption(
            AssumptionLevel.EXPLICIT,
            "老人每日步行不超过 6000 步",
            impact="high",
            affected_rules=["R05", "R07"],
        ))

    if constraints.pace == "slow":
        assumptions.append(create_assumption(
            AssumptionLevel.EXPLICIT,
            "每日主活动不超过 2 个",
            impact="high",
            affected_rules=["R07"],
        ))

    return assumptions
