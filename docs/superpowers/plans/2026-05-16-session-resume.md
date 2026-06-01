# Session Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users reopen the app and continue the last chat session, including prior messages, extracted travel constraints, and the most recent trip/plan reference.

**Architecture:** Use the existing `SessionContext.context_data` JSON as the source of truth for conversation recovery, and add a narrow resume API that shapes this JSON for the frontend. The chat API will persist both user and assistant messages and keep session metadata fresh; the frontend will store the current `session_id` in `localStorage` and call the resume API on load.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite JSON columns, Vue 3, Element Plus, localStorage, pytest.

---

## Scope

This plan implements session-level resume only. It does not resume a half-finished planning thread pool or continue from internal `research/draft/verify` pipeline checkpoints. A resumed session can continue chatting, apply quick revisions to the last trip, or view the most recent completed plan.

## File Structure

- Create `travel_planning_agent/core/session_resume.py`
  - Builds a frontend-safe resume payload from `Session`, `SessionContext`, `Trip`, and `PlanVersion`.
  - Keeps resume shaping out of API route files.
- Modify `travel_planning_agent/api/sessions.py`
  - Adds `GET /api/sessions/{session_id}/resume`.
  - Adds response models for recovered messages and session state.
- Modify `travel_planning_agent/api/chat.py`
  - Persists assistant replies into `SessionContext.context_data["messages"]`.
  - Ensures chat-created sessions have a `sessions` table row and updated title/status.
  - Records enough state for resume after question responses and plan responses.
- Modify `frontend/src/api/index.ts`
  - Adds `resumeSession(sessionId)`.
- Modify `frontend/src/views/TripList.vue`
  - Reads/writes the current session id from localStorage.
  - Calls resume on mount.
  - Restores message history and last plan message when available.
  - Adds a small “start new chat” action that clears localStorage/session state.
- Create `tests/test_session_resume.py`
  - Covers incomplete chat resume, completed plan resume, stale session handling, and chat message persistence.

## Data Contract

`GET /api/sessions/{session_id}/resume` returns:

```json
{
  "session_id": "sess_abc",
  "can_resume": true,
  "title": "南京",
  "status": "active",
  "messages": [
    {"role": "user", "content": "明天杭州去南京两天预算2000"},
    {"role": "assistant", "content": "已了解：...", "type": "question"}
  ],
  "extracted": {
    "destination": "南京",
    "start_date": "2026-05-17",
    "days": 2,
    "origin": "杭州",
    "budget": 2000
  },
  "last_trip_id": "trip_xxx",
  "last_plan_version": 1,
  "last_plan_summary": {
    "days": 2,
    "total_cost": 1849,
    "activities": 4
  },
  "suggested_next_action": "continue_chat"
}
```

Rules:
- If `session_id` exists in `session_contexts` but not `sessions`, return a valid resume payload with `title` from extracted destination or `"继续上次会话"`.
- If neither context nor session exists, return HTTP 404 so the frontend can clear stale localStorage.
- `messages` must only include `role`, `content`, and optional `type`; ignore unexpected keys.
- `suggested_next_action` is:
  - `"view_trip"` when `last_trip_id` exists and there is an active plan.
  - `"continue_chat"` when there are extracted fields or messages.
  - `"start_new"` only for an empty existing session.

---

### Task 1: Add Backend Resume Service Tests

**Files:**
- Create: `tests/test_session_resume.py`
- Later create: `travel_planning_agent/core/session_resume.py`

- [ ] **Step 1: Write failing tests for resume payload shaping**

Create `tests/test_session_resume.py` with:

