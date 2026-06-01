# Context Ledger Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic backend context ledger and context-pack assembler so long sessions can be resumed and shortened without losing the current user instruction, the original structured travel request, or the full active itinerary.

**Architecture:** Store a compact `context_ledger` inside `SessionContext.context_data` and assemble model-facing context from prioritized sections instead of raw chat history. The context pack always keeps the current user message, initial structured constraints, active constraints/overrides, and a compact full active plan; recent chat and trace/evidence references are included only as bounded supporting context.

**Tech Stack:** FastAPI, SQLAlchemy JSON columns, pytest, existing `SessionContext`, existing `PlanVersion.plan_data`, existing JSON trace files.

---

## Context Priority Rules

The model-facing context pack must follow this order:

1. **P0 current message:** The newest user instruction is included exactly and never summarized.
2. **P1 initial structured request:** The first complete extracted travel constraints are preserved as `initial_constraints` and never overwritten.
3. **P2 active constraints and overrides:** Latest structured constraints, explicit changes, and revision notes are included after the initial request.
4. **P3 full compact active plan:** The current active itinerary is included as structured JSON with all days and all segments, but without verbose display text, raw evidence payloads, or trace event bodies.
5. **P4 recent short chat:** Include only the last few user/assistant messages, replacing large plan-result messages with a pointer to `full_plan_compact`.
6. **P5 trace and evidence references:** Include IDs and short claims only by default; raw tool inputs/outputs remain in trace JSON files and are loaded only when a later feature explicitly needs drill-down.

This implements the user's preference: the current instruction, the first extracted structured instruction, and the complete plan are mandatory.

## File Structure

- Create: `travel_planning_agent/core/context_ledger.py`
  - Owns the JSON schema for `context_ledger`.
  - Records initial constraints once, active constraints repeatedly, explicit overrides, and revision notes.
  - Builds a compact context pack with deterministic priority and omission metadata.
- Modify: `travel_planning_agent/api/chat.py`
  - Updates the ledger during partial intake, complete intake, plan creation, and revision.
  - Keeps existing `messages`, `extracted`, `trace_ids`, and `last_trip_id` behavior.
- Modify: `travel_planning_agent/core/session_resume.py`
  - Exposes lightweight ledger metadata in resume payloads for backend debugging and future UI diagnostics.
- Modify: `travel_planning_agent/api/sessions.py`
  - Adds optional `context_ledger` summary fields to `SessionResumeResponse`.
- Create: `tests/test_context_ledger.py`
  - Unit tests for ledger recording, active constraint updates, compact full plan retention, recent-message trimming, and trace/evidence omission.
- Modify: `tests/test_session_resume.py`
  - API tests that prove `/api/chat` persists the ledger and `/api/sessions/{id}/resume` returns ledger metadata.

---

### Task 1: Add Context Ledger Unit Tests

**Files:**
- Create: `tests/test_context_ledger.py`

- [ ] **Step 1: Write failing tests for ledger semantics**

Create `tests/test_context_ledger.py` with this content:

