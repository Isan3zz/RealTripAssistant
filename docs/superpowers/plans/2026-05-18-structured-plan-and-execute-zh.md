# Structured Plan And Execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the travel planner toward an explicit, traceable Plan-and-Execute workflow while preserving the current user-facing planning behavior.

**Architecture:** Add an `ExecutionPlan` layer between normalized user constraints and downstream planning agents. The system first builds concrete executable tasks, runs them through a deterministic executor, stores task results/evidence/trace events, then lets existing `SupervisorAgent`, `ResearcherAgent`, `PlannerAgent`, and verification logic consume those results. The migration is incremental: global research first, daily research second, repair planning last.

**Tech Stack:** Python dataclasses, pytest, FastAPI backend, SQLAlchemy JSON records, existing `tool_runtime.py`, existing `PlanningRuntime`, existing `ResearchPlan`, existing JSON tracing.

---

## Target Flow

Current rough flow:

```text
Intake -> PlanningRuntime -> Supervisor -> daily draft/research/refine -> verify -> persist
```

Target explicit Plan-and-Execute flow:

```text
Intake
  -> TripSpec / Constraints
  -> ExecutionPlanBuilder
  -> ExecutionExecutor
  -> Evidence Store / PlanRunRecord events / JSON trace
  -> Supervisor planning loop with initial evidence
  -> Daily ExecutionPlan for research_needs
  -> Itinerary generation
  -> Verify
  -> RepairPlan
  -> Final verify
  -> Persist plan/session/trace
```

This is still mostly workflow-driven. LLMs remain useful for extraction, itinerary generation, optional ReAct research, wording, and revision, but the control plane is explicit code.

## Design Rules

1. Do not rewrite `SupervisorAgent` in one pass.
2. Do not remove existing `ResearchPlan`; wrap or reuse it.
3. Keep `/api/chat` behavior unchanged during the first implementation slice.
4. All executable tasks must have stable `task_id`, `task_type`, `tool_name`, `args`, `required`, `status`, `evidence_ids`, and `error`.
5. Every task execution must write a JSON trace event.
6. Tool calls must still go through `execute_registered_tool()` from `tool_runtime.py`.
7. Required-task failures should not crash planning immediately; they should produce a task result and a verification warning/failure later.
8. The first slice should make global research explicit: weather, outbound transport, must-have POI lookup, lodging anchor lookup when useful.
9. Daily research can be migrated after global research is stable.
10. Repair planning should be explicit and deterministic before asking LLMs to revise.

## File Structure

- Create: `travel_planning_agent/core/execution_plan.py`
  - Defines `ExecutionTask`, `ExecutionPlan`, `ExecutionResult`.
  - Builds global execution plans from `Constraints`.
  - Converts existing `ResearchTask` values into execution tasks.
  - Serializes plan/results to JSON-safe dicts.
- Create: `travel_planning_agent/core/execution_executor.py`
  - Executes `ExecutionPlan` tasks through `execute_registered_tool`.
  - Converts successful `ToolResult` values to evidence dicts.
  - Emits `execution_task_started`, `execution_task_completed`, `execution_task_failed`, and `execution_plan_completed` trace events.
- Modify: `travel_planning_agent/core/planning_runtime.py`
  - Builds and executes a global execution plan before `SupervisorAgent`.
  - Stores execution plan/results in `events` and `PlanRunRecord.events`.
  - Passes `initial_evidence` into `SupervisorAgent.run_planning_loop`.
- Modify: `travel_planning_agent/agent/supervisor.py`
  - Accepts `initial_evidence` and inserts it into `PlanState.evidence`.
  - Later uses `ExecutionExecutor` for daily `research_needs`.
- Modify: `travel_planning_agent/agent/researcher.py`
  - In phase 2, replace `_parallel_research` internal execution with `ExecutionExecutor` while preserving output shape.
- Modify: `travel_planning_agent/core/planning_runtime.py`
  - Adds explicit `RepairPlan` generation from `verify_whole_plan` blocking failures in the final phase.
- Test: `tests/test_execution_plan.py`
  - Unit tests for task building, conversion, serialization, executor success/failure, and trace events.
- Test: `tests/test_product_runtime.py`
  - Runtime integration tests for initial evidence injection and persisted execution events.
