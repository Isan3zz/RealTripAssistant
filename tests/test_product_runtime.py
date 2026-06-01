from datetime import date

from travel_planning_agent.agent.context import ContextAssembler
from travel_planning_agent.agent.planner import PlannerAgent
from travel_planning_agent.core.plan_persistence import PlanPersistenceService
from travel_planning_agent.core.plan_run_service import PlanRunService
from travel_planning_agent.core.planning_runtime import PlanningRuntime, normalize_final_day_departure, verify_whole_plan
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.tool_runtime import execute_registered_tool
from travel_planning_agent.types import (
    TripSpec, Traveler, PlanState, Constraints, ItineraryDay, Segment, SegmentType, Location
)


def test_planning_runtime_run_delegates_to_plan_run_service(monkeypatch):
    seen = {}

    class FakePlanRunService:
        def __init__(self, db, llm_client):
            seen["init"] = {"db": db, "llm_client": llm_client}

        def run(self, spec, **kwargs):
            seen["call"] = {"spec": spec, **kwargs}
            return {"run_id": "run_fake", "trip_id": "trip_fake"}

    monkeypatch.setattr("travel_planning_agent.core.planning_runtime.PlanRunService", FakePlanRunService)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
    )

    llm = MockLLMClient()
    runtime = PlanningRuntime(db=None, llm_client=llm)

    result = runtime.run(spec, persist=False)

    assert seen["init"] == {"db": None, "llm_client": llm}
    assert seen["call"]["spec"] == spec
    assert seen["call"]["persist"] is False
    assert result == {"run_id": "run_fake", "trip_id": "trip_fake"}


def test_plan_run_service_persists_failed_run_status(monkeypatch):
    seen = {}

    class FakePersistence:
        def ensure_trip(self, spec, session_id=None, trip_id=None):
            return "trip_persisted"

        def create_plan_run(self, run_id, trip_id, session_id, profile, spec, events):
            seen["created"] = True

        def persist_plan(self, trip_id, plan_data, verification, activate=True, trip_status=None):
            return 3

        def persist_evidence(self, trip_id, state):
            seen["persisted_error"] = state.error

        def finish_plan_run(self, run_id, status, events, version):
            seen["finish"] = {"status": status, "version": version}

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, **kwargs):
            return PlanState(
                trip_id="trip_runtime",
                constraints=constraints,
                error="planner failed",
            )

    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=1,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
    )

    service = PlanRunService(db=object(), llm_client=MockLLMClient())
    service.persistence = FakePersistence()

    result = service.run(spec, persist=True, use_execution_plan=False)

    assert seen["created"] is True
    assert seen["persisted_error"] == "planner failed"
    assert seen["finish"] == {"status": "failed", "version": 3}
    assert result["state"].status.value == "failed"


def test_plan_run_service_builds_supervisor_via_composition_root(monkeypatch):
    from travel_planning_agent.core.plan_run_service import PlanRunService
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.types import PlanState, TripSpec, Traveler

    seen = {}

    class FakeSupervisor:
        def run_planning_loop(self, constraints, **kwargs):
            seen["constraints"] = constraints
            return PlanState(trip_id="trip_from_composition", constraints=constraints)

    def fake_build_planning_supervisor(llm_client, use_react_research=False):
        seen["llm_client"] = llm_client
        seen["use_react_research"] = use_react_research
        return FakeSupervisor()

    monkeypatch.setattr(
        "travel_planning_agent.runtime.composition.build_planning_supervisor",
        fake_build_planning_supervisor,
        raising=False,
    )

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 19),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=3000,
        pace="slow",
    )

    service = PlanRunService(db=None, llm_client=MockLLMClient())
    result = service.run(spec, persist=False, use_execution_plan=False, use_react_research=True)

    assert seen["llm_client"] is service.llm
    assert seen["use_react_research"] is True
    assert result["trip_id"] == "trip_from_composition"


