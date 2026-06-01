"""
test_agent_protocol.py — Agent 通信协议测试
"""

from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    Pin, Assumption, AssumptionLevel, AssumptionStatus,
    ChangeItem, PlanDiff, VerificationReport, RuleResult,
    SemanticCheckResult, RiskCheck,
)


def test_agent_request():
    req = AgentRequest(
        request_id="req_001", agent="researcher",
        context={"destination": "HZ"}, params={"category": "poi"},
        context_summary="test summary",
    )
    assert req.request_id == "req_001"
    assert req.agent == "researcher"
    assert req.timeout_ms == 30000


def test_agent_response():
    resp = AgentResponse(
        request_id="req_001", status="success",
        data={"evidence": []}, tokens_used=100,
        source_note="api_result",
    )
    assert resp.status == "success"
    assert resp.tokens_used == 100


def test_pin_creation():
    pin = Pin(
        pin_id="pin_001", target_type="segment", target_id="seg_001",
        scope="entire_trip", mutable=False,
    )
    assert pin.pin_id == "pin_001"
    assert pin.mutable is False


def test_assumption():
    asm = Assumption(
        assumption_id="asm_001", level=AssumptionLevel.EXPLICIT,
        content="test", status=AssumptionStatus.PENDING,
    )
    assert asm.level == AssumptionLevel.EXPLICIT
    assert asm.status == AssumptionStatus.PENDING
    assert asm.impact == "high"


def test_change_item():
    ci = ChangeItem(
        segment_id="seg_001", change_type="modified",
        field_changes={"title": {"old": "A", "new": "B"}},
        reason="changed", impact={"budget": -100},
    )
    assert ci.change_type == "modified"
    assert ci.impact["budget"] == -100


def test_verification_report():
    report = VerificationReport(
        verification_id="v1", overall_pass=True,
        rule_checks=[
            RuleResult(rule_id="R01", name="时间", result="PASS"),
        ],
        semantic_checks=[
            SemanticCheckResult(check_id="S01", result="PASS", detail="OK"),
        ],
        risk_checks=[
            RiskCheck(risk_id="risk_1", risk_type="weather", severity="low", probability="low", detail="OK"),
        ],
    )
    assert report.overall_pass is True
    assert len(report.rule_checks) == 1
    assert len(report.semantic_checks) == 1
    assert len(report.risk_checks) == 1