```python
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from travel_planning_agent.api.app import app
from travel_planning_agent.db.models import PlanVersion, Session, SessionContext, Trip, User
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
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_resume_session_from_context_only(client, db_session):
    db_session.add(
        SessionContext(
            session_id="sess_resume_context",
            context_data={
                "extracted": {
                    "destination": "南京",
                    "start_date": "2026-05-17",
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                },
                "messages": [
                    {"role": "user", "content": "明天杭州去南京两天预算2000"},
                    {"role": "assistant", "content": "请问你更偏向哪种旅行方式？", "type": "question"},
                ],
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_resume_context/resume")

    assert res.status_code == 200
    body = res.json()
    assert body["can_resume"] is True
    assert body["session_id"] == "sess_resume_context"
    assert body["title"] == "南京"
    assert body["extracted"]["destination"] == "南京"
    assert body["messages"][-1]["type"] == "question"
    assert body["suggested_next_action"] == "continue_chat"


def test_resume_session_with_last_active_plan(client, db_session):
    user = User(email="resume@example.com", password_hash="", display_name="Resume")
    db_session.add(user)
    db_session.flush()
    session = Session(session_id="sess_resume_plan", user_id=user.user_id, title="南京")
    db_session.add(session)
    trip = Trip(
        trip_id="trip_resume_plan",
        session_id=session.session_id,
        user_id=user.user_id,
        destination="南京",
        start_date=date(2026, 5, 17),
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
            version=1,
            is_active=True,
            plan_data={
                "days": [
                    {"day_number": 1, "segments": [{"type": "activity", "estimated_cost": {"amount": 80}}]},
                    {"day_number": 2, "segments": [{"type": "meal", "estimated_cost": {"amount": 100}}]},
                ]
            },
            verification={"overall_pass": True},
        )
    )
    db_session.add(
        SessionContext(
            session_id=session.session_id,
            context_data={
                "last_trip_id": trip.trip_id,
                "last_plan_version": 1,
                "messages": [{"role": "assistant", "content": "✅ 行程规划完成！", "type": "plan"}],
            },
        )
    )
    db_session.commit()

    res = client.get("/api/sessions/sess_resume_plan/resume")

    assert res.status_code == 200
    body = res.json()
    assert body["last_trip_id"] == "trip_resume_plan"
    assert body["last_plan_version"] == 1
    assert body["last_plan_summary"] == {"days": 2, "total_cost": 180, "activities": 1}
    assert body["suggested_next_action"] == "view_trip"


def test_resume_missing_session_returns_404(client):
    res = client.get("/api/sessions/not_found/resume")

    assert res.status_code == 404
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_session_resume.py -q --basetemp .tmp_pytest_run\pytest-session-resume
```

Expected: fail with 404 for `/api/sessions/{session_id}/resume`.

### Task 2: Implement Resume Payload Builder

**Files:**
- Create: `travel_planning_agent/core/session_resume.py`
- Test: `tests/test_session_resume.py`

- [ ] **Step 1: Add the resume service**

Create `travel_planning_agent/core/session_resume.py`:

```python
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.db.models import PlanVersion, Session, SessionContext, Trip


def build_session_resume(db: DBSession, session_id: str) -> dict | None:
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

    title = _session_title(session, extracted, active_plan)
    suggested_next_action = _suggested_next_action(active_plan, extracted, messages)

    return {
        "session_id": session_id,
        "can_resume": bool(messages or extracted or last_trip_id),
        "title": title,
        "status": session.status if session else "active",
        "messages": messages,
        "extracted": extracted,
        "last_trip_id": last_trip_id,
        "last_plan_version": last_plan_version,
        "last_plan_summary": last_plan_summary,
        "suggested_next_action": suggested_next_action,
    }


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
            return str(days[0].get("theme") or "继续上次会话")
    return "继续上次会话"


def _suggested_next_action(active_plan: PlanVersion | None, extracted: dict, messages: list[dict]) -> str:
    if active_plan:
        return "view_trip"
    if extracted or messages:
        return "continue_chat"
    return "start_new"
```

- [ ] **Step 2: Run focused service tests through the API**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py -q --basetemp .tmp_pytest_run\pytest-session-resume
```

Expected: still fail because the API endpoint has not been added.

### Task 3: Add Resume API Endpoint

**Files:**
- Modify: `travel_planning_agent/api/sessions.py`
- Test: `tests/test_session_resume.py`

- [ ] **Step 1: Add response models and endpoint**

Modify `travel_planning_agent/api/sessions.py`:

```python
from typing import Optional
```

Add models after `SessionResponse`:

```python
class ResumeMessage(BaseModel):
    role: str
    content: str
    type: Optional[str] = None


class SessionResumeResponse(BaseModel):
    session_id: str
    can_resume: bool
    title: str
    status: str
    messages: list[ResumeMessage] = []
    extracted: dict = {}
    last_trip_id: Optional[str] = None
    last_plan_version: Optional[int] = None
    last_plan_summary: Optional[dict] = None
    suggested_next_action: str
```

Add before `delete_session`:

```python
@router.get("/{session_id}/resume", response_model=SessionResumeResponse)
def resume_session(session_id: str, db: DBSession = Depends(get_db)):
    from travel_planning_agent.core.session_resume import build_session_resume

    payload = build_session_resume(db, session_id)
    if not payload:
        raise HTTPException(404, "会话不存在")
    return SessionResumeResponse(**payload)
```

- [ ] **Step 2: Run resume API tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py -q --basetemp .tmp_pytest_run\pytest-session-resume
```

Expected: all tests in `tests/test_session_resume.py` pass.

### Task 4: Persist Full Chat History for Resume