def test_plan_run_service_finalizes_failed_run_when_execution_plan_raises(monkeypatch):
    seen = {}

    class FakePersistence:
        def ensure_trip(self, spec, session_id=None, trip_id=None):
            return "trip_exec_failure"

        def create_plan_run(self, run_id, trip_id, session_id, profile, spec, events):
            seen["created"] = run_id

        def persist_plan(self, trip_id, plan_data, verification, activate=True, trip_status=None):
            seen["persist_plan"] = {"trip_status": trip_status, "trip_id": trip_id}
            return 4

        def persist_evidence(self, trip_id, state):
            seen["persist_evidence"] = state.status.value

        def finish_plan_run(self, run_id, status, events, version):
            seen["finish"] = {"run_id": run_id, "status": status, "version": version}

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=1,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
    )

    service = PlanRunService(db=object(), llm_client=MockLLMClient())
    service.persistence = FakePersistence()

    def boom(plan, reuse_context=None):
        raise RuntimeError("execution plan boom")

    monkeypatch.setattr(service, "_execute_execution_plan", boom)

    result = service.run(spec, persist=True, use_execution_plan=True)

    assert seen["created"].startswith("run_")
    assert seen["persist_plan"] == {"trip_status": "failed", "trip_id": "trip_exec_failure"}
    assert seen["persist_evidence"] == "failed"
    assert seen["finish"]["status"] == "failed"
    assert seen["finish"]["version"] == 4
    assert result["state"].status.value == "failed"
    assert result["state"].error == "execution plan boom"


def test_plan_run_service_marks_verification_failure_as_failed(monkeypatch):
    seen = {}

    class FakePersistence:
        def ensure_trip(self, spec, session_id=None, trip_id=None):
            return "trip_verify_failure"

        def create_plan_run(self, run_id, trip_id, session_id, profile, spec, events):
            seen["created"] = run_id

        def persist_plan(self, trip_id, plan_data, verification, activate=True, trip_status=None):
            seen["persist_plan"] = {"trip_status": trip_status, "verification": verification}
            return 5

        def persist_evidence(self, trip_id, state):
            seen["persist_evidence"] = state.status.value

        def finish_plan_run(self, run_id, status, events, version):
            seen["finish"] = {"status": status, "version": version}

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, **kwargs):
            return PlanState(
                trip_id="trip_runtime",
                constraints=constraints,
            )

    class FakeVerification:
        overall_pass = False
        rule_checks = []
        semantic_checks = []
        risk_checks = []
        whole_plan_checks = [{"rule_id": "W04", "result": "FAIL", "detail": "missing return"}]
        blocking_failures = [{"rule_id": "W04", "detail": "missing return"}]
        warnings = []
        correction_requests = []

    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=1,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
    )

    service = PlanRunService(db=object(), llm_client=MockLLMClient())
    service.persistence = FakePersistence()
    monkeypatch.setattr(
        "travel_planning_agent.core.plan_run_service.verify_whole_plan",
        lambda state: FakeVerification(),
    )

    result = service.run(spec, persist=True, use_execution_plan=False)

    assert seen["created"].startswith("run_")
    assert seen["persist_plan"]["trip_status"] == "failed"
    assert seen["persist_plan"]["verification"]["overall_pass"] is False
    assert seen["persist_evidence"] == "failed"
    assert seen["finish"] == {"status": "failed", "version": 5}
    assert result["state"].status.value == "failed"


def test_plan_persistence_service_persist_plan_uses_runtime_status(monkeypatch):
    import travel_planning_agent.db.models as db_models

    class FakeTrip:
        trip_id = "trip_status"

        def __init__(self):
            self.status = "started"

    class FakePlanVersion:
        trip_id = "trip_id"
        is_active = "is_active"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeQuery:
        def __init__(self, model, db):
            self.model = model
            self.db = db

        def filter(self, *args, **kwargs):
            return self

        def count(self):
            return 0

        def update(self, values):
            self.db.updated_values = values

        def first(self):
            if self.model is self.db.trip_model:
                return self.db.trip
            return None

    class FakeDB:
        def __init__(self):
            self.trip = FakeTrip()
            self.trip_model = None
            self.added = []
            self.updated_values = None
            self.commits = 0

        def query(self, model):
            if self.trip_model is None and model.__name__ == "Trip":
                self.trip_model = model
            return FakeQuery(model, self)

        def add(self, item):
            self.added.append(item)

        def commit(self):
            self.commits += 1

    monkeypatch.setattr(db_models, "PlanVersion", FakePlanVersion)

    db = FakeDB()
    service = PlanPersistenceService(db)

    version = service.persist_plan(
        "trip_status",
        {"days": []},
        {"overall_pass": False},
        activate=True,
        trip_status="failed",
    )

    assert version == 1
    assert db.trip.status == "failed"
    assert db.updated_values == {"is_active": False}
    assert db.added[0].kwargs["trip_id"] == "trip_status"