- Test: `tests/test_researcher_execution_plan.py`
  - Researcher daily research migration tests.
- Test: `tests/test_repair_plan.py`
  - Repair plan tests for missing required POI, missing return, and rainy outdoor risk.

---

### Task 1: Add Execution Plan Model Tests

**Files:**
- Create: `tests/test_execution_plan.py`

- [ ] **Step 1: Write failing tests for global plan building**

Create `tests/test_execution_plan.py`:

```python
from datetime import date

from travel_planning_agent.core.execution_plan import (
    build_global_execution_plan,
    execution_plan_from_research_tasks,
)
from travel_planning_agent.types import Constraints, ResearchTask, Traveler


def test_build_global_execution_plan_includes_weather_transport_and_must_have():
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_mode="高铁",
        interests=["玄武湖"],
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_global")

    assert plan.plan_id == "exec_global"
    assert [task.task_id for task in plan.tasks] == [
        "global_weather_nanjing_2026-05-18",
        "global_transport_train_hangzhou_nanjing_2026-05-18",
        "global_poi_nanjing_xuanwu_lake",
    ]
    assert plan.tasks[0].tool_name == "get_weather_forecast"
    assert plan.tasks[0].args == {"city": "南京", "date": "2026-05-18", "days": 2}
    assert plan.tasks[1].tool_name == "search_train"
    assert plan.tasks[1].required is True
    assert plan.tasks[2].args["context"] == "玄武湖"


def test_execution_plan_from_research_tasks_preserves_reuse_key_and_priority():
    research_tasks = [
        ResearchTask(
            task_type="ticket_price",
            tool_name="query_ticket_price",
            args={"scenic_name": "玄武湖"},
            reason="核实门票",
            priority=4,
            reuse_key="ticket:玄武湖",
        )
    ]

    plan = execution_plan_from_research_tasks("exec_daily_1", research_tasks)

    assert plan.plan_id == "exec_daily_1"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.task_id == "daily_ticket_price_ticket_xuanwu_lake"
    assert task.task_type == "ticket_price"
    assert task.tool_name == "query_ticket_price"
    assert task.args == {"scenic_name": "玄武湖"}
    assert task.reuse_key == "ticket:玄武湖"
    assert task.priority == 4
    assert task.status == "pending"


def test_execution_plan_to_dict_is_json_safe():
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=1,
        travelers=[Traveler(age_group="adult")],
        budget=1000,
        interests=[],
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_safe")

    assert plan.to_dict()["created_from"]["start_date"] == "2026-05-18"
    assert plan.to_dict()["tasks"][0]["status"] == "pending"
```