```python
from travel_planning_agent.core.context_ledger import (
    build_context_pack,
    compact_plan_for_context,
    record_active_constraints,
    record_initial_constraints,
    record_revision_note,
)


def test_records_initial_constraints_once_and_active_constraints_updates():
    context = {}
    first = {
        "origin": "杭州",
        "destination": "南京",
        "start_date": "2026-05-18",
        "days": 2,
        "budget": 2000,
        "transport_mode": "train",
        "interests": ["玄武湖"],
    }
    updated = dict(first, budget=1500, pace="slow")

    record_initial_constraints(context, first, "明天杭州去南京两天", "trace_first")
    record_active_constraints(context, first, "明天杭州去南京两天", "trace_first")
    record_initial_constraints(context, updated, "预算降到1500", "trace_second")
    record_active_constraints(context, updated, "预算降到1500", "trace_second")

    ledger = context["context_ledger"]
    assert ledger["schema_version"] == 1
    assert ledger["initial_constraints"]["budget"] == 2000
    assert ledger["initial_constraints"]["destination"] == "南京"
    assert ledger["active_constraints"]["budget"] == 1500
    assert ledger["active_constraints"]["pace"] == "slow"
    assert ledger["source_refs"]["initial_trace_id"] == "trace_first"
    assert ledger["source_refs"]["active_trace_id"] == "trace_second"


def test_context_pack_keeps_current_message_initial_constraints_and_full_compact_plan():
    context = {}
    initial = {
        "origin": "杭州",
        "destination": "南京",
        "start_date": "2026-05-18",
        "days": 2,
        "budget": 2000,
        "interests": ["玄武湖"],
    }
    plan_data = {
        "profile": "slow",
        "days": [
            {
                "day_number": 1,
                "theme": "玄武湖与城市初见",
                "segments": [
                    {
                        "segment_id": "seg_train",
                        "type": "transport",
                        "title": "杭州东到南京南",
                        "start_time": "08:00",
                        "end_time": "09:30",
                        "estimated_cost": {"amount": 200, "currency": "CNY"},
                        "note": "高铁",
                    },
                    {
                        "segment_id": "seg_lake",
                        "type": "activity",
                        "title": "玄武湖散步",
                        "start_time": "10:20",
                        "end_time": "12:00",
                        "estimated_cost": {"amount": 0, "currency": "CNY"},
                    },
                ],
            },
            {
                "day_number": 2,
                "theme": "老城慢游",
                "segments": [
                    {
                        "segment_id": "seg_museum",
                        "type": "activity",
                        "title": "南京博物院",
                        "start_time": "09:30",
                        "end_time": "11:30",
                    }
                ],
            },
        ],
    }
    context["messages"] = [
        {"role": "user", "content": "明天杭州去南京两天"},
        {"role": "assistant", "content": "✅ 行程规划完成！\n很长的展示文本", "type": "plan"},
    ]
    context["trace_ids"] = ["trace_first"]
    record_initial_constraints(context, initial, "明天杭州去南京两天", "trace_first")
    record_active_constraints(context, dict(initial, pace="slow"), "轻松一点", "trace_second")

    pack = build_context_pack(
        context,
        current_message="第二天太累了，轻松一点",
        active_plan=plan_data,
        purpose="revision",
    )

    assert pack["current_message"] == "第二天太累了，轻松一点"
    assert pack["initial_constraints"]["budget"] == 2000
    assert pack["active_constraints"]["pace"] == "slow"
    assert len(pack["full_plan_compact"]["days"]) == 2
    assert pack["full_plan_compact"]["days"][0]["segments"][0]["segment_id"] == "seg_train"
    assert pack["full_plan_compact"]["days"][0]["segments"][1]["title"] == "玄武湖散步"
    assert pack["full_plan_compact"]["totals"]["segments"] == 3
    assert pack["recent_messages"][-1]["content"] == "[plan_result omitted; see full_plan_compact]"


def test_context_pack_omits_raw_messages_trace_and_evidence_payloads_by_default():
    context = {
        "messages": [{"role": "user", "content": f"message {i}"} for i in range(20)],
        "trace_ids": [f"trace_{i}" for i in range(30)],
        "evidence": [
            {
                "evidence_id": "ev_1",
                "claim": "玄武湖免费开放",
                "payload": {"raw_tool_output": "large payload should not enter context"},
            }
        ],
    }

    pack = build_context_pack(context, current_message="继续优化", active_plan=None)

    assert [msg["content"] for msg in pack["recent_messages"]] == [f"message {i}" for i in range(14, 20)]
    assert pack["trace_refs"] == [f"trace_{i}" for i in range(20, 30)]
    assert pack["evidence_refs"] == [{"evidence_id": "ev_1", "claim": "玄武湖免费开放"}]
    assert "raw_tool_output" not in str(pack)
    assert pack["omitted"]["messages"] == 14
    assert pack["omitted"]["trace_ids"] == 20


def test_revision_notes_are_bounded_and_ordered():
    context = {}

    for i in range(15):
        record_revision_note(
            context,
            message=f"第{i}次修改",
            trace_id=f"trace_{i}",
            trip_id="trip_1",
            plan_version=i + 1,
        )

    notes = context["context_ledger"]["revision_notes"]
    assert len(notes) == 10
    assert notes[0]["message"] == "第5次修改"
    assert notes[-1]["trace_id"] == "trace_14"


def test_compact_plan_for_context_keeps_cost_shape_and_all_segments():
    plan_data = {
        "plan_id": "plan_1",
        "version": 3,
        "days": [
            {
                "day_number": 1,
                "theme": "第一天",
                "day_note": "小雨",
                "segments": [
                    {
                        "segment_id": "a",
                        "type": "meal",
                        "title": "早餐",
                        "start_time": "08:00",
                        "end_time": "08:30",
                        "estimated_cost": {"amount": 30, "currency": "CNY"},
                        "explanation": {"why": "verbose text should be omitted"},
                    }
                ],
            }
        ],
    }

    compact = compact_plan_for_context(plan_data)

    assert compact == {
        "plan_id": "plan_1",
        "version": 3,
        "profile": None,
        "days": [
            {
                "day_number": 1,
                "theme": "第一天",
                "day_note": "小雨",
                "segments": [
                    {
                        "segment_id": "a",
                        "type": "meal",
                        "title": "早餐",
                        "start_time": "08:00",
                        "end_time": "08:30",
                        "estimated_cost": {"amount": 30, "currency": "CNY"},
                        "note": None,
                        "tags": [],
                    }
                ],
            }
        ],
        "totals": {"days": 1, "segments": 1, "estimated_cost": 30},
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_context_ledger.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'travel_planning_agent.core.context_ledger'`.