def test_context_assembler_returns_layered_context():
    state = PlanState(
        trip_id="ctx_trip",
        constraints=Constraints(
            destination="杭州",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
    )
    ctx = ContextAssembler.assemble(state, PlannerAgent(MockLLMClient()))
    assert {"l0", "l2", "l3", "l4", "l5"}.issubset(ctx.keys())
    assert ctx["l2"]["constraints"]["destination"] == "杭州"


def test_intake_build_constraints_preserves_must_have_interests():
    from travel_planning_agent.agent.intake import _build_constraints

    constraints = _build_constraints({
        "destination": "南京",
        "start_date": "2026-05-16",
        "days": 2,
        "origin": "杭州",
        "travelers": "2位成人",
        "budget": 2000,
        "pace": "fast",
        "transport_mode": "高铁",
        "interests": ["南京大屠杀纪念馆"],
    })

    assert constraints.interests == ["南京大屠杀纪念馆"]


def test_intake_extracts_chinese_must_go_phrase():
    from travel_planning_agent.agent.intake import extract_must_have_interests

    interests = extract_must_have_interests(
        "我打算明天从杭州到南京玩两天，预算两千，跟我女朋友一起，坐高铁吧，喜欢快节奏，南京大屠杀纪念馆我必须去。"
    )

    assert interests == ["南京大屠杀纪念馆"]


def test_tool_runtime_standardizes_unknown_tool_failure():
    result = execute_registered_tool("missing_tool", {})
    assert result.status == "failed"
    assert result.error
    assert result.cache_hit is False


def test_gaode_alias_tools_call_mcp_native_name(monkeypatch):
    from travel_planning_agent.tool_runtime import _execute_handler

    calls = []

    def fake_call(tool_name, args):
        calls.append((tool_name, args))
        return {"ok": True}

    monkeypatch.setattr("travel_planning_agent.gaode_client._call_tool", fake_call)

    result = _execute_handler("get_poi_detail", {"id": "poi-1"})

    assert calls == [("maps_search_detail", {"id": "poi-1"})]
    assert "ok" in result


def test_dynamic_tools_are_not_exposed_without_agent_mapping():
    from travel_planning_agent.tool_runtime import _tool_agents

    assert _tool_agents("get_poi_detail") == ["__not_exposed_to_agents__"]


def test_hotel_search_prefers_nearby_anchor(monkeypatch):
    calls = []

    def fake_search_hotel(city, keyword="", check_in="", check_out=""):
        calls.append({"city": city, "keyword": keyword})
        return [{
            "claim": "西湖边酒店 ¥500起 评分4.8 北山街",
        }]

    monkeypatch.setattr("travel_planning_agent.tuniu_client.search_hotel", fake_search_hotel)

    result = execute_registered_tool("search_hotel", {"city": "杭州", "near": "西湖"})

    assert calls == [{"city": "杭州", "keyword": "西湖"}]
    assert "西湖附近" in result.data


def test_research_plan_uses_activity_anchor_for_hotels():
    from travel_planning_agent.core.research_plan import build_research_plan

    constraints = Constraints(
        destination="杭州",
        start_date=date(2026, 5, 1),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=5000,
    )
    draft = {
        "modules": {
            "afternoon": [
                {"type": "activity", "title": "西湖漫步", "location": {"name": "西湖", "city": "杭州"}},
            ]
        }
    }

    plan = build_research_plan(constraints, [{"type": "hotel", "item": "住宿推荐"}], draft)

    assert plan.tasks[0].tool_name == "search_hotel"
    assert plan.tasks[0].args == {"city": "杭州", "nearby": "西湖"}
    assert plan.tasks[0].reuse_key == "hotel:杭州:nearby:西湖"


def test_whole_plan_verify_catches_route_buffer_shortage():
    state = PlanState(
        trip_id="route_trip",
        constraints=Constraints(
            destination="杭州",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(
                        segment_id="arrive",
                        type=SegmentType.TRANSPORT,
                        title="到达杭州",
                        start_time="08:00",
                        end_time="09:00",
                    ),
                    Segment(
                        segment_id="a1",
                        type=SegmentType.ACTIVITY,
                        title="西湖",
                        start_time="09:00",
                        end_time="10:00",
                        location=Location(name="西湖", city="杭州"),
                    ),
                    Segment(
                        segment_id="t1",
                        type=SegmentType.TRANSPORT,
                        title="步行约30分钟",
                        start_time="10:00",
                        end_time="10:10",
                    ),
                    Segment(
                        segment_id="m1",
                        type=SegmentType.MEAL,
                        title="午餐",
                        start_time="12:00",
                        end_time="13:00",
                    ),
                    Segment(
                        segment_id="h1",
                        type=SegmentType.ACCOMMODATION,
                        title="酒店",
                        start_time="20:00",
                        end_time="08:00",
                        location=Location(name="酒店", city="杭州"),
                    ),
                    Segment(
                        segment_id="return",
                        type=SegmentType.TRANSPORT,
                        title="杭州返程",
                        start_time="17:00",
                        end_time="19:00",
                    ),
                ],
            )
        ],
    )

    report = verify_whole_plan(state)

    assert any(f["rule_id"] == "W05" for f in report.blocking_failures)


