from datetime import date

from travel_planning_agent.storage.file_store import load_state, save_state
from travel_planning_agent.types import Constraints, PlanState, Traveler


def test_tool_call_registry_survives_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_planning_agent.config.settings.data_dir", str(tmp_path))

    state = PlanState(
        trip_id="trip_resume_dedup",
        constraints=Constraints(
            destination="南京",
            origin="杭州",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
        ),
    )
    state.module_context["_tool_calls"] = {
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

    save_state(state)
    loaded = load_state("trip_resume_dedup")

    assert loaded is not None
    assert loaded.module_context["_tool_calls"]["sha256:weather"]["evidence_ids"] == ["ev_weather"]


def test_restored_state_skips_weather_prefetch(tmp_path, monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.core.tool_dedup import get_tool_call_registry, remember_tool_call

    monkeypatch.setattr("travel_planning_agent.config.settings.data_dir", str(tmp_path))
    calls = []

    def fake_execute_tool(tool_name, args):
        calls.append((tool_name, args))
        return "should not be called"

    monkeypatch.setattr("travel_planning_agent.tools.execute_tool", fake_execute_tool)

    state = PlanState(
        trip_id="trip_restore_prefetch",
        constraints=Constraints(
            destination="南京",
            origin="杭州",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
        ),
    )
    registry = get_tool_call_registry(state.module_context)
    remember_tool_call(
        registry,
        "get_weather_forecast",
        {"city": "南京", "date": "2026-05-18", "days": 2},
        status="success",
        evidence_ids=["ev_weather"],
        task_id="global_weather",
    )

    save_state(state)
    loaded = load_state("trip_restore_prefetch")

    assert loaded is not None
    SupervisorAgent(MockLLMClient(), {})._prefetch_shared_data(loaded)

    assert calls == []


def test_restored_registry_skips_duplicate_research_tool_call(tmp_path, monkeypatch):
    from travel_planning_agent.agent.researcher import ResearcherAgent
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.types import AgentRequest, ToolResult

    monkeypatch.setattr("travel_planning_agent.config.settings.data_dir", str(tmp_path))
    calls = []
    legacy_calls = []

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
    monkeypatch.setattr(
        "travel_planning_agent.agent.researcher.execute_tool",
        lambda name, args: legacy_calls.append((name, args)) or "legacy should not be called",
    )

    constraints = Constraints(
        destination="南京",
        origin="杭州",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    registry = {}
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    first = agent.handle(AgentRequest(
        request_id="restore_first",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))
    state = PlanState(trip_id="trip_restore_research", constraints=constraints)
    state.module_context["_tool_calls"] = registry
    save_state(state)
    loaded = load_state("trip_restore_research")

    assert loaded is not None
    second = agent.handle(AgentRequest(
        request_id="restore_second",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": loaded.module_context["_tool_calls"],
        },
    ))

    assert first.status == "success"
    assert second.status == "success"
    assert len(calls) == 1
    assert legacy_calls == []
