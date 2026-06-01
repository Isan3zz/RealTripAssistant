"""
agent/verifier.py — Verifier 封装层

确定性规则引擎 + 语义 LLM 判断 + 风险检查。

重要设计决策（架构总纲）：
  - 规则引擎（代码实现）是主体，不消耗 token
  - 语义检查仅在确定性规则全部通过后触发
  - Risk Check 也合并在此 Agent
"""

import logging
from typing import Any

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    PlanState, VerificationReport, SemanticCheckResult, RiskCheck,
)
from travel_planning_agent.engine import run_rule_engine
from travel_planning_agent.semantic.semantic_checker import run_all_semantic_checks
from copy import deepcopy

logger = logging.getLogger(__name__)


class VerifierAgent(BaseAgent):
    """
    Verifier：确定性规则引擎 + 语义 LLM 判断。

    数据流：
      输入 PlanState
        → 规则引擎（8 条确定性规则）
          → 全部 PASS → 语义检查（3 条）
            → Risk Check
          → 有 FAIL → correction_requests
    """

    agent_name = "verifier"
    context_required = ContextRequirement(levels=[0, 2, 3, 5])

    def handle(self, request: AgentRequest) -> AgentResponse:
        params = request.params
        check_type = params.get("check_type", "all")  # "deterministic" / "semantic" / "risk" / "all"
        state: PlanState = params.get("state")

        if not state:
            return AgentResponse(
                request_id=request.request_id, status="failed", data={},
                error="缺少 state 参数",
            )

        try:
            # Step 1: 确定性规则
            rule_results = []
            semantic_results = []
            risk_results = []

            if check_type in ("deterministic", "all"):
                report = run_rule_engine(state)
                rule_results = report.rule_checks
                has_fail = any(r.result == "FAIL" for r in rule_results)

                if not has_fail and check_type == "all":
                    # Step 2: 语义检查（仅全部 PASS 时）
                    semantic_results = run_all_semantic_checks(self.llm_client.generate, state)

                    # Step 3: 风险检查
                    risk_results = self._run_risk_checks(state)

                # 构建修正请求
                corrections = self._build_corrections(rule_results, semantic_results)

                # 构建完整的 VerificationReport
                import uuid
                report = VerificationReport(
                    verification_id=f"verify_{uuid.uuid4().hex[:8]}",
                    overall_pass=not has_fail and all(s.result != "FAIL" for s in semantic_results),
                    rule_checks=rule_results,
                    semantic_checks=semantic_results,
                    risk_checks=risk_results,
                    correction_requests=corrections,
                )

                return AgentResponse(
                    request_id=request.request_id,
                    status="success",
                    data={"verification_report": report},
                )

            elif check_type == "semantic":
                semantic_results = run_all_semantic_checks(self.llm_client.generate, state)
                return AgentResponse(
                    request_id=request.request_id,
                    status="success",
                    data={"semantic_checks": semantic_results},
                )

            elif check_type == "risk":
                risk_results = self._run_risk_checks(state)
                return AgentResponse(
                    request_id=request.request_id,
                    status="success",
                    data={"risk_checks": risk_results},
                )

            elif check_type == "module_deterministic":
                module_day = params.get("module_day")
                module_name = params.get("module_name")
                report = run_rule_engine(state, module_filter=(module_day, module_name))
                return AgentResponse(
                    request_id=request.request_id,
                    status="success",
                    data={"verification_report": report},
                )

            else:
                return AgentResponse(
                    request_id=request.request_id, status="failed", data={},
                    error=f"未知 check_type: {check_type}",
                )

        except Exception as e:
            logger.error("Verifier 失败: %s", str(e))
            return AgentResponse(
                request_id=request.request_id, status="failed", data={},
                error=str(e),
            )

    def _run_risk_checks(self, state: PlanState) -> list[RiskCheck]:
        """运行风险检查。"""
        risks = []

        # 检查是否有 confidence="medium"/"low" 的证据
        for eid, ev in state.evidence.items():
            if ev.confidence in ("medium", "low"):
                risks.append(RiskCheck(
                    risk_id=f"risk_{eid}",
                    risk_type="timing",
                    severity="medium",
                    probability="medium",
                    detail=f"证据 {eid} 置信度为 {ev.confidence}，建议出行前确认",
                    mitigation="出行前验证相关信息",
                ))

        return risks

    def _build_corrections(self, rule_results, semantic_results) -> list[dict]:
        """将 FAIL 规则转化为可执行的修正请求。"""
        corrections = []
        for r in rule_results:
            if r.result != "FAIL":
                continue
            corrections.append({
                "rule_id": r.rule_id,
                "target_segments": r.affected_segments,
                "detail": r.detail,
                "required_change": "adjust_schedule_or_replace",
            })
        for s in semantic_results:
            if s.result != "FAIL":
                continue
            corrections.append({
                "rule_id": s.check_id,
                "target_segments": [],
                "detail": s.detail,
                "required_change": "replan_with_feedback",
            })
        return corrections