def test_final_day_cleanup_removes_hotel_return_and_lodging_after_return():
    state = PlanState(
        trip_id="cleanup_trip",
        constraints=Constraints(
            origin="杭州",
            destination="南京",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
        days=[
            ItineraryDay(day_id="d1", day_number=1),
            ItineraryDay(
                day_id="d2",
                day_number=2,
                segments=[
                    Segment(segment_id="meal", type=SegmentType.MEAL, title="晚餐", start_time="16:30", end_time="18:00"),
                    Segment(segment_id="hotel_return", type=SegmentType.TRANSPORT, title="乘坐公交/地铁返回南京金陵饭店", start_time="18:10", end_time="18:40"),
                    Segment(segment_id="return", type=SegmentType.TRANSPORT, title="乘坐高铁从南京前往杭州（约2小时）", start_time="19:00", end_time="21:00"),
                    Segment(segment_id="hotel", type=SegmentType.ACCOMMODATION, title="入住杭州西湖国宾馆", start_time="22:00", end_time="23:00"),
                ],
            ),
        ],
    )

    normalize_final_day_departure(state)
    titles = [s.title for s in state.days[-1].segments]

    assert "乘坐公交/地铁返回南京金陵饭店" not in titles
    assert "入住杭州西湖国宾馆" not in titles
    assert "乘坐高铁从南京前往杭州（约2小时）" in titles


def test_return_to_hotel_does_not_satisfy_final_return_transport():
    state = PlanState(
        trip_id="hotel_return_trip",
        constraints=Constraints(
            origin="杭州",
            destination="南京",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(segment_id="a1", type=SegmentType.ACTIVITY, title="总统府"),
                    Segment(segment_id="m1", type=SegmentType.MEAL, title="晚餐"),
                    Segment(segment_id="t1", type=SegmentType.TRANSPORT, title="乘坐公交/地铁返回南京金陵饭店"),
                ],
            )
        ],
    )

    report = verify_whole_plan(state)

    assert any(f["rule_id"] == "W04" for f in report.blocking_failures)


def test_runtime_keeps_two_days_and_required_content(tmp_path, monkeypatch):
    from travel_planning_agent.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    spec = TripSpec(
        origin="南京",
        destination="杭州",
        start_date=date(2026, 5, 16),
        days=2,
        travelers=[Traveler(age_group="adult"), Traveler(age_group="adult")],
        budget=10000,
        pace="moderate",
        transport_preference="高铁",
    )
    result = PlanningRuntime(llm_client=MockLLMClient()).run(spec, persist=False)
    days = result["plan_data"]["days"]
    assert [d["day_number"] for d in days] == [1, 2]
    assert any(s["type"] == "transport" for s in days[0]["segments"])
    assert any("返程" in s["title"] or "返回" in s["title"] for s in days[-1]["segments"])
    for day in days[:-1]:
        types = {s["type"] for s in day["segments"]}
        assert {"meal", "activity", "accommodation"}.issubset(types)
    assert not any(s["type"] == "accommodation" for s in days[-1]["segments"])


