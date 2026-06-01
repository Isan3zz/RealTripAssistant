# Agent Complexity Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce unnecessary architectural complexity in the travel planning agent by splitting orchestration, runtime, and API responsibilities into smaller units without changing current user-facing behavior.

**Architecture:** Keep the current four-role model (`Supervisor`, `Researcher`, `Planner`, `Verifier`) and the deterministic-rule-plus-LLM design, but move large mixed-responsibility code out of `supervisor.py`, `planning_runtime.py`, and `api/chat.py` into focused helper and service modules. The refactor is staged so behavior stays stable after each slice.

**Tech Stack:** Python 3.11, pytest, FastAPI, SQLAlchemy, existing `PlanState` / `AgentRequest` / `AgentResponse` models, existing tracing and plan revision helpers.

---

## Refactor Boundaries

Keep these concepts:

- Deterministic rule engine in `travel_planning_agent/engine/rules.py`
- Four-agent mental model in `travel_planning_agent/agent/*`
- Revision / diff / persistence behavior already exposed to API callers

Reduce complexity in these hotspots:

- `travel_planning_agent/agent/supervisor.py`
- `travel_planning_agent/core/planning_runtime.py`
- `travel_planning_agent/api/chat.py`
- `travel_planning_agent/core/execution_plan.py` only after the first three slices are stable

Success criteria:

1. `SupervisorAgent` mainly routes and delegates instead of running the daily pipeline directly.
2. `PlanningRuntime` becomes a thin coordinator rather than a persistence-and-postprocessing god object.
3. `/api/chat` becomes a thin route that calls a service layer.
4. Existing tests for revision, runtime behavior, and chat routing still pass.
5. New tests pin module boundaries so future edits do not drift back toward monolith files.

## Planned File Structure

- Create: `travel_planning_agent/core/daily_pipeline.py`
  - Owns daily draft / research / refine / verify pipeline execution.
- Create: `travel_planning_agent/core/plan_run_service.py`
  - Owns one planning run from normalized constraints to final `PlanState`.
- Create: `travel_planning_agent/core/plan_persistence.py`
  - Owns trip creation, run record persistence, plan version persistence, evidence persistence.
- Create: `travel_planning_agent/core/chat_service.py`
  - Owns chat workflow, intake branching, revision branching, session-context updates.
- Create: `travel_planning_agent/core/chat_session_store.py`
  - Owns session context load/save/append helpers currently embedded in `api/chat.py`.
- Create: `travel_planning_agent/core/chat_questioning.py`
  - Owns follow-up question normalization and next-missing-field logic.
- Modify: `travel_planning_agent/agent/supervisor.py`
  - Keep routing and degrade logic; delegate pipeline work to `daily_pipeline.py`.
- Modify: `travel_planning_agent/core/planning_runtime.py`
  - Delegate run orchestration and persistence to services.
- Modify: `travel_planning_agent/api/chat.py`
  - Keep request/response models and route wiring; delegate flow to `ChatService`.
- Test: `tests/test_supervisor.py`
  - Add delegation-focused tests for the extracted daily pipeline.
- Test: `tests/test_product_runtime.py`
  - Add runtime service and persistence seam tests.
- Test: `tests/test_chat_api.py`
  - Keep current API behavior green after service extraction.
- Create: `tests/test_chat_service.py`
  - Add service-level workflow tests without HTTP transport.

---

### Task 1: Extract Daily Pipeline From `SupervisorAgent`

**Files:**
- Create: `travel_planning_agent/core/daily_pipeline.py`
- Modify: `travel_planning_agent/agent/supervisor.py`
- Modify: `tests/test_supervisor.py`

- [ ] **Step 1: Write the failing delegation test**

Add to `tests/test_supervisor.py`:

```python
from datetime import date

from travel_planning_agent.agent.supervisor import SupervisorAgent
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import Constraints, PlanState, Traveler


def test_supervisor_run_planning_loop_delegates_to_daily_pipeline(monkeypatch):
    calls = []

    def fake_run_daily_pipeline(self, state):
        calls.append(state.trip_id)
        state.status = state.status

    monkeypatch.setattr(
        "travel_planning_agent.core.daily_pipeline.DailyPipelineRunner.run",
        fake_run_daily_pipeline,
    )

    supervisor = SupervisorAgent(MockLLMClient(), {})
    state = PlanState(
        trip_id="trip_delegate",
        constraints=Constraints(
            destination="南京",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
        ),
    )

    supervisor._run_pipeline_loop(state)

    assert calls == ["trip_delegate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_supervisor.py::test_supervisor_run_planning_loop_delegates_to_daily_pipeline -v
```

Expected: FAIL because `travel_planning_agent.core.daily_pipeline` or `DailyPipelineRunner` does not exist yet.

