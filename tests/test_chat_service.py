from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.db.models import PlanVersion, Session, Trip, User
from travel_planning_agent.db.session import Base
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import AgentResponse


def _seed_active_plan(db, trip_id="trip_1", session_id="sess_trip"):
    user = User(user_id="user_1", email=f"{trip_id}@example.test", password_hash="", display_name="Test User")
    session = Session(session_id=session_id, user_id=user.user_id, title="测试行程")
    trip = Trip(
        trip_id=trip_id,
        session_id=session.session_id,
        user_id=user.user_id,
        destination="杭州",
        start_date=date(2026, 5, 20),
        days=2,
        traveler_count=1,
        budget=2000,
        pace="moderate",
    )
    plan = PlanVersion(
        trip_id=trip.trip_id,
        version=1,
        plan_data={
            "days": [
                {
                    "day_number": 2,
                    "theme": "经典日",
                    "segments": [
                        {"segment_id": "seg_1", "title": "雷峰塔", "type": "activity", "module": "afternoon"},
                    ],
                }
            ]
        },
        is_active=True,
    )
    db.add_all([user, session, trip, plan])
    db.commit()


def test_chat_service_returns_followup_question_with_known_context():
    from travel_planning_agent.core.chat_service import ChatService

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeIntakeAgent:
        def handle(self, request):
            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={
                    "complete": False,
                    "question": "请问这次旅行的天数是几天？",
                    "extracted": {
                        "origin": "杭州",
                        "destination": "南京",
                        "days": 2,
                        "budget": 2000,
                    },
                },
            )

    try:
        service = ChatService(db=db, intake_agent_factory=lambda _llm: FakeIntakeAgent())

        result = service.handle_message(
            message="杭州到南京，预算2000",
            session_id="sess_service_followup",
        )

        assert result.type == "question"
        assert result.session_id == "sess_service_followup"
        assert "已了解" in result.content
        assert "杭州" in result.content
        assert "南京" in result.content
        assert "请问您的出发日期是哪天？" in result.content
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_chat_service_delegates_revision_path_to_revision_service():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeSessionStore:
        def __init__(self):
            self.saved_context = None

        def load_context(self, session_id):
            return {"last_trip_id": "trip_1", "extracted": {}}

        def remember_trace_id(self, context, trace_id):
            context["last_trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, message_type=None):
            context.setdefault("messages", []).append((role, content, message_type))

        def save_context(self, session_id, context):
            context["saved"] = session_id
            self.saved_context = context

    seen = {}

    class FakeRevisionService:
        def try_apply(self, session_id, message, context, revision_intent):
            seen["call"] = {
                "session_id": session_id,
                "message": message,
                "context_trip_id": context.get("last_trip_id"),
                "intent_type": revision_intent.get("intent_type"),
            }
            return ChatServiceResult(
                type="plan_result",
                content="revised plan",
                trip_id="trip_1",
                session_id=session_id,
                plan={"schema_version": "plan.v1", "days": []},
            )

    try:
        store = FakeSessionStore()
        _seed_active_plan(db, trip_id="trip_1", session_id="sess_revision")
        service = ChatService(
            db=db,
            session_store=store,
            llm_factory=lambda mock=False: MockLLMClient(mock_data={"days": [{"day_number": 1}]}),
            revision_service_factory=lambda _db, _store: FakeRevisionService(),
        )

        result = service.handle_message("第二天太累了，轻松一点", session_id="sess_revision")

        assert seen["call"] == {
            "session_id": "sess_revision",
            "message": "第二天太累了，轻松一点",
            "context_trip_id": "trip_1",
            "intent_type": "lighten_day",
        }
        assert result.type == "plan_result"
        assert result.content == "revised plan"
        assert result.plan == {"schema_version": "plan.v1", "days": []}
        assert store.saved_context["last_response"]["plan"]["schema_version"] == "plan.v1"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_chat_service_delegates_intake_handling_to_runtime_service():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeIntakeAgent:
        def handle(self, request):
            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={"complete": False, "question": "请补充出发日期", "extracted": {"destination": "南京"}},
            )

    class FakeRuntimeService:
        def handle_intake_result(self, *, session_id, message, context, data, trace_id, llm):
            return ChatServiceResult(
                type="question",
                content=f"runtime:{data['question']}",
                session_id=session_id,
            )

    try:
        service = ChatService(
            db=db,
            intake_agent_factory=lambda _llm: FakeIntakeAgent(),
            runtime_service_factory=lambda _db, _store: FakeRuntimeService(),
        )

        result = service.handle_message("杭州到南京", session_id="sess_runtime")

        assert result.type == "question"
        assert result.content == "runtime:请补充出发日期"
        assert result.session_id == "sess_runtime"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_chat_service_returns_revision_clarification_question():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeSessionStore:
        def load_context(self, session_id):
            return {"last_trip_id": "trip_1", "extracted": {}}

        def remember_trace_id(self, context, trace_id):
            context["last_trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, message_type=None):
            context.setdefault("messages", []).append((role, content, message_type))

        def save_context(self, session_id, context):
            context["saved"] = session_id

    class FakeRevisionService:
        def try_apply(self, session_id, message, context, revision_intent):
            return ChatServiceResult(
                type="question",
                content="你想改哪一天，还是改某个具体景点/时段？",
                trip_id="trip_1",
                session_id=session_id,
            )

    try:
        _seed_active_plan(db, trip_id="trip_1", session_id="sess_revision_question")
        service = ChatService(
            db=db,
            session_store=FakeSessionStore(),
            llm_factory=lambda mock=False: MockLLMClient(mock_data={"days": [{"day_number": 1}]}),
            revision_service_factory=lambda _db, _store: FakeRevisionService(),
        )

        result = service.handle_message("改一下", session_id="sess_revision_question")

        assert result.type == "question"
        assert result.content == "你想改哪一天，还是改某个具体景点/时段？"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_chat_service_returns_append_day_clarification():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeSessionStore:
        def load_context(self, session_id):
            return {"last_trip_id": "trip_1", "extracted": {}}

        def remember_trace_id(self, context, trace_id):
            context["last_trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, message_type=None):
            context.setdefault("messages", []).append((role, content, message_type))

        def save_context(self, session_id, context):
            context["saved"] = session_id

    class FakeRevisionService:
        def try_apply(self, session_id, message, context, revision_intent):
            return ChatServiceResult(
                type="question",
                content="你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
                trip_id="trip_1",
                session_id=session_id,
            )

    try:
        _seed_active_plan(db, trip_id="trip_1", session_id="sess_append_day")
        service = ChatService(
            db=db,
            session_store=FakeSessionStore(),
            llm_factory=lambda mock=False: MockLLMClient(mock_data={"days": [{"day_number": 1}]}),
            revision_service_factory=lambda _db, _store: FakeRevisionService(),
        )

        result = service.handle_message("我还能多玩一天", session_id="sess_append_day")

        assert result.type == "question"
        assert result.content == "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_chat_service_returns_transport_change_clarification():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    class FakeSessionStore:
        def load_context(self, session_id):
            return {"last_trip_id": "trip_1", "extracted": {}}

        def remember_trace_id(self, context, trace_id):
            context["last_trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, message_type=None):
            context.setdefault("messages", []).append((role, content, message_type))

        def save_context(self, session_id, context):
            context["saved"] = session_id

    class FakeRevisionService:
        def try_apply(self, session_id, message, context, revision_intent):
            return ChatServiceResult(
                type="question",
                content="你是想只改返程，还是整趟交通方式都调整？",
                trip_id="trip_1",
                session_id=session_id,
            )

    try:
        _seed_active_plan(db, trip_id="trip_1", session_id="sess_transport_change")
        service = ChatService(
            db=db,
            session_store=FakeSessionStore(),
            llm_factory=lambda mock=False: MockLLMClient(mock_data={"days": [{"day_number": 1}]}),
            revision_service_factory=lambda _db, _store: FakeRevisionService(),
        )

        result = service.handle_message("我要坐飞机", session_id="sess_transport_change")

        assert result.type == "question"
        assert "只改返程" in result.content
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