def test_normalize_intercity_departure_keeps_only_big_transport_and_removes_overlap():
    from travel_planning_agent.core.plan_run_service import normalize_intercity_departure

    state = PlanState(
        trip_id="trip_departure",
        constraints=Constraints(
            origin="杭州",
            destination="厦门",
            start_date=date(2026, 5, 20),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
            transport_mode="高铁",
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(
                        segment_id="arrive",
                        type=SegmentType.TRANSPORT,
                        title="从杭州乘坐76路公交转地铁1号线再换乘D3211次列车前往厦门（约8小时）",
                        start_time="06:00",
                        end_time="14:00",
                    ),
                    Segment(
                        segment_id="temple",
                        type=SegmentType.ACTIVITY,
                        title="参观南普陀寺",
                        start_time="09:30",
                        end_time="11:00",
                    ),
                ],
            )
        ],
    )

    normalize_intercity_departure(state)

    transport = state.days[0].segments[0]
    activity = state.days[0].segments[1]
    assert transport.title == "乘坐D3211次列车 杭州 → 厦门"
    assert "公交" not in transport.title
    assert "地铁" not in transport.title
    assert activity.start_time == "14:30"
    assert activity.end_time == "16:00"


def test_plan_data_exports_attention_only_for_user_facing_notes_and_big_transport():
    from travel_planning_agent.core.plan_run_service import normalize_intercity_departure, plan_data_from_state

    state = PlanState(
        trip_id="trip_attention",
        constraints=Constraints(
            origin="杭州",
            destination="厦门",
            start_date=date(2026, 5, 20),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
            transport_mode="高铁",
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(
                        segment_id="train",
                        type=SegmentType.TRANSPORT,
                        title="从杭州乘坐D3211次列车前往厦门",
                        start_time="08:00",
                        end_time="14:00",
                    ),
                    Segment(
                        segment_id="meal",
                        type=SegmentType.MEAL,
                        title="午餐",
                        start_time="14:30",
                        end_time="15:30",
                        note="如果排队久，直接换附近同类型餐厅。",
                    ),
                    Segment(
                        segment_id="activity",
                        type=SegmentType.ACTIVITY,
                        title="鼓浪屿",
                        start_time="16:00",
                        end_time="18:00",
                        note="系统补齐的必要规划项",
                    ),
                ],
            )
        ],
    )

    normalize_intercity_departure(state)
    segments = plan_data_from_state(state)["days"][0]["segments"]

    assert segments[0]["attention"] == "请以实际出票信息为准，提前确认出发站、检票口和到站交通。"
    assert segments[1]["attention"] == "如果排队久，直接换附近同类型餐厅。"
    assert segments[2]["attention"] == ""


def test_runtime_includes_must_have_activity(tmp_path, monkeypatch):
    from travel_planning_agent.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 16),
        days=2,
        travelers=[Traveler(age_group="adult"), Traveler(age_group="adult")],
        budget=2000,
        pace="fast",
        transport_preference="高铁",
        must_have=["南京大屠杀纪念馆"],
    )

    result = PlanningRuntime(llm_client=MockLLMClient()).run(spec, persist=False)
    titles = [
        segment["title"]
        for day in result["plan_data"]["days"]
        for segment in day["segments"]
    ]

    assert any("南京大屠杀纪念馆" in title for title in titles)
    assert not any(
        failure.get("rule_id") == "W08"
        for failure in result["verification"]["blocking_failures"]
    )