- [ ] **Step 3: Add the minimal daily pipeline wrapper**

Create `travel_planning_agent/core/daily_pipeline.py`:

```python
from travel_planning_agent.types import PlanState


class DailyPipelineRunner:
    def __init__(self, supervisor):
        self.supervisor = supervisor

    def run(self, state: PlanState) -> None:
        self.supervisor._run_pipeline_loop_impl(state)
```

Update `travel_planning_agent/agent/supervisor.py` so `_run_pipeline_loop()` becomes a delegating wrapper and current body moves to `_run_pipeline_loop_impl()`:

```python
from travel_planning_agent.core.daily_pipeline import DailyPipelineRunner


def _run_pipeline_loop(self, state: PlanState):
    runner = DailyPipelineRunner(self)
    runner.run(state)


def _run_pipeline_loop_impl(self, state: PlanState):
    # move the current pipeline body here unchanged first
    ...
```

- [ ] **Step 4: Run the targeted supervisor tests**

Run:

```bash
pytest tests/test_supervisor.py -v
```

Expected: PASS for existing supervisor tests plus the new delegation seam test.

- [ ] **Step 5: Move pipeline-only helpers out of `SupervisorAgent`**

Move daily-pipeline-specific helpers from `travel_planning_agent/agent/supervisor.py` into `travel_planning_agent/core/daily_pipeline.py` first, leaving route/degrade helpers in `SupervisorAgent`:

- `_prefetch_shared_data`
- `_state_snapshot`
- `_submit_module_tasks`
- draft / research / refine / verify pipeline submission helpers

Keep these in `SupervisorAgent`:

- `dispatch_with_degrade`
- `run_planning_loop`
- request-level state assembly for agent delegation

Use this target class shape:

```python
class DailyPipelineRunner:
    def __init__(self, supervisor):
        self.supervisor = supervisor

    def run(self, state: PlanState) -> None:
        self._prefetch_shared_data(state)
        # existing loop here
```

- [ ] **Step 6: Re-run the runtime-adjacent tests**

Run:

```bash
pytest tests/test_supervisor.py tests/test_product_runtime.py -v
```

Expected: PASS. No change in current planning outcomes.

- [ ] **Step 7: Commit**

```bash
git add travel_planning_agent/core/daily_pipeline.py travel_planning_agent/agent/supervisor.py tests/test_supervisor.py
git commit -m "refactor: extract daily pipeline from supervisor"
```

---

### Task 2: Split `PlanningRuntime` Into Run and Persistence Services

**Files:**
- Create: `travel_planning_agent/core/plan_run_service.py`
- Create: `travel_planning_agent/core/plan_persistence.py`
- Modify: `travel_planning_agent/core/planning_runtime.py`
- Modify: `tests/test_product_runtime.py`

- [ ] **Step 1: Write failing tests for runtime delegation seams**

Add to `tests/test_product_runtime.py`:

```python
from datetime import date

from travel_planning_agent.core.planning_runtime import PlanningRuntime
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import TripSpec, Traveler


def test_planning_runtime_delegates_run_to_plan_run_service(monkeypatch):
    calls = []

    class FakePlanRunService:
        def __init__(self, db, llm_client):
            calls.append(("init", bool(db), llm_client.__class__.__name__))

        def run(self, spec, session_id=None, trip_id=None, profile="default", persist=True, activate_plan=True, use_react_research=False, use_execution_plan=True):
            calls.append(("run", spec.destination, profile, persist))
            return {"trip_id": "trip_x", "plan_data": {}, "verification": {}, "events": []}

    monkeypatch.setattr(
        "travel_planning_agent.core.planning_runtime.PlanRunService",
        FakePlanRunService,
    )

    runtime = PlanningRuntime(db=None, llm_client=MockLLMClient())
    spec = TripSpec(
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
    )

    result = runtime.run(spec, persist=False)

    assert result["trip_id"] == "trip_x"
    assert calls[-1] == ("run", "南京", "default", False)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_product_runtime.py::test_planning_runtime_delegates_run_to_plan_run_service -v
```

Expected: FAIL because `PlanRunService` is not imported or used yet.

- [ ] **Step 3: Add the minimal run service**

Create `travel_planning_agent/core/plan_run_service.py`:

```python
class PlanRunService:
    def __init__(self, db, llm_client):
        self.db = db
        self.llm_client = llm_client

    def run(
        self,
        spec,
        session_id=None,
        trip_id=None,
        profile="default",
        persist=True,
        activate_plan=True,
        use_react_research=False,
        use_execution_plan=True,
    ):
        raise NotImplementedError
```

Update `travel_planning_agent/core/planning_runtime.py`:

