"""
api/trips.py — 行程 CRUD + 规划触发 API
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.db.session import get_db
from travel_planning_agent.db.models import Trip, Session, PlanVersion, User

router = APIRouter(prefix="/api/trips", tags=["行程管理"])


class TripCreate(BaseModel):
    session_id: str
    destination: str
    start_date: str
    days: int
    travelers: dict = {"adults": 2, "elderly": 0, "children": 0}
    budget: float
    pace: str = "moderate"


class TripResponse(BaseModel):
    trip_id: str
    session_id: str
    destination: str
    start_date: str
    days: int
    budget: float
    pace: str
    status: str
    created_at: str


class TripDetailResponse(TripResponse):
    active_plan: Optional[dict] = None
    verification: Optional[dict] = None
    plan_versions: list = []
    assumptions: list = []


@router.post("", response_model=TripResponse)
def create_trip(req: TripCreate, db: DBSession = Depends(get_db)):
    # 自动创建默认会话和用户（方便前端直接使用）
    session = db.query(Session).filter(Session.session_id == req.session_id).first()
    if not session:
        user = db.query(User).first()
        if not user:
            user = User(email="default@realtrip.ai", password_hash="", display_name="默认用户")
            db.add(user)
            db.commit()
            db.refresh(user)
        session = Session(user_id=user.user_id, title=req.destination)
        db.add(session)
        db.commit()
        db.refresh(session)

    t = Trip(
        session_id=session.session_id,
        user_id=session.user_id,
        destination=req.destination,
        start_date=date.fromisoformat(req.start_date),
        days=req.days,
        traveler_count=req.travelers.get("adults", 0) + req.travelers.get("elderly", 0) + req.travelers.get("children", 0),
        elderly_count=req.travelers.get("elderly", 0),
        child_count=req.travelers.get("children", 0),
        budget=req.budget,
        pace=req.pace,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return TripResponse(
        trip_id=t.trip_id, session_id=t.session_id, destination=t.destination,
        start_date=t.start_date.isoformat(), days=t.days,
        budget=t.budget, pace=t.pace, status=t.status,
        created_at=t.created_at.isoformat(),
    )


@router.get("", response_model=list[TripResponse])
def list_trips(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    q = db.query(Trip)
    if session_id:
        q = q.filter(Trip.session_id == session_id)
    if status:
        q = q.filter(Trip.status == status)
    trips = q.order_by(Trip.updated_at.desc()).limit(50).all()
    return [
        TripResponse(
            trip_id=t.trip_id, session_id=t.session_id, destination=t.destination,
            start_date=t.start_date.isoformat(), days=t.days,
            budget=t.budget, pace=t.pace, status=t.status,
            created_at=t.created_at.isoformat(),
        )
        for t in trips
    ]


@router.get("/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: str, db: DBSession = Depends(get_db)):
    t = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not t:
        raise HTTPException(404, "行程不存在")

    versions = db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id
    ).order_by(PlanVersion.version.desc()).all()

    active = next((v for v in versions if v.is_active), versions[0] if versions else None)

    return TripDetailResponse(
        trip_id=t.trip_id, session_id=t.session_id, destination=t.destination,
        start_date=t.start_date.isoformat(), days=t.days,
        budget=t.budget, pace=t.pace, status=t.status,
        created_at=t.created_at.isoformat(),
        active_plan=active.plan_data if active else None,
        verification=active.verification if active else None,
        plan_versions=[{"plan_id": v.plan_id, "version": v.version, "is_active": v.is_active} for v in versions],
        assumptions=[{"content": a.content, "level": a.level, "status": a.status} for a in t.assumptions],
    )


@router.delete("/{trip_id}")
def delete_trip(trip_id: str, db: DBSession = Depends(get_db)):
    t = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not t:
        raise HTTPException(404, "行程不存在")
    db.delete(t)
    db.commit()
    return {"status": "deleted"}
