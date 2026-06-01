"""
api/sessions.py — 会话管理 API
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.db.session import get_db
from travel_planning_agent.db.models import Session, User

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])


class SessionCreate(BaseModel):
    user_id: str
    title: str = "新建行程"


class SessionResponse(BaseModel):
    session_id: str
    title: str
    status: str
    created_at: str


class ResumeMessage(BaseModel):
    role: str
    content: str
    type: Optional[str] = None


class SessionResumeResponse(BaseModel):
    session_id: str
    can_resume: bool
    title: str
    status: str
    updated_at: Optional[str] = None
    last_message_preview: str = ""
    last_trace_id: Optional[str] = None
    trace_ids: list[str] = []
    messages: list[ResumeMessage] = []
    extracted: dict = {}
    last_trip_id: Optional[str] = None
    last_plan_version: Optional[int] = None
    last_plan_summary: Optional[dict] = None
    plan: Optional[dict] = None
    context_ledger_summary: dict = {}
    context_pack_preview: Optional[dict] = None
    suggested_next_action: str


@router.post("", response_model=SessionResponse)
def create_session(req: SessionCreate, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    session = Session(user_id=req.user_id, title=req.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        status=session.status,
        created_at=session.created_at.isoformat(),
    )


@router.get("", response_model=list[SessionResponse])
def list_sessions(user_id: str, db: DBSession = Depends(get_db)):
    sessions = db.query(Session).filter(
        Session.user_id == user_id,
        Session.status == "active",
    ).order_by(Session.updated_at.desc()).all()
    return [
        SessionResponse(
            session_id=s.session_id, title=s.title,
            status=s.status, created_at=s.created_at.isoformat(),
        )
        for s in sessions
    ]


@router.get("/recent", response_model=list[SessionResumeResponse])
def recent_sessions(limit: int = 20, db: DBSession = Depends(get_db)):
    from travel_planning_agent.core.session_resume import list_recent_session_resumes

    bounded_limit = max(1, min(limit, 50))
    return [SessionResumeResponse(**item) for item in list_recent_session_resumes(db, bounded_limit)]


@router.get("/{session_id}/resume", response_model=SessionResumeResponse)
def resume_session(session_id: str, db: DBSession = Depends(get_db)):
    from travel_planning_agent.core.session_resume import build_session_resume
    from travel_planning_agent.core.tracing import (
        clear_trace_context,
        create_trace_id,
        record_trace_event,
        set_trace_context,
    )

    payload = build_session_resume(db, session_id, include_context_pack=True)
    if not payload:
        raise HTTPException(404, "会话不存在")
    trace_id = create_trace_id()
    set_trace_context(trace_id, session_id=session_id)
    try:
        record_trace_event(
            "session_resumed",
            "session",
            {
                "can_resume": payload["can_resume"],
                "last_trip_id": payload.get("last_trip_id"),
                "suggested_next_action": payload.get("suggested_next_action"),
            },
            trace_id=trace_id,
            session_id=session_id,
        )
    finally:
        clear_trace_context()
    return SessionResumeResponse(**payload)


@router.delete("/{session_id}")
def delete_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        raise HTTPException(404, "会话不存在")
    session.status = "deleted"
    db.commit()
    return {"status": "deleted"}
