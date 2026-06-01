from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.core.session_resume import build_session_resume
from travel_planning_agent.db.models import PlanVersion, Session, SessionContext, Trip, User
from travel_planning_agent.db.session import Base


def test_build_session_resume_includes_structured_plan():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()

    try:
        user = User(email="resume-core@example.com", password_hash="", display_name="Resume")
        db.add(user)
        db.flush()
        session = Session(session_id="sess_resume_core", user_id=user.user_id, title="厦门")
        db.add(session)
        trip = Trip(
            trip_id="trip_resume_core",
            session_id=session.session_id,
            user_id=user.user_id,
            destination="厦门",
            start_date=date(2026, 5, 20),
            days=2,
            traveler_count=1,
            budget=5000,
            pace="slow",
            status="completed",
        )
        db.add(trip)
        db.add(
            PlanVersion(
                trip_id=trip.trip_id,
                version=1,
                is_active=True,
                plan_data={
                    "days": [
                        {
                            "day_number": 1,
                            "theme": "抵达厦门",
                            "segments": [
                                {
                                    "segment_id": "seg_train",
                                    "type": "transport",
                                    "start_time": "08:00",
                                    "end_time": "12:00",
                                    "title": "高铁前往厦门",
                                    "estimated_cost": {"amount": 420, "currency": "CNY"},
                                }
                            ],
                        }
                    ]
                },
            )
        )
        db.add(
            SessionContext(
                session_id=session.session_id,
                context_data={
                    "last_trip_id": trip.trip_id,
                    "last_plan_version": 1,
                    "extracted": {"origin": "杭州"},
                },
            )
        )
        db.commit()

        payload = build_session_resume(db, "sess_resume_core")

        assert payload is not None
        assert payload["plan"]["schema_version"] == "plan.v1"
        assert payload["plan"]["origin"] == "杭州"
        assert payload["plan"]["destination"] == "厦门"
        assert payload["plan"]["total_cost"] == {"amount": 420, "currency": "CNY"}
        assert payload["plan"]["days"][0]["segments"][0]["time"] == "08:00-12:00"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