def test_whole_plan_verify_catches_missing_must_have_activity():
    state = PlanState(
        trip_id="must_have_trip",
        constraints=Constraints(
            origin="杭州",
            destination="南京",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
            interests=["南京大屠杀纪念馆"],
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(segment_id="arrive", type=SegmentType.TRANSPORT, title="杭州前往南京", start_time="08:00", end_time="10:00"),
                    Segment(segment_id="a1", type=SegmentType.ACTIVITY, title="中山陵", start_time="10:30", end_time="12:00"),
                    Segment(segment_id="m1", type=SegmentType.MEAL, title="午餐", start_time="12:30", end_time="13:30"),
                    Segment(segment_id="return", type=SegmentType.TRANSPORT, title="南京返回杭州", start_time="17:00", end_time="19:00"),
                ],
            )
        ],
    )

    report = verify_whole_plan(state)

    assert any(f["rule_id"] == "W08" for f in report.blocking_failures)


def test_whole_plan_verify_catches_missing_return_transport():
    state = PlanState(
        trip_id="verify_trip",
        constraints=Constraints(
            destination="杭州",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
        days=[
            ItineraryDay(
                day_id="d1",
                day_number=1,
                segments=[
                    Segment(segment_id="a1", type=SegmentType.ACTIVITY, title="西湖"),
                    Segment(segment_id="m1", type=SegmentType.MEAL, title="午餐"),
                    Segment(segment_id="h1", type=SegmentType.ACCOMMODATION, title="酒店"),
                ],
            )
        ],
    )
    report = verify_whole_plan(state)
    assert report.overall_pass is False
    assert any(f["rule_id"] == "W03" for f in report.blocking_failures)


def test_planning_runtime_accepts_react_research_flag(monkeypatch):
    seen = {}

    class FakeSupervisor:
        def __init__(self, llm, agents):
            seen["researcher"] = agents["researcher"]

        def run_planning_loop(self, constraints, **kwargs):
            seen["constraints"] = constraints
            return PlanState(trip_id="trip_react_flag", constraints=constraints)

    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        must_have=["玄武湖"],
    )

    runtime = PlanningRuntime()
    runtime.run(spec, session_id="sess_react_flag", persist=False, use_react_research=True)

    assert getattr(seen["researcher"], "use_react_research") is True


def test_planning_runtime_executes_global_plan_and_passes_initial_evidence(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        seen["plan"] = plan
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [{
                "evidence_id": "ev_weather",
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        }

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, initial_evidence=None, execution_plan=None, tool_call_registry=None):
            seen["initial_evidence"] = initial_evidence
            seen["execution_plan"] = execution_plan
            return PlanState(trip_id="trip_exec", constraints=constraints)

    monkeypatch.setattr(PlanRunService, "_execute_execution_plan", lambda self, plan, reuse_context=None: fake_execute(plan, reuse_context))
    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_preference="高铁",
        must_have=["玄武湖"],
    )

    result = PlanningRuntime().run(spec, persist=False, use_execution_plan=True)

    assert seen["plan"].scope == "global"
    assert seen["initial_evidence"][0]["evidence_id"] == "ev_weather"
    assert seen["execution_plan"].plan_id.startswith("exec_global_")
    assert any(event["stage"] == "execution_plan" for event in result["events"])


def test_planning_runtime_passes_tool_call_registry_to_supervisor(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        from travel_planning_agent.core.tool_dedup import remember_tool_call

        remember_tool_call(
            reuse_context,
            "get_weather_forecast",
            {"city": "南京", "date": "2026-05-18", "days": 2},
            status="success",
            evidence_ids=["ev_weather"],
            task_id="global_weather",
        )
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [{
                "evidence_id": "ev_weather",
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
            "tool_calls": reuse_context,
        }

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, initial_evidence=None, execution_plan=None, tool_call_registry=None):
            seen["tool_call_registry"] = tool_call_registry
            return PlanState(trip_id="trip_registry", constraints=constraints)

    monkeypatch.setattr(PlanRunService, "_execute_execution_plan", lambda self, plan, reuse_context=None: fake_execute(plan, reuse_context))
    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_preference="高铁",
    )

    PlanningRuntime().run(spec, persist=False, use_execution_plan=True)

    assert seen["tool_call_registry"]
    assert list(seen["tool_call_registry"].values())[0]["evidence_ids"] == ["ev_weather"]