---

### Task 2: Implement `context_ledger.py`

**Files:**
- Create: `travel_planning_agent/core/context_ledger.py`
- Test: `tests/test_context_ledger.py`

- [ ] **Step 1: Add the module implementation**

Create `travel_planning_agent/core/context_ledger.py`:

```python
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
```

- [ ] **Step 2: Run ledger tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_context_ledger.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add tests/test_context_ledger.py travel_planning_agent/core/context_ledger.py
git commit -m "feat: add persistent context ledger"
```

---

### Task 3: Persist Ledger From Chat Intake and Planning

**Files:**
- Modify: `travel_planning_agent/api/chat.py`
- Modify: `tests/test_session_resume.py`

- [ ] **Step 1: Add failing API test for incomplete intake draft ledger**

Append this test to `tests/test_session_resume.py`:

```python
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
```

- [ ] **Step 2: Add failing API test for complete intake initial ledger**

Append this test to `tests/test_session_resume.py`:

```python
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
```

- [ ] **Step 3: Run new API tests and verify failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_chat_persists_context_ledger_for_partial_intake tests\test_session_resume.py::test_chat_persists_initial_and_active_context_ledger_after_plan -q
```

Expected: FAIL because `context_ledger` is not written by `/api/chat`.

- [ ] **Step 4: Import ledger helpers in `api/chat.py`**

Add this import near the existing `core.tracing` import:

```python
from travel_planning_agent.core.context_ledger import (
    record_active_constraints,
    record_initial_constraints,
    record_revision_note,
)
```

- [ ] **Step 5: Record active draft constraints for incomplete intake**

Inside `if not data.get("complete"):` immediately after:

```python
new_extracted = data.get("extracted", {})
context["extracted"] = dict(new_extracted)
```

add:

```python
record_active_constraints(context, new_extracted, req.message, trace_id)
```

- [ ] **Step 6: Record initial and active constraints for complete intake**

Inside the complete branch, after:

```python
constraints = data.get("constraints")
```

and before `TripSpec.from_constraints(constraints)`, add:

```python
record_initial_constraints(context, constraints, req.message, trace_id)
record_active_constraints(context, constraints, req.message, trace_id)
```

- [ ] **Step 7: Record revision notes**

Inside `_try_apply_plan_revision`, after:

```python
context["last_plan_version"] = new_version
context.setdefault("extracted", {})["days"] = trip.days
```

add:

```python
from travel_planning_agent.core.tracing import get_trace_context

trace_context = get_trace_context()
record_revision_note(
    context,
    message=message,
    trace_id=trace_context.trace_id if trace_context else None,
    trip_id=trip_id,
    plan_version=new_version,
)
```

If `get_trace_context` does not exist in `core/tracing.py`, add a smaller fallback import-free helper instead:

```python
record_revision_note(
    context,
    message=message,
    trace_id=context.get("last_trace_id"),
    trip_id=trip_id,
    plan_version=new_version,
)
```

Use the fallback if the tracing module exposes only setters and recorders.

- [ ] **Step 8: Run targeted tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_context_ledger.py tests\test_session_resume.py::test_chat_persists_context_ledger_for_partial_intake tests\test_session_resume.py::test_chat_persists_initial_and_active_context_ledger_after_plan -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```powershell
git add travel_planning_agent/api/chat.py tests/test_session_resume.py
git commit -m "feat: persist context ledger from chat"
```

---

### Task 4: Expose Ledger Metadata in Session Resume

**Files:**
- Modify: `travel_planning_agent/core/session_resume.py`
- Modify: `travel_planning_agent/api/sessions.py`
- Modify: `tests/test_session_resume.py`

- [ ] **Step 1: Add failing resume test**

Append this test to `tests/test_session_resume.py`:

```python
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
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_resume_session_returns_context_ledger_summary -q
```

Expected: FAIL because `context_ledger_summary` is absent.

- [ ] **Step 3: Add summary builder in `session_resume.py`**

In `build_session_resume`, add this key to the returned dict:

```python
"context_ledger_summary": _context_ledger_summary(context.get("context_ledger") or {}),
```

Add this helper at the end of `travel_planning_agent/core/session_resume.py`:

```python
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
```

- [ ] **Step 4: Add response field in `api/sessions.py`**

In `SessionResumeResponse`, add:

```python
context_ledger_summary: dict = {}
```