```python
from travel_planning_agent.core.plan_run_service import PlanRunService


def run(...):
    service = PlanRunService(self.db, self.llm)
    return service.run(
        spec,
        session_id=session_id,
        trip_id=trip_id,
        profile=profile,
        persist=persist,
        activate_plan=activate_plan,
        use_react_research=use_react_research,
        use_execution_plan=use_execution_plan,
    )
```

- [ ] **Step 4: Move persistence methods into `plan_persistence.py`**

Create `travel_planning_agent/core/plan_persistence.py` with the methods currently embedded in `PlanningRuntime`:

```python
class PlanPersistenceService:
    def __init__(self, db):
        self.db = db

    def ensure_trip(self, spec, session_id=None, trip_id=None):
        ...

    def create_plan_run(self, run_id, trip_id, session_id, profile, spec, events):
        ...

    def finish_plan_run(self, run_id, status, events, version):
        ...

    def persist_plan(self, trip_id, plan_data, verification, activate=True):
        ...

    def persist_evidence(self, trip_id, state):
        ...
```

Then update `PlanRunService.run()` to own the current orchestration flow and call `PlanPersistenceService`.

- [ ] **Step 5: Run the focused runtime tests**

Run:

```bash
pytest tests/test_product_runtime.py -v
```

Expected: PASS. Existing behavior around verification, final-day normalization, and runtime flow remains intact.

- [ ] **Step 6: Keep `PlanningRuntime` thin**

After the move, `travel_planning_agent/core/planning_runtime.py` should mainly contain:

- constructor wiring
- `run()`
- helper functions that are truly stateless and reusable, such as:
  - `normalize_final_day_departure`
  - `verify_whole_plan`
  - any pure serialization helpers still used elsewhere

Do not leave DB mutation methods in `PlanningRuntime`.

- [ ] **Step 7: Commit**

```bash
git add travel_planning_agent/core/plan_run_service.py travel_planning_agent/core/plan_persistence.py travel_planning_agent/core/planning_runtime.py tests/test_product_runtime.py
git commit -m "refactor: split planning runtime services"
```

---

### Task 3: Extract Chat Workflow Into Service Modules

**Files:**
- Create: `travel_planning_agent/core/chat_service.py`
- Create: `travel_planning_agent/core/chat_session_store.py`
- Create: `travel_planning_agent/core/chat_questioning.py`
- Modify: `travel_planning_agent/api/chat.py`
- Create: `tests/test_chat_service.py`
- Modify: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing service-level workflow test**

Create `tests/test_chat_service.py`:

```python
from travel_planning_agent.core.chat_service import ChatService
from travel_planning_agent.types import AgentResponse


def test_chat_service_returns_followup_question_when_intake_incomplete(monkeypatch):
    class FakeIntake:
        def handle(self, request):
            return AgentResponse(
                request_id=request.request_id,
                status="success",
                data={
                    "complete": False,
                    "question": "请问这次旅行几天？",
                    "extracted": {"destination": "南京", "origin": "杭州"},
                },
            )

    service = ChatService(db=None, llm_client=None, intake_agent=FakeIntake())
    result = service.handle_message("去南京玩", session_id="sess_1")

    assert result.type == "question"
    assert "南京" in result.content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_chat_service.py::test_chat_service_returns_followup_question_when_intake_incomplete -v
```

Expected: FAIL because `ChatService` does not exist yet.

- [ ] **Step 3: Add the minimal chat service and session store**

Create `travel_planning_agent/core/chat_service.py`:

```python
from dataclasses import dataclass


@dataclass
class ChatServiceResult:
    type: str
    content: str
    trip_id: str | None = None
    plan_summary: dict | None = None
    session_id: str | None = None


class ChatService:
    def __init__(self, db, llm_client, intake_agent):
        self.db = db
        self.llm_client = llm_client
        self.intake_agent = intake_agent

    def handle_message(self, message: str, session_id: str) -> ChatServiceResult:
        raise NotImplementedError
```

Create `travel_planning_agent/core/chat_session_store.py`:

```python
class ChatSessionStore:
    def __init__(self, db):
        self.db = db

    def load(self, session_id: str) -> dict:
        ...

    def save(self, session_id: str, context: dict) -> None:
        ...

    def append_message(self, context: dict, role: str, content: str, kind: str | None = None) -> None:
        ...
```

- [ ] **Step 4: Move question normalization helpers out of `api/chat.py`**

Create `travel_planning_agent/core/chat_questioning.py` and move these helpers there:

- `_normalize_followup_question`
- `_normalize_known_field_question`
- `_question_field`
- `_next_missing_question`

Use this exported surface:

```python
def normalize_followup_question(question: str) -> str:
    ...


def normalize_known_field_question(question: str, extracted: dict) -> str:
    ...


def next_missing_question(extracted: dict) -> str:
    ...
```

