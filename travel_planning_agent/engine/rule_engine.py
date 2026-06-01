"""
rule_engine.py — 规则引擎编排（Phase 2, 9 条确定性规则）

规则注册表模式。新增规则只需在 RULES_REGISTRY 中添加条目。
"""

import logging
from typing import Optional
from travel_planning_agent.types import PlanState, RuleResult, VerificationReport

logger = logging.getLogger(__name__)
from travel_planning_agent.engine.rules import (
    check_time_non_overlap,
    check_budget_not_exceeded,
    check_date_in_bounds,
    check_required_fields_complete,
    check_spatial_continuity,
    check_opening_hours,
    check_density,
    check_pin_integrity,
    check_poi_real,
)

# 规则注册表（Phase 1: R01-R04, Phase 2: R05-R08）
# R09 POI 真实性需要外部地图服务，作为产品级风险检查按需调用，避免默认规则引擎产生网络副作用。
RULES_REGISTRY: list[tuple[str, str, callable]] = [
    ("R01", "时间连续性", check_time_non_overlap),
    ("R02", "预算", check_budget_not_exceeded),
    ("R03", "日期边界", check_date_in_bounds),
    ("R04", "必填完整性", check_required_fields_complete),
    ("R05", "空间连续性", check_spatial_continuity),
    ("R06", "开放时间", check_opening_hours),
    ("R07", "行程密度", check_density),
    ("R08", "用户锁定项", check_pin_integrity),
]


def run_rule_engine(state: PlanState, module_filter: Optional[tuple[int, str]] = None) -> VerificationReport:
    """
    执行所有注册规则，返回 VerificationReport。

    参数：
      state: 规划状态
      module_filter: 可选 (day_number, module_name) 只检查指定模块的段

    逻辑：
      遍历 RULES_REGISTRY 执行每条规则
      聚合结果到 VerificationReport
      overall_pass = all PASS
    """
    # 如果指定了 module_filter，过滤 state 只保留该天（或该天+模块）的段
    if module_filter:
        from copy import deepcopy
        day_num, mod_name = module_filter
        state = deepcopy(state)
        filtered_days = []
        for d in state.days:
            if d.day_number == day_num:
                if mod_name is not None:
                    d.segments = [s for s in d.segments if s.module == mod_name]
                filtered_days.append(d)
            # 其他天清空段（规则只检查指定天）
            else:
                d.segments = []
        state.days = filtered_days

    results: list[RuleResult] = []
    for rule_id, name, check_fn in RULES_REGISTRY:
        result = check_fn(state)
        results.append(result)

    overall_pass = all(r.result != "FAIL" for r in results)
    has_warn = any(r.result == "WARN" for r in results)
    if has_warn:
        logger.warning("规则校验有 WARN: %s", [r.rule_id for r in results if r.result == "WARN"])

    import uuid
    return VerificationReport(
        verification_id=f"verify_{uuid.uuid4().hex[:8]}",
        overall_pass=overall_pass,
        rule_checks=results,
        semantic_checks=[],
        risk_checks=[],
        correction_requests=_build_corrections(results),
    )


def _build_corrections(rule_results: list[RuleResult]) -> list[dict]:
    """将 FAIL 规则转化为可执行的修正请求。"""
    corrections = []
    for r in rule_results:
        if r.result != "FAIL":
            continue
        corrections.append({
            "rule_id": r.rule_id,
            "target_segments": r.affected_segments,
            "detail": r.detail,
        })
    return corrections
