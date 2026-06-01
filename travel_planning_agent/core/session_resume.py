"""Build session resume payloads for the chat UI."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.core.context_ledger import build_context_pack
from travel_planning_agent.core.plan_schema import format_plan_view
from travel_planning_agent.db.models import PlanVersion, Session, SessionContext


def build_session_resume(
    db: DBSession,
    session_id: str,
    *,
    include_context_pack: bool = False,
) -> dict | None:
    session = db.query(Session).filter(Session.session_id == session_id).first()
    context_rec = db.query(SessionContext).filter(SessionContext.session_id == session_id).first()
    if not session and not context_rec:
        return None

    context = dict(context_rec.context_data or {}) if context_rec else {}
    extracted = dict(context.get("extracted") or {})
    messages = _clean_messages(context.get("messages") or [])
    last_trip_id = context.get("last_trip_id")
    last_plan_version = context.get("last_plan_version")
    active_plan = None
    last_plan_summary = None
    plan = None

    if last_trip_id:
        active_plan = (
            db.query(PlanVersion)
            .filter(PlanVersion.trip_id == last_trip_id, PlanVersion.is_active == True)  # noqa: E712
            .order_by(PlanVersion.version.desc())
            .first()
        )
        if active_plan:
            last_plan_version = active_plan.version
            last_plan_summary = summarize_plan_data(active_plan.plan_data or {})
            plan = format_plan_view(
                active_plan.plan_data or {},
                trip=_trip_view_source(active_plan.trip, extracted),
                summary=last_plan_summary,
            )

    context_pack_preview = None
    if include_context_pack:
        context_pack_preview = build_context_pack(
            context,
            current_message="",
            active_plan=active_plan.plan_data if active_plan else None,
            purpose="resume_preview",
        )

    return {
        "session_id": session_id,
        "can_resume": bool(messages or extracted or last_trip_id),
        "title": _session_title(session, extracted, active_plan),
        "status": session.status if session else "active",
        "updated_at": _latest_updated_at(session, context_rec),
        "last_message_preview": _last_message_preview(messages),
        "last_trace_id": context.get("last_trace_id"),
        "trace_ids": list(context.get("trace_ids") or []),
        "messages": messages,
        "extracted": extracted,
        "last_trip_id": last_trip_id,
        "last_plan_version": last_plan_version,
        "last_plan_summary": last_plan_summary,
        "plan": plan,
        "context_ledger_summary": _context_ledger_summary(context.get("context_ledger") or {}),
        "context_pack_preview": context_pack_preview,
        "suggested_next_action": _suggested_next_action(active_plan, extracted, messages),
    }


def list_recent_session_resumes(db: DBSession, limit: int = 20) -> list[dict]:
    sessions = db.query(Session).filter(Session.status == "active").all()
    context_ids = {
        row.session_id
        for row in db.query(SessionContext.session_id).all()
    }
    ids = {session.session_id for session in sessions} | context_ids
    payloads = []
    for session_id in ids:
        payload = build_session_resume(db, session_id)
        if payload and payload.get("can_resume"):
            payloads.append(payload)
    payloads.sort(
        key=lambda item: (
            item.get("updated_at") or "",
            len(item.get("messages") or []),
        ),
        reverse=True,
    )
    return payloads[:limit]


def summarize_plan_data(plan_data: dict) -> dict:
    days = plan_data.get("days") or []
    total_cost = 0
    activities = 0
    for day in days:
        for seg in day.get("segments") or []:
            cost = seg.get("estimated_cost") or {}
            if isinstance(cost, dict):
                total_cost += cost.get("amount") or 0
            if seg.get("type") == "activity":
                activities += 1
    return {"days": len(days), "total_cost": total_cost, "activities": activities}


def _trip_view_source(trip, extracted: dict) -> SimpleNamespace:
    return SimpleNamespace(
        origin=extracted.get("origin") or getattr(trip, "origin", "") or "",
        destination=getattr(trip, "destination", None) or extracted.get("destination") or "",
        days=getattr(trip, "days", None) or extracted.get("days") or 0,
        budget=getattr(trip, "budget", None) or extracted.get("budget") or 0,
    )


def _clean_messages(raw_messages: list[Any]) -> list[dict]:
    cleaned = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        msg = {"role": role, "content": content}
        if item.get("type") in {"question", "plan", "error"}:
            msg["type"] = item["type"]
        cleaned.append(msg)
    return cleaned[-50:]


def _session_title(session: Session | None, extracted: dict, active_plan: PlanVersion | None) -> str:
    if session and session.title:
        return session.title
    if extracted.get("destination"):
        return str(extracted["destination"])
    if active_plan and active_plan.plan_data:
        days = active_plan.plan_data.get("days") or []
        if days:
            return str(days[0].get("theme") or "Continue previous session")
    return "Continue previous session"


def _suggested_next_action(active_plan: PlanVersion | None, extracted: dict, messages: list[dict]) -> str:
    if active_plan:
        return "view_trip"
    if extracted or messages:
        return "continue_chat"
    return "start_new"


def _latest_updated_at(session: Session | None, context_rec: SessionContext | None) -> str | None:
    values = [
        value
        for value in (
            getattr(session, "updated_at", None),
            getattr(context_rec, "updated_at", None),
        )
        if isinstance(value, datetime)
    ]
    if not values:
        return None
    return max(values).isoformat()


def _last_message_preview(messages: list[dict]) -> str:
    for msg in reversed(messages):
        content = (msg.get("content") or "").strip()
        if content:
            return content[:80]
    return ""


def _context_ledger_summary(ledger: dict) -> dict:
    active = ledger.get("active_constraints") or {}
    refs = ledger.get("source_refs") or {}
    return {
        "has_initial_constraints": bool(ledger.get("initial_constraints")),
        "active_constraint_keys": sorted(active.keys()),
        "override_count": len(ledger.get("overrides") or []),
        "revision_note_count": len(ledger.get("revision_notes") or []),
        "initial_trace_id": refs.get("initial_trace_id"),
    }