- [ ] **Step 5: Make `api/chat.py` a thin route**

Update `travel_planning_agent/api/chat.py` so the route primarily:

```python
service = ChatService(...)
result = service.handle_message(req.message, session_id=session_id)
return ChatResponse(**result.__dict__)
```

Keep in `api/chat.py` only:

- request/response Pydantic models
- route registration
- top-level dependency wiring

Move workflow branches into `ChatService`:

- intake incomplete
- intake complete
- plan revision path
- context load/save
- trace event emission

- [ ] **Step 6: Run API and service tests**

Run:

```bash
pytest tests/test_chat_service.py tests/test_chat_api.py -v
```

Expected: PASS. HTTP output shape stays stable while workflow logic is now service-owned.

- [ ] **Step 7: Commit**

```bash
git add travel_planning_agent/core/chat_service.py travel_planning_agent/core/chat_session_store.py travel_planning_agent/core/chat_questioning.py travel_planning_agent/api/chat.py tests/test_chat_service.py tests/test_chat_api.py
git commit -m "refactor: extract chat workflow services"
```

---

### Task 4: Re-evaluate `execution_plan.py` and Remove Duplicate Orchestration

**Files:**
- Modify: `travel_planning_agent/core/execution_plan.py`
- Modify: `travel_planning_agent/agent/researcher.py`
- Modify: `tests/test_product_runtime.py`

- [ ] **Step 1: Write the failing characterization test**

Add to `tests/test_product_runtime.py`:

```python
from datetime import date

from travel_planning_agent.core.execution_plan import build_global_execution_plan
from travel_planning_agent.types import Constraints, Traveler


def test_execution_plan_building_stays_pure_without_runtime_side_effects():
    constraints = Constraints(
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_1")

    assert plan.plan_id == "exec_1"
    assert all(task.status == "pending" for task in plan.tasks)
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```bash
pytest tests/test_product_runtime.py::test_execution_plan_building_stays_pure_without_runtime_side_effects -v
```

Expected: PASS or near-pass. If it fails, fix purity issues before changing ownership boundaries.

- [ ] **Step 3: Freeze `execution_plan.py` to plan-building only**

Confirm `travel_planning_agent/core/execution_plan.py` is limited to:

- task dataclasses
- global-plan builders
- research-task conversion
- JSON-safe serialization
- dedupe helpers

Do not add:

- DB writes
- trace writes
- agent dispatch
- tool execution
- session mutation

If any of those responsibilities were added during prior work, move them out now.

- [ ] **Step 4: Keep `ResearcherAgent` responsible for research semantics**

Update `travel_planning_agent/agent/researcher.py` only if needed so the ownership line is explicit:

- `execution_plan.py` decides task structure
- `researcher.py` decides what research is semantically needed
- executor / pipeline / runtime decide when tasks run

Use comments or small helper names to make this obvious:

```python
# Research semantics: what we need
research_tasks = build_research_plan(...)

# Execution shape: how task specs are represented
execution_plan = execution_plan_from_research_tasks(...)
```

- [ ] **Step 5: Run the regression pack**

Run:

```bash
pytest tests/test_supervisor.py tests/test_product_runtime.py tests/test_chat_api.py -v
```

Expected: PASS. The first three slices stay green after execution-plan cleanup.

- [ ] **Step 6: Commit**

```bash
git add travel_planning_agent/core/execution_plan.py travel_planning_agent/agent/researcher.py tests/test_product_runtime.py
git commit -m "refactor: narrow execution plan responsibilities"
```

---

## Verification Checklist

- [ ] `travel_planning_agent/agent/supervisor.py` is noticeably smaller and mainly routing-focused.
- [ ] `travel_planning_agent/core/planning_runtime.py` no longer contains direct DB persistence methods.
- [ ] `travel_planning_agent/api/chat.py` mostly wires request/response and delegates workflow.
- [ ] Existing plan revision behavior still passes in `tests/test_chat_api.py`.
- [ ] Existing runtime verification behavior still passes in `tests/test_product_runtime.py`.
- [ ] New tests protect the extracted seams so responsibilities do not collapse back together.

## Suggested Execution Order

1. Task 1 only. Stop and review file boundaries.
2. Task 2 only. Stop and review runtime readability.
3. Task 3 only. Stop and test `/api/chat` behavior manually if a local server is available.
4. Task 4 only after the first three slices are stable.

## Out of Scope For This Plan

- Replacing the four-agent architecture
- Redesigning `types.py`
- Rewriting the rule engine
- Adding Redis, Vector DB, Model Router, or Reflection changes
- Frontend redesign
- DB schema changes unrelated to service extraction

