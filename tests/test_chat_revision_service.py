from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.core.chat_revision_service import ChatRevisionService
from travel_planning_agent.core.chat_types import ChatServiceResult
from travel_planning_agent.db.models import PlanVersion, Session, Trip, User
from travel_planning_agent.db.session import Base


def _make_db_with_active_plan():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    user = User(user_id="user_1", email="revision-service@example.test", password_hash="", display_name="Test")
    session = Session(session_id="sess_1", user_id=user.user_id, title="测试行程")
    trip = Trip(
        trip_id="trip_1",
        session_id=session.session_id,
        user_id=user.user_id,
        destination="南京",
        start_date=date(2026, 5, 20),
        days=2,
        traveler_count=1,
        budget=2000,
        pace="moderate",
    )
    plan = PlanVersion(
        trip_id=trip.trip_id,
        version=1,
        plan_data={"days": [{"day_number": 2, "segments": [{"title": "玄武湖", "type": "activity"}]}]},
        is_active=True,
    )
    db.add_all([user, session, trip, plan])
    db.commit()
    return engine, db


def test_chat_revision_service_returns_clarification_for_vague_scope():
    service = ChatRevisionService(db=None, session_store=None)

    result = service._build_scope_result(
        session_id="sess_1",
        trip_id="trip_1",
        parsed_scope={
            "matched": False,
            "clarification_needed": True,
            "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
        },
    )

    assert isinstance(result, ChatServiceResult)
    assert result.type == "question"
    assert result.content == "你想改哪一天，还是改某个具体景点/时段？"


def test_chat_revision_service_returns_none_when_not_revision_scope():
    service = ChatRevisionService(db=None, session_store=None)

    result = service._build_scope_result(
        session_id="sess_1",
        trip_id="trip_1",
        parsed_scope={
            "matched": False,
            "clarification_needed": False,
            "clarification_question": "",
        },
    )

    assert result is None


def test_chat_revision_service_returns_clarification_for_append_day():
    service = ChatRevisionService(db=None, session_store=None)

    result = service._build_strategy_result(
        session_id="sess_1",
        trip_id="trip_1",
        strategy_result={
            "strategy": "clarify",
            "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
        },
    )

    assert result.type == "question"
    assert result.content == "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？"


def test_chat_revision_service_returns_false_for_patch_strategy():
    service = ChatRevisionService(db=None, session_store=None)

    result = service._build_strategy_result(
        session_id="sess_1",
        trip_id="trip_1",
        strategy_result={"strategy": "patch_scope"},
    )

    assert result is False


def test_chat_revision_service_asks_when_classification_failed():
    engine, db = _make_db_with_active_plan()
    service = ChatRevisionService(db=db, session_store=None)

    try:
        result = service.try_apply(
            "sess_1",
            "改一下",
            {"last_trip_id": "trip_1"},
            {
                "is_revision": True,
                "intent_type": None,
                "scope_type": "unknown",
                "classification_failed": True,
                "clarification_needed": True,
                "clarification_question": "你想改哪一天？",
            },
        )

        assert result.type == "question"
        assert "不太确定" in result.content
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
