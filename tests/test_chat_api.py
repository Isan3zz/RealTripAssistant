from datetime import date
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.api.app import app
from travel_planning_agent.api.chat import _format_days_text
from travel_planning_agent.db.models import PlanVersion, Session, SessionContext, Trip, User
from travel_planning_agent.db.session import Base, get_db
from travel_planning_agent.types import AgentResponse, Cost, ItineraryDay, PlanState, Segment, SegmentType


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
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_chat_routes_new_personal_revision_intent_to_revision_flow(client, db_session, monkeypatch):
    session_id = "sess_revision_personal"
    trip = _create_trip_with_active_plan(db_session)
    db_session.add(
        SessionContext(
            session_id=session_id,
            context_data={
                "last_trip_id": trip.trip_id,
                "last_plan_version": 1,
                "extracted": {"origin": "杭州"},
            },
        )
    )
    db_session.commit()

    def fake_revise_day(self, plan_data, trip_info, intent, evidence):
        assert intent["type"] == "lighten_day"
        assert intent["target_day"] == 2
        return {
            "day_number": 2,
            "theme": "轻松一点的南京",
            "segments": [
                {
                    "segment_id": "d2_light",
                    "type": "activity",
                    "title": "玄武湖轻松散步",
                    "start_time": "10:00",
                    "end_time": "11:30",
                }
            ],
        }

    monkeypatch.setattr("travel_planning_agent.agent.revision.RevisionAgent.revise_day", fake_revise_day)

    res = client.post("/api/chat", json={"session_id": session_id, "message": "第二天太累了，轻松一点"})

    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "plan_result"
    assert "已根据你的要求重新规划" in body["content"]

    active = db_session.query(PlanVersion).filter(
        PlanVersion.trip_id == trip.trip_id,
        PlanVersion.is_active == True,  # noqa: E712
    ).one()
    assert active.version == 2
    assert active.diff_previous["reason"] == "第二天太累了，轻松一点"
    assert active.plan_data["days"][1]["theme"] == "轻松一点的南京"


def test_chat_response_model_includes_structured_plan(client, monkeypatch):
    from travel_planning_agent.core.chat_types import ChatServiceResult

    def fake_handle_message(self, message, session_id=None):
        return ChatServiceResult(
            type="plan_result",
            content="plan generated",
            trip_id="trip_1",
            session_id="sess_1",
            plan={"schema_version": "plan.v1", "days": []},
        )

    monkeypatch.setattr("travel_planning_agent.core.chat_service.ChatService.handle_message", fake_handle_message)

    res = client.post("/api/chat", json={"message": "\u676d\u5dde\u53bb\u53a6\u95e8\u4e09\u5929"})

    assert res.status_code == 200
    assert res.json()["plan"]["schema_version"] == "plan.v1"


def test_chat_plan_output_includes_explanation_sections():
    state = PlanState(trip_id="trip_explain")
    state.days = [
        ItineraryDay(
            day_id="day_1",
            day_number=1,
            theme="初探徐州历史文化",
            segments=[
                Segment(
                    segment_id="a1",
                    type=SegmentType.ACTIVITY,
                    title="参观徐州博物馆",
                    start_time="11:20",
                    end_time="12:00",
                    estimated_cost=Cost(amount=0),
                    tags=["classic"],
                )
            ],
        )
    ]

    text = _format_days_text(state)

    assert "为什么推荐：" in text
    assert "注意事项：" in text


def test_chat_plan_output_uses_weather_aware_explanations():
    state = PlanState(trip_id="trip_rain_explain")
    state.days = [
        ItineraryDay(
            day_id="day_1",
            day_number=1,
            theme="雨天徐州",
            day_note="暴雨/中雨，20~21°C，建议带伞",
            segments=[
                Segment(
                    segment_id="lake",
                    type=SegmentType.ACTIVITY,
                    title="游览云龙湖景区",
                    start_time="16:00",
                    end_time="18:00",
                    estimated_cost=Cost(amount=0),
                    tags=["outdoor"],
                )
            ],
        )
    ]

    text = _format_days_text(state)

    assert "降雨" in text
    assert "室内备选" in text


def test_chat_rewrites_old_pace_followup_to_personal_profile_options(client, monkeypatch):
    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={
                "complete": False,
                "question": "请问您这次旅行的节奏是怎样的？慢/适中/快？",
                "extracted": {
                    "destination": "徐州",
                    "start_date": "2026-06-01",
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                },
            },
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post("/api/chat", json={"message": "杭州到徐州两天预算2000"})

    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "question"
    assert "慢/适中/快" not in body["content"]
    assert "轻松慢游" in body["content"]
    assert "经典初游" in body["content"]


def test_chat_does_not_ask_for_already_known_days(client, monkeypatch):
    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={
                "complete": False,
                "question": "请问您这次旅行的天数是几天？",
                "extracted": {
                    "destination": "南京",
                    "start_date": "2026-05-17",
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                    "transport_mode": "高铁",
                    "interests": ["玄武湖"],
                },
            },
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post("/api/chat", json={"message": "杭州到南京两天预算2000，高铁，必去玄武湖"})

    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "question"
    assert "天数是几天" not in body["content"]
    assert "旅行方式" in body["content"]


def test_chat_writes_json_trace_for_user_input_and_intake(client, monkeypatch, tmp_path):
    from travel_planning_agent.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    def fake_handle(self, request):
        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={
                "complete": False,
                "question": "请问你更偏向哪种旅行方式：轻松慢游、经典初游、美食深度，还是省钱优先？",
                "extracted": {
                    "destination": "南京",
                    "start_date": "2026-05-17",
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                },
            },
            tokens_used=42,
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post("/api/chat", json={"message": "杭州到南京两天预算2000"})

    assert res.status_code == 200
    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event_types = [event["event_type"] for event in trace["events"]]
    assert "user_input" in event_types
    assert "intake_result" in event_types
    assert trace["events"][0]["data"]["message"] == "杭州到南京两天预算2000"
    intake_event = next(event for event in trace["events"] if event["event_type"] == "intake_result")
    assert intake_event["data"]["status"] == "success"
    assert intake_event["data"]["tokens_used"] == 42


def _create_trip_with_active_plan(db_session) -> Trip:
    user = User(email="chat-revision@example.com", password_hash="", display_name="Chat Revision")
    db_session.add(user)
    db_session.flush()
    session = Session(user_id=user.user_id, title="南京")
    db_session.add(session)
    db_session.flush()
    trip = Trip(
        trip_id="trip_chat_revision",
        session_id=session.session_id,
        user_id=user.user_id,
        destination="南京",
        start_date=date(2026, 6, 1),
        days=2,
        traveler_count=1,
        budget=3000,
        pace="moderate",
        status="completed",
    )
    db_session.add(trip)
    db_session.flush()
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=1,
            is_active=True,
            plan_data={
                "days": [
                    {
                        "day_number": 1,
                        "theme": "抵达南京",
                        "segments": [
                            {"segment_id": "d1a", "type": "activity", "title": "夫子庙", "start_time": "15:00", "end_time": "17:00"},
                        ],
                    },
                    {
                        "day_number": 2,
                        "theme": "南京经典游",
                        "segments": [
                            {"segment_id": "d2a", "type": "activity", "title": "总统府", "start_time": "09:00", "end_time": "11:00"},
                            {"segment_id": "d2b", "type": "activity", "title": "南京博物院", "start_time": "13:00", "end_time": "16:30"},
                        ],
                    },
                ]
            },
            verification={"overall_pass": True},
        )
    )
    db_session.commit()
    return trip