**Files:**
- Modify: `tests/test_session_resume.py`
- Modify: `travel_planning_agent/api/chat.py`

- [ ] **Step 1: Add failing test for chat message persistence**

Append to `tests/test_session_resume.py`:

```python
from travel_planning_agent.types import AgentResponse


def test_chat_persists_user_and_assistant_messages_for_resume(client, db_session, monkeypatch):
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
        )

    monkeypatch.setattr("travel_planning_agent.agent.intake.IntakeAgent.handle", fake_handle)

    res = client.post("/api/chat", json={"session_id": "sess_chat_history", "message": "杭州到南京两天预算2000"})

    assert res.status_code == 200
    resume = client.get("/api/sessions/sess_chat_history/resume").json()
    assert resume["messages"] == [
        {"role": "user", "content": "杭州到南京两天预算2000", "type": None},
        {
            "role": "assistant",
            "content": res.json()["content"],
            "type": "question",
        },
    ]
    assert resume["suggested_next_action"] == "continue_chat"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_chat_persists_user_and_assistant_messages_for_resume -q --basetemp .tmp_pytest_run\pytest-chat-history
```

Expected: fail because chat currently only stores user messages in some branches.

- [ ] **Step 3: Add chat history helpers**

In `travel_planning_agent/api/chat.py`, add helper functions near `_save_session_context`:

```python
def _append_context_message(context: dict, role: str, content: str, msg_type: str | None = None) -> None:
    if not content:
        return
    msg = {"role": role, "content": content}
    if msg_type:
        msg["type"] = msg_type
    messages = context.setdefault("messages", [])
    messages.append(msg)
    del messages[:-50]


def _touch_session(db: DBSession, session_id: str, title: str | None = None) -> None:
    from travel_planning_agent.db.models import User, Session

    session = db.query(Session).filter(Session.session_id == session_id).first()
    if session:
        if title and (not session.title or session.title == "新建行程"):
            session.title = title
        db.commit()
        return

    user = db.query(User).filter(User.email == "default@realtrip.ai").first()
    if not user:
        user = User(email="default@realtrip.ai", password_hash="", display_name="默认用户")
        db.add(user)
        db.commit()
        db.refresh(user)
    db.add(Session(session_id=session_id, user_id=user.user_id, title=title or "继续上次会话"))
    db.commit()
```

- [ ] **Step 4: Use helpers in chat branches**

In `chat()`, after loading context and extracted:

```python
_touch_session(db, session_id, extracted.get("destination"))
```

In the incomplete branch, replace the current user-only append:

```python
_append_context_message(context, "user", req.message)
```

After `content` is built and before `_save_session_context` or immediately before return, add:

```python
_append_context_message(context, "assistant", content, "question")
context["last_response"] = {"type": "question", "content": content}
_save_session_context(db, session_id, context)
```

In the plan-result branch, before saving context:

```python
_append_context_message(context, "user", req.message)
```

After `content` is built:

```python
_append_context_message(context, "assistant", content, "plan")
context["last_response"] = {"type": "plan", "content": content, "trip_id": state.trip_id}
_save_session_context(db, session_id, context)
```

In the revision branch, before returning revised:

```python
_append_context_message(context, "assistant", revised.content, "plan")
context["last_response"] = {"type": "plan", "content": revised.content, "trip_id": revised.trip_id}
```

- [ ] **Step 5: Run chat persistence test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_chat_persists_user_and_assistant_messages_for_resume -q --basetemp .tmp_pytest_run\pytest-chat-history
```

Expected: pass.

### Task 5: Add Frontend Resume API and Local Session Persistence

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/TripList.vue`

- [ ] **Step 1: Add API wrapper**

In `frontend/src/api/index.ts`, add:

```ts
export const resumeSession = (sessionId: string) =>
  api.get(`/sessions/${sessionId}/resume`)
```

- [ ] **Step 2: Persist session id after chat response**

In `frontend/src/views/TripList.vue`, add near script constants:

```ts
const SESSION_STORAGE_KEY = 'realtrip.currentSessionId'
const resumeNotice = ref('')
```

Replace:

```ts
sessionId = data.session_id || sessionId
```

with:

```ts
sessionId = data.session_id || sessionId
if (sessionId) {
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
}
```

- [ ] **Step 3: Restore session on mount**

In the existing `onMounted`, after the health check block, add:

```ts
const savedSessionId = localStorage.getItem(SESSION_STORAGE_KEY)
if (savedSessionId) {
  await restoreSession(savedSessionId)
}
```

Add this function:

