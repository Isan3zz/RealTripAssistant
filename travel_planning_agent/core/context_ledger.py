"""Persistent context ledger and compact context-pack assembly."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


LEDGER_KEY = "context_ledger"
SCHEMA_VERSION = 1


def ensure_context_ledger(context: dict) -> dict:
    ledger = context.setdefault(
        LEDGER_KEY,
        {
            "schema_version": SCHEMA_VERSION,
            "initial_constraints": None,
            "active_constraints": {},
            "overrides": [],
            "revision_notes": [],
            "source_refs": {},
        },
    )
    ledger.setdefault("schema_version", SCHEMA_VERSION)
    ledger.setdefault("initial_constraints", None)
    ledger.setdefault("active_constraints", {})
    ledger.setdefault("overrides", [])
    ledger.setdefault("revision_notes", [])
    ledger.setdefault("source_refs", {})
    return ledger


def record_initial_constraints(
    context: dict,
    constraints: Any,
    source_message: str | None,
    trace_id: str | None,
) -> None:
    ledger = ensure_context_ledger(context)
    if ledger.get("initial_constraints"):
        return
    ledger["initial_constraints"] = _constraints_to_dict(constraints)
    ledger["source_refs"]["initial_trace_id"] = trace_id
    ledger["source_refs"]["initial_message"] = source_message
    ledger["source_refs"]["initial_recorded_at"] = _now_iso()


def record_active_constraints(
    context: dict,
    constraints: Any,
    source_message: str | None,
    trace_id: str | None,
) -> None:
    ledger = ensure_context_ledger(context)
    new_constraints = _constraints_to_dict(constraints)
    old_constraints = dict(ledger.get("active_constraints") or {})
    overrides = []
    for key, value in new_constraints.items():
        if key in old_constraints and old_constraints[key] != value:
            overrides.append(
                {
                    "field": key,
                    "old_value": old_constraints[key],
                    "new_value": value,
                    "source_message": source_message,
                    "trace_id": trace_id,
                    "recorded_at": _now_iso(),
                }
            )
    ledger["active_constraints"] = new_constraints
    ledger["source_refs"]["active_trace_id"] = trace_id
    ledger["source_refs"]["active_message"] = source_message
    ledger["source_refs"]["active_recorded_at"] = _now_iso()
    if overrides:
        ledger["overrides"] = (ledger.get("overrides") or []) + overrides
        del ledger["overrides"][:-20]


def record_revision_note(
    context: dict,
    message: str,
    trace_id: str | None,
    trip_id: str | None,
    plan_version: int | None,
) -> None:
    ledger = ensure_context_ledger(context)
    notes = ledger.setdefault("revision_notes", [])
    notes.append(
        {
            "message": message,
            "trace_id": trace_id,
            "trip_id": trip_id,
            "plan_version": plan_version,
            "recorded_at": _now_iso(),
        }
    )
    del notes[:-10]


def build_context_pack(
    context: dict,
    current_message: str,
    active_plan: dict | None = None,
    purpose: str = "chat",
    recent_message_limit: int = 6,
) -> dict:
    ledger = ensure_context_ledger(context)
    recent_messages, omitted_messages = _compact_recent_messages(
        context.get("messages") or [],
        limit=recent_message_limit,
    )
    trace_ids = list(context.get("trace_ids") or [])
    evidence_refs = _compact_evidence_refs(context.get("evidence") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": purpose,
        "current_message": current_message,
        "initial_constraints": deepcopy(ledger.get("initial_constraints")),
        "active_constraints": deepcopy(ledger.get("active_constraints") or {}),
        "overrides": deepcopy((ledger.get("overrides") or [])[-20:]),
        "revision_notes": deepcopy((ledger.get("revision_notes") or [])[-10:]),
        "full_plan_compact": compact_plan_for_context(active_plan) if active_plan else None,
        "recent_messages": recent_messages,
        "trace_refs": trace_ids[-10:],
        "evidence_refs": evidence_refs,
        "omitted": {
            "messages": omitted_messages,
            "trace_ids": max(0, len(trace_ids) - 10),
            "raw_trace_events": True,
            "raw_evidence_payloads": True,
        },
    }


def compact_plan_for_context(plan_data: dict) -> dict:
    days = []
    total_cost = 0
    segment_count = 0
    for day in plan_data.get("days") or []:
        compact_segments = []
        for seg in day.get("segments") or []:
            cost = _normalize_cost(seg.get("estimated_cost"))
            if cost:
                total_cost += cost.get("amount") or 0
            segment_count += 1
            compact_segments.append(
                {
                    "segment_id": seg.get("segment_id"),
                    "type": seg.get("type"),
                    "title": seg.get("title"),
                    "start_time": seg.get("start_time"),
                    "end_time": seg.get("end_time"),
                    "estimated_cost": cost,
                    "note": seg.get("note"),
                    "tags": list(seg.get("tags") or []),
                }
            )
        days.append(
            {
                "day_number": day.get("day_number"),
                "theme": day.get("theme"),
                "day_note": day.get("day_note"),
                "segments": compact_segments,
            }
        )
    return {
        "plan_id": plan_data.get("plan_id"),
        "version": plan_data.get("version"),
        "profile": plan_data.get("profile"),
        "days": days,
        "totals": {
            "days": len(days),
            "segments": segment_count,
            "estimated_cost": total_cost,
        },
    }


def _constraints_to_dict(constraints: Any) -> dict:
    if constraints is None:
        return {}
    if isinstance(constraints, dict):
        return _jsonable_dict(constraints)
    data = {}
    for key in (
        "origin",
        "destination",
        "start_date",
        "days",
        "budget",
        "pace",
        "transport_mode",
        "preferences_detail",
        "interests",
    ):
        if hasattr(constraints, key):
            value = getattr(constraints, key)
            if value is not None:
                data[key] = _jsonable_value(value)
    if hasattr(constraints, "travelers"):
        data["travelers"] = [
            {
                "age_group": getattr(item, "age_group", None),
                "note": getattr(item, "note", None),
            }
            for item in (getattr(constraints, "travelers") or [])
        ]
    return _jsonable_dict(data)


def _jsonable_dict(data: dict) -> dict:
    return {key: _jsonable_value(value) for key, value in data.items() if value is not None}


def _jsonable_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, list):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, dict):
        return _jsonable_dict(value)
    return value


def _compact_recent_messages(messages: list[Any], limit: int) -> tuple[list[dict], int]:
    cleaned = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        msg_type = item.get("type")
        if msg_type == "plan":
            content = "[plan_result omitted; see full_plan_compact]"
        cleaned.append({"role": role, "content": content, "type": msg_type})
    omitted = max(0, len(cleaned) - limit)
    return cleaned[-limit:], omitted


def _compact_evidence_refs(evidence: list[Any]) -> list[dict]:
    refs = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "evidence_id": item.get("evidence_id"),
                "claim": item.get("claim"),
            }
        )
    return refs[-20:]


def _normalize_cost(value: Any) -> dict | None:
    if isinstance(value, dict):
        amount = value.get("amount")
        currency = value.get("currency") or "CNY"
        return {"amount": amount, "currency": currency} if amount is not None else None
    if isinstance(value, (int, float)):
        return {"amount": value, "currency": "CNY"}
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