- [ ] **Step 5: Run resume tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add travel_planning_agent/core/session_resume.py travel_planning_agent/api/sessions.py tests/test_session_resume.py
git commit -m "feat: expose context ledger resume summary"
```

---

### Task 5: Add Context Pack Builder Coverage for Active Plan From Database

**Files:**
- Modify: `travel_planning_agent/core/session_resume.py`
- Modify: `tests/test_session_resume.py`

- [ ] **Step 1: Add failing test for context-pack assembly from active plan**

Append this test to `tests/test_session_resume.py`:

```python
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
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_resume_context_pack_keeps_active_plan_compact -q
```

Expected: FAIL because `context_pack_preview` is absent.

- [ ] **Step 3: Build preview in `session_resume.py`**

Import:

```python
from travel_planning_agent.core.context_ledger import build_context_pack
```

In `build_session_resume`, after `active_plan` is loaded and before the returned dict, compute:

```python
context_pack_preview = build_context_pack(
    context,
    current_message="",
    active_plan=active_plan.plan_data if active_plan else None,
    purpose="resume_preview",
)
```

Add to returned dict:

```python
"context_pack_preview": context_pack_preview,
```

- [ ] **Step 4: Add response field in `api/sessions.py`**

In `SessionResumeResponse`, add:

```python
context_pack_preview: Optional[dict] = None
```

- [ ] **Step 5: Run session resume tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py -q
```

Expected: PASS.

- [ ] **Step 6: Decide whether preview is acceptable for API payload size**

Inspect one real response:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/sessions/recent?limit=1" | ConvertTo-Json -Depth 20
```

If the response is too large for the session list, keep `context_pack_preview` only on `/{session_id}/resume` by moving preview creation behind an optional `include_context_pack` argument in `build_session_resume`. The API should not send full compact plans in `/recent` unless the UI needs them.

- [ ] **Step 7: Commit**

Run:

```powershell
git add travel_planning_agent/core/session_resume.py travel_planning_agent/api/sessions.py tests/test_session_resume.py
git commit -m "feat: provide resumable context pack preview"
```

---

### Task 6: Verification and Regression Pass

**Files:**
- No source file changes unless verification exposes a bug.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_context_ledger.py tests\test_session_resume.py tests\test_chat_api.py tests\test_chat_revision.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run with temp paths inside the workspace:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_run\pytest
```

Expected: PASS.

- [ ] **Step 3: Clean temp test directory**

Run:

```powershell
Remove-Item -Recurse -Force .tmp_pytest_run
```

- [ ] **Step 4: Restart backend and smoke-test health**

Run:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 1 }
Start-Process -FilePath 'D:\Python_Project\RealTripAssistant\venv\Scripts\python.exe' -ArgumentList '-m','travel_planning_agent.main' -WorkingDirectory 'D:\Python_Project\RealTripAssistant' -WindowStyle Hidden
Start-Sleep -Seconds 3
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 10 | ConvertTo-Json -Depth 4
```

Expected: JSON contains healthy service status.

- [ ] **Step 5: Manual API smoke test**

Run:

```powershell
$body = @{
  session_id = "sess_context_smoke"
  message = "明天我从杭州去南京玩两天，坐高铁去吧，然后我想看玄武湖，预算2000"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType 'application/json; charset=utf-8' -Body $body | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/sessions/sess_context_smoke/resume | ConvertTo-Json -Depth 20
```

Expected:
- `/api/chat` returns a question or plan result.
- `/resume` includes `context_ledger_summary`.
- If a plan exists, `/resume` includes `context_pack_preview.full_plan_compact`.
- `context_pack_preview.current_message` may be empty for resume preview; future model calls pass the real current message.

- [ ] **Step 6: Final commit**

Run:

```powershell
git status --short
git add travel_planning_agent/core/context_ledger.py travel_planning_agent/api/chat.py travel_planning_agent/core/session_resume.py travel_planning_agent/api/sessions.py tests/test_context_ledger.py tests/test_session_resume.py
git commit -m "feat: assemble resumable context packs"
```

Skip this commit if all previous task commits already cover the final state.

---

## Self-Review

Spec coverage:
- Current user instruction is mandatory: Task 2 `build_context_pack(... current_message=...)`.
- Initial extracted structured instruction is mandatory and immutable: Task 2 `record_initial_constraints`, Task 3 complete intake integration.
- Full plan remains included: Task 2 `compact_plan_for_context`, Task 5 active `PlanVersion.plan_data` preview.
- Long raw context is reduced: Task 2 recent-message trimming and raw trace/evidence omission.
- Session recovery remains JSON-backed: all new state lives inside `SessionContext.context_data`.

Placeholder scan:
- The implementation plan contains no `TBD`, `TODO`, or unspecified test steps.
- Optional behavior in Task 5 has an explicit decision point and concrete fallback.

Type consistency:
- `context_ledger`, `context_ledger_summary`, and `context_pack_preview` names are consistent across tests, core modules, and response models.
- `estimated_cost` remains `{amount, currency}` in compact plans.
- Trace references remain `trace_ids`/`last_trace_id`, matching the existing session resume implementation.
