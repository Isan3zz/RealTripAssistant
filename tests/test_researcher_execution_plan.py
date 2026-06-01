from datetime import date

from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import AgentRequest, Constraints, ToolResult, Traveler


def test_parallel_research_uses_execution_plan_executor(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        seen["plan"] = plan
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [{
                "evidence_id": "ev_ticket",
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        }

    monkeypatch.setattr("travel_planning_agent.agent.researcher.execute_execution_plan", fake_execute)

    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    response = agent.handle(AgentRequest(
        request_id="req_daily_exec",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
        },
    ))

    assert response.status == "success"
    assert seen["plan"].scope == "daily_research"
    assert response.data["evidence"][0]["claim"] == "玄武湖免费"
    assert response.data["execution_plan"]["plan_id"].startswith("exec_research_")


def test_parallel_research_reuses_shared_tool_call_registry(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        seen["reuse_context"] = reuse_context
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [],
            "tool_calls": reuse_context,
        }

    monkeypatch.setattr("travel_planning_agent.agent.researcher.execute_execution_plan", fake_execute)

    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    registry = {
        "sha256:weather": {
            "fingerprint": "sha256:weather",
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18", "days": 2},
            "status": "success",
            "evidence_ids": ["ev_weather"],
            "task_id": "global_weather",
            "updated_at": "2026-05-18T00:00:00",
        }
    }
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    response = agent.handle(AgentRequest(
        request_id="req_reuse_registry",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))

    assert response.status in ("degraded", "success")
    assert seen["reuse_context"] is registry


def test_parallel_research_skips_duplicate_tool_call_from_shared_registry(monkeypatch):
    calls = []
    legacy_calls = []

    def fake_execute(plan, reuse_context=None):
        from travel_planning_agent.core.execution_executor import execute_execution_plan

        return execute_execution_plan(plan, reuse_context=reuse_context)

    def fake_registered_tool(name, args):
        calls.append((name, args))
        return ToolResult(
            status="success",
            data="玄武湖免费",
            evidence=[{
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_registered_tool)
    monkeypatch.setattr("travel_planning_agent.agent.researcher.execute_execution_plan", fake_execute)
    monkeypatch.setattr(
        "travel_planning_agent.agent.researcher.execute_tool",
        lambda name, args: legacy_calls.append((name, args)) or "legacy should not be called",
    )

    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    registry = {}
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    first = agent.handle(AgentRequest(
        request_id="req_first",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))
    second = agent.handle(AgentRequest(
        request_id="req_second",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))

    assert first.status == "success"
    assert second.status == "success"
    assert len(calls) == 1
    assert legacy_calls == []