- [ ] **Step 2: Run tests and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'travel_planning_agent.core.execution_plan'`.

---

### Task 2: Implement Execution Plan Models and Builders

**Files:**
- Create: `travel_planning_agent/core/execution_plan.py`
- Test: `tests/test_execution_plan.py`

- [ ] **Step 1: Create execution plan module**

Create `travel_planning_agent/core/execution_plan.py`:

```python
"""Structured Plan-and-Execute task models and builders."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from travel_planning_agent.types import Constraints, ResearchTask


@dataclass
class ExecutionTask:
    task_id: str
    task_type: str
    tool_name: str | None
    args: dict[str, Any]
    required: bool = True
    reason: str = ""
    priority: int = 5
    reuse_key: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    evidence_ids: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionResult:
    task_id: str
    status: str
    output: Any = None
    evidence_ids: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionPlan:
    plan_id: str
    scope: str
    created_from: dict[str, Any]
    tasks: list[ExecutionTask] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "scope": self.scope,
            "created_from": _jsonable(self.created_from),
            "created_at": self.created_at,
            "tasks": [_jsonable(asdict(task)) for task in self.tasks],
        }


def build_global_execution_plan(constraints: Constraints, plan_id: str) -> ExecutionPlan:
    start_date = constraints.start_date.isoformat()
    destination = constraints.destination
    tasks = [
        ExecutionTask(
            task_id=f"global_weather_{_slug(destination)}_{start_date}",
            task_type="weather",
            tool_name="get_weather_forecast",
            args={"city": destination, "date": start_date, "days": constraints.days},
            required=True,
            reason="出发前需要确认天气，影响室内/户外安排",
            priority=1,
            reuse_key=f"weather:{destination}:{start_date}:{constraints.days}",
        )
    ]
    if constraints.origin and _prefers_train(constraints.transport_mode):
        tasks.append(
            ExecutionTask(
                task_id=f"global_transport_train_{_slug(constraints.origin)}_{_slug(destination)}_{start_date}",
                task_type="transport",
                tool_name="search_train",
                args={
                    "from_station": constraints.origin,
                    "to_station": destination,
                    "date": start_date,
                },
                required=True,
                reason="用户指定或偏好高铁/火车，需要确认可行交通",
                priority=2,
                reuse_key=f"transport:train:{constraints.origin}->{destination}:{start_date}",
            )
        )
    for item in constraints.interests or []:
        if not item:
            continue
        tasks.append(
            ExecutionTask(
                task_id=f"global_poi_{_slug(destination)}_{_slug(item)}",
                task_type="poi_detail",
                tool_name="search_poi",
                args={"destination": destination, "category": "cultural", "context": item},
                required=True,
                reason=f"用户明确要求包含 {item}",
                priority=3,
                reuse_key=f"poi:{destination}:{item}",
            )
        )
    return ExecutionPlan(
        plan_id=plan_id,
        scope="global",
        created_from=_constraints_summary(constraints),
        tasks=_dedupe_execution_tasks(tasks),
    )


def execution_plan_from_research_tasks(plan_id: str, research_tasks: list[ResearchTask]) -> ExecutionPlan:
    tasks = []
    for task in research_tasks:
        tasks.append(
            ExecutionTask(
                task_id=f"daily_{task.task_type}_{_slug(task.reuse_key or task.tool_name)}",
                task_type=task.task_type,
                tool_name=task.tool_name,
                args=dict(task.args),
                required=True,
                reason=task.reason,
                priority=task.priority,
                reuse_key=task.reuse_key,
            )
        )
    return ExecutionPlan(
        plan_id=plan_id,
        scope="daily_research",
        created_from={"research_task_count": len(research_tasks)},
        tasks=_dedupe_execution_tasks(tasks),
    )


def _constraints_summary(constraints: Constraints) -> dict:
    return {
        "origin": constraints.origin,
        "destination": constraints.destination,
        "start_date": constraints.start_date,
        "days": constraints.days,
        "budget": constraints.budget,
        "pace": constraints.pace,
        "transport_mode": constraints.transport_mode,
        "interests": list(constraints.interests or []),
    }


def _dedupe_execution_tasks(tasks: list[ExecutionTask]) -> list[ExecutionTask]:
    seen = set()
    result = []
    for task in sorted(tasks, key=lambda item: item.priority):
        key = task.reuse_key or f"{task.tool_name}:{task.args}"
        if key in seen:
            continue
        seen.add(key)
        result.append(task)
    return result


def _prefers_train(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in ("高铁", "火车", "动车", "train", "rail"))


def _slug(value: str) -> str:
    mapping = {
        "杭州": "hangzhou",
        "南京": "nanjing",
        "玄武湖": "xuanwu_lake",
    }
    if value in mapping:
        return mapping[value]
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(value or "").strip())
    return text.strip("_").lower() or "unknown"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
```

- [ ] **Step 2: Run execution plan tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py -q
```

Expected: PASS.

---

### Task 3: Add Execution Executor Tests

**Files:**
- Modify: `tests/test_execution_plan.py`
- Create: `travel_planning_agent/core/execution_executor.py`

- [ ] **Step 1: Add failing executor tests**

Append to `tests/test_execution_plan.py`:

```python
from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.core.execution_plan import ExecutionPlan, ExecutionTask
from travel_planning_agent.types import ToolResult


def test_execute_execution_plan_runs_tools_and_returns_evidence(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_run",
        scope="global",
        created_from={"destination": "南京"},
        tasks=[
            ExecutionTask(
                task_id="weather",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"city": "南京"},
            )
        ],
    )

    def fake_execute(name, args):
        assert name == "get_weather_forecast"
        assert args == {"city": "南京"}
        return ToolResult(
            status="success",
            data="南京小雨",
            evidence=[{
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    result = execute_execution_plan(plan)

    assert result["status"] == "completed"
    assert result["results"][0].status == "success"
    assert result["evidence"][0]["claim"] == "南京小雨"
    assert result["tasks"][0].status == "completed"
    assert result["tasks"][0].evidence_ids == [result["evidence"][0]["evidence_id"]]


def test_execute_execution_plan_records_failed_required_task(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_failed",
        scope="global",
        created_from={},
        tasks=[
            ExecutionTask(
                task_id="transport",
                task_type="transport",
                tool_name="search_train",
                args={"from_station": "杭州"},
                required=True,
            )
        ],
    )

    def fake_execute(name, args):
        return ToolResult(status="failed", error="查询失败", confidence="low")

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    result = execute_execution_plan(plan)

    assert result["status"] == "completed_with_errors"
    assert result["results"][0].status == "failed"
    assert result["results"][0].error == "查询失败"
    assert result["tasks"][0].status == "failed"
```

- [ ] **Step 2: Run tests and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py::test_execute_execution_plan_runs_tools_and_returns_evidence tests\test_execution_plan.py::test_execute_execution_plan_records_failed_required_task -q
```

Expected: FAIL because `execution_executor.py` is missing.

- [ ] **Step 3: Implement executor**

Create `travel_planning_agent/core/execution_executor.py`:

```python
"""Execute structured execution plans through the product tool runtime."""

from __future__ import annotations

import uuid
from datetime import datetime

from travel_planning_agent.core.execution_plan import ExecutionPlan, ExecutionResult
from travel_planning_agent.tool_runtime import execute_registered_tool


def execute_execution_plan(plan: ExecutionPlan) -> dict:
    results: list[ExecutionResult] = []
    evidence: list[dict] = []
    has_required_error = False

    _trace("execution_plan_started", {"plan": plan.to_dict()})
    for task in plan.tasks:
        _trace("execution_task_started", {"plan_id": plan.plan_id, "task": task.__dict__})
        if not task.tool_name:
            task.status = "skipped"
            result = ExecutionResult(task_id=task.task_id, status="skipped", error="No tool_name")
            results.append(result)
            continue

        tool_result = execute_registered_tool(task.tool_name, task.args)
        if tool_result.status == "success":
            task.status = "completed"
            task_evidence = [_normalize_evidence(item, task.task_id) for item in tool_result.evidence or []]
            if not task_evidence and tool_result.data:
                task_evidence = [_normalize_evidence({
                    "source": task.tool_name,
                    "source_type": tool_result.source_type,
                    "confidence": tool_result.confidence,
                    "claim": str(tool_result.data),
                    "retrieved_at": tool_result.retrieved_at or datetime.now().isoformat(),
                }, task.task_id)]
            evidence.extend(task_evidence)
            task.evidence_ids = [item["evidence_id"] for item in task_evidence]
            result = ExecutionResult(
                task_id=task.task_id,
                status="success",
                output=tool_result.data,
                evidence_ids=list(task.evidence_ids),
            )
        else:
            task.status = "failed"
            task.error = tool_result.error or str(tool_result.data or "")
            has_required_error = has_required_error or task.required
            result = ExecutionResult(
                task_id=task.task_id,
                status="failed",
                output=tool_result.data,
                error=task.error,
            )
        results.append(result)
        _trace(
            "execution_task_completed" if task.status == "completed" else "execution_task_failed",
            {"plan_id": plan.plan_id, "task_id": task.task_id, "status": task.status, "error": task.error},
        )

    status = "completed_with_errors" if has_required_error else "completed"
    payload = {
        "status": status,
        "plan": plan,
        "tasks": plan.tasks,
        "results": results,
        "evidence": evidence,
    }
    _trace("execution_plan_completed", {"plan_id": plan.plan_id, "status": status})
    return payload


def _normalize_evidence(item: dict, task_id: str) -> dict:
    return {
        "evidence_id": item.get("evidence_id") or f"ev_{task_id}_{uuid.uuid4().hex[:8]}",
        "source": item.get("source", "tool"),
        "source_type": item.get("source_type", "api"),
        "confidence": item.get("confidence", "medium"),
        "claim": item.get("claim", ""),
        "retrieved_at": item.get("retrieved_at") or datetime.now().isoformat(),
    }


def _trace(event_type: str, data: dict) -> None:
    try:
        from travel_planning_agent.core.tracing import record_trace_event

        record_trace_event(event_type, "execution", data)
    except Exception:
        return
```

- [ ] **Step 4: Run execution plan tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py -q
```

Expected: PASS.

---

### Task 4: Integrate Global Execution Plan Into PlanningRuntime

**Files:**
- Modify: `travel_planning_agent/core/planning_runtime.py`
- Modify: `travel_planning_agent/agent/supervisor.py`
- Modify: `tests/test_product_runtime.py`

- [ ] **Step 1: Add failing runtime integration test**

Append to `tests/test_product_runtime.py`:

```python
def test_planning_runtime_executes_global_plan_and_passes_initial_evidence(monkeypatch):
    from datetime import date
    from travel_planning_agent.core.planning_runtime import PlanningRuntime
    from travel_planning_agent.types import TripSpec, Traveler, PlanState

    seen = {}

    def fake_execute(plan):
        seen["plan"] = plan
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [{
                "evidence_id": "ev_weather",
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        }

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, initial_evidence=None, execution_plan=None):
            seen["initial_evidence"] = initial_evidence
            seen["execution_plan"] = execution_plan
            return PlanState(trip_id="trip_exec", constraints=constraints)

    monkeypatch.setattr("travel_planning_agent.core.planning_runtime.execute_execution_plan", fake_execute)
    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_preference="高铁",
        must_have=["玄武湖"],
    )

    result = PlanningRuntime().run(spec, persist=False, use_execution_plan=True)

    assert seen["plan"].scope == "global"
    assert seen["initial_evidence"][0]["evidence_id"] == "ev_weather"
    assert seen["execution_plan"].plan_id.startswith("exec_global_")
    assert any(event["stage"] == "execution_plan" for event in result["events"])
```

- [ ] **Step 2: Run test and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_executes_global_plan_and_passes_initial_evidence -q
```

Expected: FAIL because `use_execution_plan` and `initial_evidence` are not supported.

- [ ] **Step 3: Modify `PlanningRuntime.run` signature**

Add an opt-in parameter:

```python
use_execution_plan: bool = True,
```

The final signature should include both existing ReAct option and this option:

```python
def run(..., use_react_research: bool = False, use_execution_plan: bool = True) -> dict:
```

- [ ] **Step 4: Import execution helpers**

At the top of `planning_runtime.py`, add:

```python
from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.core.execution_plan import build_global_execution_plan
```

- [ ] **Step 5: Build and execute global plan before `SupervisorAgent`**

After:

```python
constraints = self._apply_profile(spec, profile).to_constraints()
self._record_event(events, "research_plan", "Shared prefetch and planner research will run")
```

add:

```python
initial_evidence = []
execution_plan = None
if use_execution_plan:
    execution_plan = build_global_execution_plan(
        constraints,
        plan_id=f"exec_global_{run_id}",
    )
    execution_result = execute_execution_plan(execution_plan)
    initial_evidence = execution_result.get("evidence") or []
    self._record_event(
        events,
        "execution_plan",
        f"Global execution plan {execution_result.get('status')} with {len(execution_plan.tasks)} task(s)",
    )
```

- [ ] **Step 6: Pass initial evidence into supervisor**

Change:

```python
state = supervisor.run_planning_loop(constraints)
```

to:

```python
state = supervisor.run_planning_loop(
    constraints,
    initial_evidence=initial_evidence,
    execution_plan=execution_plan,
)
```

- [ ] **Step 7: Modify `SupervisorAgent.run_planning_loop`**

Change signature:

```python
def run_planning_loop(self, constraints: Constraints) -> PlanState:
```

to:

```python
def run_planning_loop(
    self,
    constraints: Constraints,
    initial_evidence: list[dict] | None = None,
    execution_plan=None,
) -> PlanState:
```

After `state.assumptions = ...`, add:

```python
        for ev_data in initial_evidence or []:
            if isinstance(ev_data, dict) and ev_data.get("evidence_id"):
                state.evidence[ev_data["evidence_id"]] = Evidence(**ev_data)
        if execution_plan is not None:
            state.module_context["execution_plan"] = execution_plan.to_dict()
```

- [ ] **Step 8: Run integration test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_executes_global_plan_and_passes_initial_evidence -q
```

Expected: PASS.

---

### Task 5: Migrate Daily Research to ExecutionExecutor

**Files:**
- Modify: `travel_planning_agent/agent/researcher.py`
- Create: `tests/test_researcher_execution_plan.py`

- [ ] **Step 1: Write failing daily research test**

Create `tests/test_researcher_execution_plan.py`:

```python
from datetime import date

from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import AgentRequest, Constraints, Traveler


def test_parallel_research_uses_execution_plan_executor(monkeypatch):
    seen = {}

    def fake_execute(plan):
        seen["plan"] = plan
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [{
                "evidence_id": "ev_ticket",
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        }

    monkeypatch.setattr("travel_planning_agent.agent.researcher.execute_execution_plan", fake_execute)

    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    response = agent.handle(AgentRequest(
        request_id="req_daily_exec",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
        },
    ))

    assert response.status == "success"
    assert seen["plan"].scope == "daily_research"
    assert response.data["evidence"][0]["claim"] == "玄武湖免费"
    assert response.data["execution_plan"]["plan_id"].startswith("exec_research_")
```

- [ ] **Step 2: Run test and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py -q
```

Expected: FAIL because researcher does not expose `execution_plan`.

- [ ] **Step 3: Import execution helpers in `researcher.py`**

Add near existing imports:

```python
from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.core.execution_plan import execution_plan_from_research_tasks
```

- [ ] **Step 4: Replace direct parallel tool execution inside `_parallel_research`**

Inside `_parallel_research`, after `research_plan = build_research_plan(...)`, add:

```python
        execution_plan = execution_plan_from_research_tasks(
            f"exec_research_{uuid.uuid4().hex[:8]}",
            research_plan.tasks,
        )
        execution_result = execute_execution_plan(execution_plan)
        evidence_list = list(execution_result.get("evidence") or [])
        if evidence_list:
            return AgentResponse(
                request_id="",
                status="success",
                data={
                    "evidence": evidence_list,
                    "research_plan": research_plan.to_dict(),
                    "execution_plan": execution_plan.to_dict(),
                },
                tokens_used=0,
                source_note="execution_plan",
            )
```

Keep the existing old parallel/LLM summary path below as fallback when `evidence_list` is empty.

- [ ] **Step 5: Run researcher execution test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py -q
```

Expected: PASS.

---

### Task 6: Add Explicit Repair Plan

**Files:**
- Create: `travel_planning_agent/core/repair_plan.py`
- Create: `tests/test_repair_plan.py`
- Modify: `travel_planning_agent/core/planning_runtime.py`

- [ ] **Step 1: Write repair plan tests**

Create `tests/test_repair_plan.py`:

```python
from travel_planning_agent.core.repair_plan import build_repair_plan


def test_build_repair_plan_for_missing_must_have():
    failures = [{"rule_id": "W08", "detail": "缺少用户必去项：玄武湖"}]

    plan = build_repair_plan(failures, warnings=[])

    assert plan["status"] == "repair_needed"
    assert plan["tasks"] == [{
        "repair_type": "insert_required_poi",
        "target": "玄武湖",
        "reason": "缺少用户必去项：玄武湖",
        "priority": 1,
    }]


def test_build_repair_plan_for_missing_return_transport():
    failures = [{"rule_id": "W04", "detail": "最后一天缺少返程交通"}]

    plan = build_repair_plan(failures, warnings=[])

    assert plan["tasks"][0]["repair_type"] == "add_return_transport"
    assert plan["tasks"][0]["priority"] == 1


def test_build_repair_plan_for_route_buffer_warning():
    warnings = [{"rule_id": "W07", "detail": "两点之间仅 0 分钟，建议补充交通缓冲"}]

    plan = build_repair_plan(failures=[], warnings=warnings)

    assert plan["status"] == "repair_recommended"
    assert plan["tasks"][0]["repair_type"] == "add_route_buffer"
```

- [ ] **Step 2: Run tests and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_repair_plan.py -q
```

Expected: FAIL because `repair_plan.py` does not exist.

- [ ] **Step 3: Implement repair plan module**

Create `travel_planning_agent/core/repair_plan.py`:

```python
"""Build explicit repair tasks from verification failures and warnings."""

from __future__ import annotations


def build_repair_plan(failures: list[dict], warnings: list[dict]) -> dict:
    tasks = []
    for failure in failures:
        rule_id = failure.get("rule_id")
        detail = failure.get("detail", "")
        if rule_id == "W08":
            target = detail.split("：", 1)[-1] if "：" in detail else detail
            tasks.append({
                "repair_type": "insert_required_poi",
                "target": target,
                "reason": detail,
                "priority": 1,
            })
        elif rule_id == "W04":
            tasks.append({
                "repair_type": "add_return_transport",
                "target": "final_day",
                "reason": detail,
                "priority": 1,
            })
    for warning in warnings:
        rule_id = warning.get("rule_id")
        detail = warning.get("detail", "")
        if rule_id == "W07":
            tasks.append({
                "repair_type": "add_route_buffer",
                "target": warning.get("affected_segments") or [],
                "reason": detail,
                "priority": 3,
            })
    if any(task["priority"] == 1 for task in tasks):
        status = "repair_needed"
    elif tasks:
        status = "repair_recommended"
    else:
        status = "clean"
    return {"status": status, "tasks": tasks}
```

- [ ] **Step 4: Persist repair plan into verification**

In `PlanningRuntime.run`, after:

```python
state.validation = verify_whole_plan(state)
```

add:

```python
        from travel_planning_agent.core.repair_plan import build_repair_plan

        repair_plan = build_repair_plan(
            state.validation.blocking_failures,
            state.validation.warnings,
        )
        state.module_context["repair_plan"] = repair_plan
        self._record_event(events, "repair_plan", f"{repair_plan['status']} with {len(repair_plan['tasks'])} task(s)")
```

This task records repair needs but does not yet auto-apply repairs. Auto-repair is a later slice because it touches itinerary mutation behavior.

- [ ] **Step 5: Run repair tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_repair_plan.py -q
```

Expected: PASS.

---

### Task 7: Verification Pass

**Files:**
- No source file changes unless tests expose a bug.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py tests\test_researcher_execution_plan.py tests\test_repair_plan.py tests\test_product_runtime.py -q --basetemp .tmp_pytest_run\pytest-plan-execute-focused
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_run\pytest
```

Expected: PASS.

- [ ] **Step 3: Clean temp directory**

Run:

```powershell
if (Test-Path '.tmp_pytest_run') { Remove-Item -Recurse -Force '.tmp_pytest_run' }
```

- [ ] **Step 4: Restart backend**

Run:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 1 }
Start-Process -FilePath 'D:\Python_Project\RealTripAssistant\venv\Scripts\python.exe' -ArgumentList '-m','travel_planning_agent.main' -WorkingDirectory 'D:\Python_Project\RealTripAssistant' -WindowStyle Hidden
Start-Sleep -Seconds 3
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 10 | ConvertTo-Json -Depth 4
```

Expected: health JSON contains `"status": "ok"`.

- [ ] **Step 5: Manual trace smoke test**

Run a normal chat request and then inspect a new trace JSON:

```powershell
$body = @{
  session_id = "sess_plan_execute_smoke"
  message = "明天杭州去南京玩两天，高铁，想看玄武湖，预算2000"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType 'application/json; charset=utf-8' -Body $body | ConvertTo-Json -Depth 20
```

Expected trace events include:

```text
execution_plan_started
execution_task_started
execution_task_completed or execution_task_failed
execution_plan_completed
```

If the chat remains in follow-up mode because intake asks for a missing date, complete the missing date and inspect the trace from that second request.

---

## Self-Review

Spec coverage:
- The design makes Plan-and-Execute explicit through `ExecutionPlan`, `ExecutionTask`, and `ExecutionResult`.
- Existing workflow remains intact; the first integration only injects global evidence into the current supervisor loop.
- Daily research migration is covered separately and preserves `ResearcherAgent` output shape.
- Repair planning becomes explicit without yet mutating plans automatically.
- Traceability is improved with execution-level trace events.

Risk controls:
- `/api/chat` does not need a frontend change.
- Existing ReAct mode remains optional and compatible.
- Old `ResearchPlan` is reused, not deleted.
- Required task failures become structured results instead of exceptions.
- Auto-repair is intentionally deferred because it changes itinerary behavior.

Type consistency:
- `ExecutionPlan.to_dict()` returns JSON-safe payloads for `PlanRunRecord.events` and `module_context`.
- Evidence dicts match the existing `Evidence` dataclass keys.
- Researcher still returns `{"evidence": [...]}` so supervisor code remains compatible.
