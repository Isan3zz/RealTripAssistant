from datetime import date
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.api.app import app
from travel_planning_agent.config import settings
from travel_planning_agent.db.models import PlanVersion, Session, SessionContext, Trip, User
from travel_planning_agent.db.session import Base, get_db
from travel_planning_agent.types import AgentResponse, Constraints, PlanState, Traveler


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_resume_session_from_context_only(client, db_session):
    db_session.add(
        SessionContext(
            session_id="sess_resume_context",
            context_data={
                "extracted": {
                    "destination": "Nanjing",
                    "start_date": "2026-05-17",
                    "days": 2,
                    "origin": "Hangzhou",
                    "budget": 2000,
                },
                "messages": [
                    {"role": "user", "content": "Hangzhou to Nanjing for two days"},
                    {"role": "assistant", "content": "Which travel style do you prefer?", "type": "question"},
                    {"role": "system", "content": "internal note"},
                    {"role": "assistant", "content": ""},
                ],
                "trace_ids": ["trace_old"],
                "last_trace_id": "trace_old",
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_resume_context/resume")

    assert res.status_code == 200
    body = res.json()
    assert body["can_resume"] is True
    assert body["session_id"] == "sess_resume_context"
    assert body["title"] == "Nanjing"
    assert body["extracted"]["destination"] == "Nanjing"
    assert body["updated_at"]
    assert body["last_message_preview"] == "Which travel style do you prefer?"
    assert body["last_trace_id"] == "trace_old"
    assert body["trace_ids"] == ["trace_old"]
    assert body["messages"] == [
        {"role": "user", "content": "Hangzhou to Nanjing for two days", "type": None},
        {"role": "assistant", "content": "Which travel style do you prefer?", "type": "question"},
    ]
    assert body["suggested_next_action"] == "continue_chat"


def test_resume_session_with_last_active_plan(client, db_session):
    user = User(email="resume@example.com", password_hash="", display_name="Resume")
    db_session.add(user)
    db_session.flush()
    session = Session(session_id="sess_resume_plan", user_id=user.user_id, title="Nanjing")
    db_session.add(session)
    trip = Trip(
        trip_id="trip_resume_plan",
        session_id=session.session_id,
        user_id=user.user_id,
        destination="Nanjing",
        start_date=date(2026, 5, 17),
        days=2,
        traveler_count=1,
        budget=2000,
        pace="slow",
        status="completed",
    )
    db_session.add(trip)
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=1,
            is_active=True,
            plan_data={
                "days": [
                    {"day_number": 1, "segments": [{"type": "activity", "estimated_cost": {"amount": 80}}]},
                    {"day_number": 2, "segments": [{"type": "meal", "estimated_cost": {"amount": 100}}]},
                ]
            },
            verification={"overall_pass": True},
        )
    )
    db_session.add(
        SessionContext(
            session_id=session.session_id,
            context_data={
                "last_trip_id": trip.trip_id,
                "last_plan_version": 1,
                "messages": [{"role": "assistant", "content": "Plan completed", "type": "plan"}],
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_resume_plan/resume")

    assert res.status_code == 200
    body = res.json()
    assert body["last_trip_id"] == "trip_resume_plan"
    assert body["last_plan_version"] == 1
    assert body["last_plan_summary"] == {"days": 2, "total_cost": 180, "activities": 1}
    assert body["plan"]["schema_version"] == "plan.v1"
    assert body["plan"]["destination"] == "Nanjing"
    assert body["plan"]["total_cost"] == {"amount": 180, "currency": "CNY"}
    assert body["suggested_next_action"] == "view_trip"


def test_resume_missing_session_returns_404(client):
    res = client.get("/api/sessions/not_found/resume")

    assert res.status_code == 404


def test_chat_persists_user_and_assistant_messages_for_resume(client, monkeypatch):
    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={
                "complete": False,
                "question": "Which travel style do you prefer?",
                "extracted": {
                    "destination": "Nanjing",
                    "start_date": "2026-05-17",
                    "days": 2,
                    "origin": "Hangzhou",
                    "budget": 2000,
                },
            },
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post(
        "/api/chat",
        json={"session_id": "sess_chat_history", "message": "Hangzhou to Nanjing for two days"},
    )

    assert res.status_code == 200
    resume = client.get("/api/sessions/sess_chat_history/resume").json()
    assert resume["messages"] == [
        {"role": "user", "content": "Hangzhou to Nanjing for two days", "type": None},
        {"role": "assistant", "content": res.json()["content"], "type": "question"},
    ]
    assert resume["last_trace_id"].startswith("trace_")
    assert resume["trace_ids"] == [resume["last_trace_id"]]
    assert resume["suggested_next_action"] == "continue_chat"


def test_recent_sessions_returns_server_persisted_resume_summaries(client, db_session):
    user = User(email="recent@example.com", password_hash="", display_name="Recent")
    db_session.add(user)
    db_session.flush()
    db_session.add_all(
        [
            Session(session_id="sess_old", user_id=user.user_id, title="Old Trip"),
            Session(session_id="sess_new", user_id=user.user_id, title="New Trip"),
        ]
    )
    db_session.add_all(
        [
            SessionContext(
                session_id="sess_old",
                context_data={"messages": [{"role": "user", "content": "old message"}]},
            ),
            SessionContext(
                session_id="sess_new",
                context_data={"messages": [{"role": "user", "content": "new message"}]},
            ),
        ]
    )
    db_session.commit()

    # Force deterministic ordering by touching the newer context last.
    new_context = db_session.query(SessionContext).filter(SessionContext.session_id == "sess_new").one()
    new_context.context_data = {
        "messages": [{"role": "user", "content": "new message"}, {"role": "assistant", "content": "new reply"}]
    }
    db_session.commit()

    res = client.get("/api/sessions/recent")

    assert res.status_code == 200
    body = res.json()
    assert [item["session_id"] for item in body[:2]] == ["sess_new", "sess_old"]
    assert body[0]["title"] == "New Trip"
    assert body[0]["last_message_preview"] == "new reply"


def test_chat_sets_session_title_before_planning(client, db_session, monkeypatch):
    constraints = Constraints(
        origin="Hangzhou",
        destination="Nanjing",
        start_date=date(2026, 5, 17),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_mode="train",
        interests=["Xuanwu Lake"],
    )

    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={"complete": True, "constraints": constraints},
        )

    def fake_title(llm, constraints_arg, user_message):
        assert constraints_arg.destination == "Nanjing"
        assert user_message == "Plan Hangzhou to Nanjing"
        return "Hangzhou to Nanjing Slow Trip"

    def fake_run(self, spec, session_id=None, trip_id=None, profile="default", persist=True, activate_plan=True):
        session = db_session.query(Session).filter(Session.session_id == session_id).one()
        assert session.title == "Hangzhou to Nanjing Slow Trip"
        state = PlanState(trip_id="trip_named", constraints=constraints)
        return {
            "run_id": "run_named",
            "trip_id": "trip_named",
            "state": state,
            "plan_data": {"days": []},
            "verification": None,
            "plan_version": 1,
            "events": [],
        }

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)
    monkeypatch.setattr("travel_planning_agent.core.session_naming.generate_session_title", fake_title)
    monkeypatch.setattr("travel_planning_agent.core.planning_runtime.PlanningRuntime.run", fake_run)

    res = client.post(
        "/api/chat",
        json={"session_id": "sess_named", "message": "Plan Hangzhou to Nanjing"},
    )

    assert res.status_code == 200
    assert res.json()["type"] == "plan_result"
    assert res.json()["plan"]["schema_version"] == "plan.v1"
    assert res.json()["plan"]["destination"] == "Nanjing"
    session = db_session.query(Session).filter(Session.session_id == "sess_named").one()
    assert session.title == "Hangzhou to Nanjing Slow Trip"


def test_resume_session_writes_trace_event(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    db_session.add(
        SessionContext(
            session_id="sess_trace_resume",
            context_data={"messages": [{"role": "user", "content": "continue"}]},
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_trace_resume/resume")

    assert res.status_code == 200
    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event = trace["events"][0]
    assert event["event_type"] == "session_resumed"
    assert event["stage"] == "session"
    assert event["session_id"] == "sess_trace_resume"


def test_chat_persists_context_ledger_for_partial_intake(client, db_session, monkeypatch):
    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={
                "complete": False,
                "question": "请问您的出发日期是哪天？",
                "extracted": {
                    "destination": "南京",
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                    "transport_mode": "train",
                    "interests": ["玄武湖"],
                },
            },
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post(
        "/api/chat",
        json={"session_id": "sess_partial_ledger", "message": "杭州去南京两天，高铁，想看玄武湖，预算2000"},
    )

    assert res.status_code == 200
    rec = db_session.query(SessionContext).filter(SessionContext.session_id == "sess_partial_ledger").one()
    ledger = rec.context_data["context_ledger"]
    assert ledger["initial_constraints"] is None
    assert ledger["active_constraints"]["destination"] == "南京"
    assert ledger["active_constraints"]["interests"] == ["玄武湖"]


def test_chat_persists_initial_and_active_context_ledger_after_plan(client, db_session, monkeypatch):
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_mode="train",
        interests=["玄武湖"],
    )

    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={"complete": True, "constraints": constraints},
        )

    def fake_run(self, spec, session_id=None, trip_id=None, profile="default", persist=True, activate_plan=True):
        state = PlanState(trip_id="trip_ledger", constraints=constraints)
        return {
            "run_id": "run_ledger",
            "trip_id": "trip_ledger",
            "state": state,
            "plan_data": {"days": []},
            "verification": None,
            "plan_version": 1,
            "events": [],
        }

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)
    monkeypatch.setattr("travel_planning_agent.core.session_naming.generate_session_title", lambda llm, c, m: "南京慢游")
    monkeypatch.setattr("travel_planning_agent.core.planning_runtime.PlanningRuntime.run", fake_run)

    res = client.post(
        "/api/chat",
        json={"session_id": "sess_complete_ledger", "message": "明天杭州去南京玩两天，坐高铁，看玄武湖，预算2000"},
    )

    assert res.status_code == 200
    rec = db_session.query(SessionContext).filter(SessionContext.session_id == "sess_complete_ledger").one()
    ledger = rec.context_data["context_ledger"]
    assert ledger["initial_constraints"]["destination"] == "南京"
    assert ledger["initial_constraints"]["start_date"] == "2026-05-18"
    assert ledger["initial_constraints"]["budget"] == 2000
    assert ledger["active_constraints"]["pace"] == "slow"
    assert ledger["source_refs"]["initial_trace_id"].startswith("trace_")


def test_resume_session_returns_context_ledger_summary(client, db_session):
    db_session.add(
        SessionContext(
            session_id="sess_ledger_resume",
            context_data={
                "messages": [{"role": "user", "content": "继续"}],
                "context_ledger": {
                    "schema_version": 1,
                    "initial_constraints": {"destination": "南京", "days": 2},
                    "active_constraints": {"destination": "南京", "days": 2, "pace": "slow"},
                    "overrides": [{"field": "pace", "old_value": "moderate", "new_value": "slow"}],
                    "revision_notes": [{"message": "第二天轻松一点"}],
                    "source_refs": {"initial_trace_id": "trace_initial"},
                },
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_ledger_resume/resume")

    assert res.status_code == 200
    body = res.json()
    assert body["context_ledger_summary"] == {
        "has_initial_constraints": True,
        "active_constraint_keys": ["days", "destination", "pace"],
        "override_count": 1,
        "revision_note_count": 1,
        "initial_trace_id": "trace_initial",
    }


def test_resume_context_pack_keeps_active_plan_compact(client, db_session):
    user = User(email="pack@example.com", password_hash="", display_name="Pack")
    db_session.add(user)
    db_session.flush()
    session = Session(session_id="sess_pack", user_id=user.user_id, title="南京")
    db_session.add(session)
    trip = Trip(
        trip_id="trip_pack",
        session_id=session.session_id,
        user_id=user.user_id,
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        traveler_count=1,
        budget=2000,
        pace="slow",
        status="completed",
    )
    db_session.add(trip)
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=2,
            is_active=True,
            plan_data={
                "version": 2,
                "profile": "slow",
                "days": [
                    {
                        "day_number": 1,
                        "theme": "玄武湖",
                        "segments": [
                            {
                                "segment_id": "seg_lake",
                                "type": "activity",
                                "title": "玄武湖",
                                "start_time": "10:00",
                                "end_time": "12:00",
                                "estimated_cost": {"amount": 0, "currency": "CNY"},
                            }
                        ],
                    }
                ],
            },
        )
    )
    db_session.add(
        SessionContext(
            session_id=session.session_id,
            context_data={
                "last_trip_id": trip.trip_id,
                "messages": [{"role": "user", "content": "继续"}],
                "context_ledger": {
                    "schema_version": 1,
                    "initial_constraints": {"destination": "南京"},
                    "active_constraints": {"destination": "南京"},
                    "overrides": [],
                    "revision_notes": [],
                    "source_refs": {},
                },
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_pack/resume")

    assert res.status_code == 200
    pack = res.json()["context_pack_preview"]
    assert pack["initial_constraints"]["destination"] == "南京"
    assert pack["full_plan_compact"]["days"][0]["segments"][0]["segment_id"] == "seg_lake"
    assert pack["full_plan_compact"]["totals"]["segments"] == 1