```ts
async function restoreSession(savedSessionId: string) {
  try {
    const res = await fetch(`/api/sessions/${savedSessionId}/resume`)
    if (res.status === 404) {
      localStorage.removeItem(SESSION_STORAGE_KEY)
      return
    }
    if (!res.ok) return
    const data = await res.json()
    if (!data.can_resume) return
    sessionId = data.session_id
    if (Array.isArray(data.messages) && data.messages.length) {
      messages.value = data.messages.map((msg: any) => ({
        role: msg.role,
        content: msg.content,
        type: msg.type === 'plan' ? 'plan' : undefined,
      }))
      resumeNotice.value = '已恢复上次会话'
      scrollToBottom()
    }
  } catch {
    return
  }
}
```

- [ ] **Step 4: Add start-new-session action**

Add a compact button in the topbar beside health status:

```vue
<el-button size="small" plain @click="startNewSession">新会话</el-button>
```

Add the function:

```ts
function startNewSession() {
  sessionId = null
  localStorage.removeItem(SESSION_STORAGE_KEY)
  resumeNotice.value = ''
  messages.value = [
    { role: 'assistant', content: '想从哪里出发，去哪里，玩几天？把预算、同行人和偏好也告诉我。' },
  ]
}
```

If a resume notice is displayed in the template, use a small inline `el-tag`:

```vue
<el-tag v-if="resumeNotice" size="small" effect="plain">{{ resumeNotice }}</el-tag>
```

- [ ] **Step 5: Build frontend**

Run:

```powershell
cd frontend
npm run build
```

Expected: Vite build exits with code 0. Existing large chunk warnings are acceptable.

### Task 6: Add Trace Event for Resume

**Files:**
- Modify: `travel_planning_agent/api/sessions.py`
- Test: `tests/test_session_resume.py`

- [ ] **Step 1: Add trace assertion**

Append to `tests/test_session_resume.py`:

```python
import json

from travel_planning_agent.config import settings


def test_resume_session_writes_trace_event(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    db_session.add(SessionContext(session_id="sess_trace_resume", context_data={"messages": [{"role": "user", "content": "继续"}]}))
    db_session.commit()

    res = client.get("/api/sessions/sess_trace_resume/resume")

    assert res.status_code == 200
    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event = trace["events"][0]
    assert event["event_type"] == "session_resumed"
    assert event["stage"] == "session"
    assert event["session_id"] == "sess_trace_resume"
```

- [ ] **Step 2: Run trace test and verify failure**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_resume_session_writes_trace_event -q --basetemp .tmp_pytest_run\pytest-resume-trace
```

Expected: fail because the resume endpoint does not write trace yet.

- [ ] **Step 3: Record resume trace**

In `travel_planning_agent/api/sessions.py`, inside `resume_session()` after payload is built:

```python
from travel_planning_agent.core.tracing import create_trace_id, record_trace_event, set_trace_context, clear_trace_context

trace_id = create_trace_id()
set_trace_context(trace_id, session_id=session_id)
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
clear_trace_context()
```

- [ ] **Step 4: Run trace test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_session_resume.py::test_resume_session_writes_trace_event -q --basetemp .tmp_pytest_run\pytest-resume-trace
```

Expected: pass.

### Task 7: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted backend tests**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_session_resume.py tests\test_chat_api.py -q --basetemp .tmp_pytest_run\pytest-session-targeted
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_run\pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits with code 0. Existing chunk-size warnings are acceptable.

- [ ] **Step 4: Restart backend**

Run:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 1 }
Start-Process -FilePath 'D:\Python_Project\RealTripAssistant\venv\Scripts\python.exe' -ArgumentList '-m','travel_planning_agent.main' -WorkingDirectory 'D:\Python_Project\RealTripAssistant' -WindowStyle Hidden
Start-Sleep -Seconds 3
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 10 | ConvertTo-Json -Depth 4
```

Expected: health response contains `"status": "ok"`.

- [ ] **Step 5: Clean temporary test directory**

Run:

```powershell
Remove-Item -LiteralPath 'D:\Python_Project\RealTripAssistant\.tmp_pytest_run' -Recurse -Force -ErrorAction SilentlyContinue
```

Expected: command exits with code 0.

## Self-Review

- Spec coverage: The plan covers session id persistence, message recovery, extracted constraint recovery, recent trip/plan recovery, stale session behavior, and trace visibility.
- Placeholder scan: No placeholder implementation steps remain; each code task includes concrete snippets and commands.
- Type consistency: `SessionResumeResponse`, `ResumeMessage`, `build_session_resume()`, and frontend `restoreSession()` use the same field names: `messages`, `extracted`, `last_trip_id`, `last_plan_version`, `last_plan_summary`, and `suggested_next_action`.
