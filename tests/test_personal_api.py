from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from travel_planning_agent.api.app import app
from travel_planning_agent.db.models import PlanVersion, Session, Trip, User
from travel_planning_agent.db.session import Base, get_db


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


def test_get_personal_trip_view_returns_cards_for_active_plan(client, db_session):
    trip = _create_trip(db_session, trip_id="trip_personal_001")
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=1,
            is_active=True,
            plan_data={
                "days": [
                    {
                        "day_number": 1,
                        "segments": [
                            {
                                "segment_id": "a1",
                                "type": "activity",
                                "title": "West Lake",
                                "estimated_cost": {"amount": 0},
                            },
                            {
                                "segment_id": "t1",
                                "type": "transport",
                                "title": "Metro to hotel",
                                "estimated_cost": {"amount": 6},
                            },
                        ],
                    }
                ]
            },
        )
    )
    db_session.commit()

    res = client.get(f"/api/trips/{trip.trip_id}/personal")

    assert res.status_code == 200
    body = res.json()
    assert body["decision_card"]["day_count"] == 1
    assert body["explanations"][0]["segment_id"] == "a1"
    assert body["checklist"]


def test_get_personal_trip_view_uses_active_plan_profile(client, db_session):
    trip = _create_trip(db_session, trip_id="trip_personal_economy")
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=1,
            is_active=True,
            plan_data={"profile": "economy", "days": [{"day_number": 1, "segments": []}]},
        )
    )
    db_session.commit()

    res = client.get(f"/api/trips/{trip.trip_id}/personal")

    assert res.status_code == 200
    body = res.json()
    assert body["decision_card"]["profile_id"] == "economy"
    assert body["decision_card"]["label"] == "省钱优先"


def test_get_personal_trip_view_maps_default_profile_to_classic(client, db_session):
    trip = _create_trip(db_session, trip_id="trip_personal_default")
    db_session.add(
        PlanVersion(
            trip_id=trip.trip_id,
            version=1,
            is_active=True,
            plan_data={"profile": "default", "days": [{"day_number": 1, "segments": []}]},
        )
    )
    db_session.commit()

    res = client.get(f"/api/trips/{trip.trip_id}/personal")

    assert res.status_code == 200
    body = res.json()
    assert body["decision_card"]["profile_id"] == "classic"
    assert body["decision_card"]["label"] == "经典初游"


def test_get_personal_trip_view_returns_404_for_missing_trip(client):
    res = client.get("/api/trips/missing-trip/personal")

    assert res.status_code == 404


def test_get_personal_trip_view_returns_404_without_active_plan(client, db_session):
    trip = _create_trip(db_session, trip_id="trip_without_active_plan")

    res = client.get(f"/api/trips/{trip.trip_id}/personal")

    assert res.status_code == 404


def _create_trip(db_session, trip_id: str) -> Trip:
    user = User(email=f"{trip_id}@example.com", password_hash="", display_name="Test User")
    db_session.add(user)
    db_session.flush()
    session = Session(user_id=user.user_id, title="Hangzhou")
    db_session.add(session)
    db_session.flush()
    trip = Trip(
        trip_id=trip_id,
        session_id=session.session_id,
        user_id=user.user_id,
        destination="Hangzhou",
        start_date=date(2026, 6, 1),
        days=1,
        traveler_count=1,
        budget=3000,
        pace="moderate",
    )
    db_session.add(trip)
    db_session.commit()
    return trip
