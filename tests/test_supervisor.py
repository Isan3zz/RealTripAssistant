"""
test_supervisor.py — Supervisor 路由与降级测试
"""

from travel_planning_agent.types import (
    PlanState, PlanPhase, TripStatus, Constraints, Traveler,
    AgentRequest, AgentResponse,
)
from travel_planning_agent.models.assumption import get_default_assumptions, get_pending_explicit
from datetime import date


def test_default_assumptions_with_elderly():
    c = Constraints(destination="HZ", start_date=date(2026, 5, 1), end_date=3,
                    travelers=[Traveler(age_group="adult"), Traveler(age_group="elderly")],
                    budget=10000, pace="slow")
    assumptions = get_default_assumptions(c)
    explicit = [a for a in assumptions if a.level.value == "explicit"]
    assert any("老人" in a.content for a in explicit)


def test_default_assumptions_without_elderly():
    c = Constraints(destination="HZ", start_date=date(2026, 5, 1), end_date=3,
                    travelers=[Traveler(age_group="adult")],
                    budget=10000, pace="moderate")
    assumptions = get_default_assumptions(c)
    explicit = [a for a in assumptions if a.level.value == "explicit"]
    assert len(explicit) == 0


def test_pending_questions_limit():
    c = Constraints(destination="HZ", start_date=date(2026, 5, 1), end_date=3,
                    travelers=[Traveler(age_group="adult")], budget=10000, pace="slow")
    assumptions = get_default_assumptions(c)
    pending = get_pending_explicit(assumptions)
    assert len(pending) <= 3


class MockAgent:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail

    def handle(self, request: AgentRequest) -> AgentResponse:
        if self.fail:
            raise Exception("mock failure")
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={"result": f"{self.name}_done"},
        )


def test_supervisor_agent_dispatch():
    """验证 Supervisor 分发到子 Agent。"""
    agents = {
        "researcher": MockAgent("researcher"),
        "planner": MockAgent("planner"),
    }

    req = AgentRequest(
        request_id="req_001", agent="researcher",
        context={"key": "val"}, params={"category": "poi"},
    )

    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    llm = MockLLMClient()
    supervisor = SupervisorAgent(llm, agents)

    # 直接分发测试
    response = supervisor.dispatch_with_degrade("researcher", req)
    assert response.status == "success"
    assert response.data["result"] == "researcher_done"


def test_run_pipeline_loop_delegates_to_daily_pipeline_runner(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    called = {}

    def fake_run(self, state):
        called["trip_id"] = state.trip_id

    monkeypatch.setattr(
        "travel_planning_agent.agent.supervisor.SupervisorAgent._run_pipeline_loop_impl",
        fake_run,
    )

    state = PlanState(
        trip_id="delegation_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
    )
    supervisor = SupervisorAgent(MockLLMClient(), {})

    supervisor._run_pipeline_loop(state)

    assert called == {"trip_id": "delegation_trip"}


def test_prefetch_shared_data_only_fetches_weather(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    calls = []

    def fake_execute_tool(tool_name, args):
        calls.append((tool_name, args))
        return "【天气】HZ：\n- 2026-05-01 晴/晴\n- 2026-05-02 多云/多云"

    monkeypatch.setattr("travel_planning_agent.tools.execute_tool", fake_execute_tool)

    state = PlanState(
        trip_id="pref_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
    )
    supervisor = SupervisorAgent(MockLLMClient(), {})

    supervisor._prefetch_shared_data(state)

    assert calls == [("get_weather_forecast", {"city": "HZ", "date": "2026-05-01", "days": 2})]
    assert list(state.evidence.keys()) == ["pref_trip_pref_weather"]


def test_prefetch_shared_data_delegates_state_write_to_planning_state_service(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    writes = []

    class FakePlanningStateService:
        def remember_prefetched_weather(self, state, weather_text):
            writes.append((state.trip_id, weather_text))

    monkeypatch.setattr(
        "travel_planning_agent.core.planning_state_service.PlanningStateService",
        lambda: FakePlanningStateService(),
    )
    monkeypatch.setattr(
        "travel_planning_agent.tools.execute_tool",
        lambda tool_name, args: "【天气】HZ：\n- 2026-05-01 晴/晴",
    )

    state = PlanState(
        trip_id="state_service_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=1000,
        ),
    )

    supervisor = SupervisorAgent(MockLLMClient(), {})
    supervisor._prefetch_shared_data(state)

    assert writes == [("state_service_trip", "【天气】HZ：\n- 2026-05-01 晴/晴")]


def test_prefetch_shared_data_skips_duplicate_weather_tool_call(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.core.tool_dedup import get_tool_call_registry, remember_tool_call
    from travel_planning_agent.llm import MockLLMClient

    calls = []

    def fake_execute_tool(tool_name, args):
        calls.append((tool_name, args))
        return "should not be called"

    monkeypatch.setattr("travel_planning_agent.tools.execute_tool", fake_execute_tool)

    state = PlanState(
        trip_id="pref_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
    )
    registry = get_tool_call_registry(state.module_context)
    remember_tool_call(
        registry,
        "get_weather_forecast",
        {"city": "HZ", "date": "2026-05-01", "days": 2},
        status="success",
        evidence_ids=["ev_existing_weather"],
        task_id="global_weather",
    )

    supervisor = SupervisorAgent(MockLLMClient(), {})
    supervisor._prefetch_shared_data(state)

    assert calls == []
    assert state.evidence == {}


def test_supervisor_builds_cumulative_previous_days_context():
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    supervisor = SupervisorAgent(MockLLMClient(), {})
    draft_results = {
        1: {
            "day_theme": "第一天主题",
            "modules": {
                "morning": [{"title": "南普陀寺", "location": {"name": "南普陀寺"}}],
                "afternoon": [{"title": "沙坡尾", "location": {"name": "沙坡尾"}}],
            },
        },
        2: {
            "day_theme": "第二天主题",
            "modules": {
                "morning": [{"title": "鼓浪屿", "location": {"name": "鼓浪屿"}}],
                "evening": [{"title": "中山路", "location": {"name": "中山路步行街"}}],
            },
        },
    }

    context = supervisor._format_previous_days_context(draft_results, upto_day=2)

    assert "第一天主题" in context
    assert "第二天主题" in context
    assert "南普陀寺" in context
    assert "鼓浪屿" in context
