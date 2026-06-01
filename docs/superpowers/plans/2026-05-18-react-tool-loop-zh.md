# ReAct Tool Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, traceable ReAct-style tool loop for dynamic travel research without replacing the existing deterministic planning runtime.

**Architecture:** Introduce a small `core/react_loop.py` runner that asks the model for structured `action` or `final` decisions, executes tools through the existing `tool_runtime.py`, records every action/observation into JSON trace, and returns structured findings. Researcher uses this runner behind an explicit `mode="react_research"` switch first; after tests pass, PlanningRuntime can opt in through a boolean flag instead of changing the default behavior immediately.

**Tech Stack:** Python, FastAPI-adjacent service modules, pytest, existing `LLMClient`, existing `tool_runtime.registry`, existing JSON tracing.

---

## Design Rules

1. Do not rewrite the whole planner into ReAct.
2. Keep `PlanningRuntime` as the orchestration backbone.
3. Use ReAct only for dynamic lookup/research decisions: weather, POI, hotel, tickets, train/flight, nearby search.
4. Do not persist raw hidden chain-of-thought. Store only a short `rationale_summary` written by the model as an explicit audit summary.
5. All tool execution must go through `execute_registered_tool()` so existing tracing and result envelopes stay consistent.
6. Every ReAct loop must have `max_steps`, allowed tool names, and graceful fallback when the model returns invalid JSON or unknown tools.
7. The output of the ReAct runner must be deterministic enough for tests: a list of steps, a final dict, status, tokens, and errors.

## ReAct Decision JSON Contract

Each model turn must return one of these JSON shapes:

```json
{
  "rationale_summary": "Need weather before deciding indoor/outdoor plan.",
  "action": {
    "tool": "get_weather_forecast",
    "args": {"city": "南京", "date": "2026-05-18"}
  }
}
```

or:

```json
{
  "rationale_summary": "Weather and POI info are enough to summarize.",
  "final": {
    "findings": [
      {
        "category": "weather",
        "title": "南京天气",
        "detail": "小雨，建议保留室内备选。",
        "source": "api"
      }
    ],
    "covered_items": ["南京天气"]
  }
}
```

The runner never requires or stores free-form private reasoning. `rationale_summary` is a concise audit field, not hidden chain-of-thought.

## File Structure

- Create: `travel_planning_agent/core/react_loop.py`
  - Defines `ReActDecision`, `ReActStep`, `ReActRunResult`.
  - Parses model JSON decisions.
  - Executes allowed tools through `execute_registered_tool`.
  - Records `react_decision`, `react_observation`, `react_final`, and `react_error` trace events.
- Modify: `travel_planning_agent/agent/researcher.py`
  - Adds `mode == "react_research"` branch.
  - Converts ReAct final findings into existing evidence dicts.
  - Keeps `_parallel_research`, `_research_mode`, and `_price_lookup` unchanged.
- Modify: `travel_planning_agent/core/planning_runtime.py`
  - Adds optional `use_react_research: bool = False` argument to `run`.
  - Passes `mode="react_research"` only when explicitly enabled.
- Modify: `travel_planning_agent/api/chat.py`
  - No behavior change by default.
  - Later execution may add a guarded setting, but the first implementation should keep chat output stable.
- Create: `tests/test_react_loop.py`
  - Unit tests for parsing, successful action/observation/final loop, unknown tool failure, max-step stop, and trace events.
- Create or modify: `tests/test_researcher_react.py`
  - Tests `ResearcherAgent.handle(... mode="react_research")`.
- Modify: `tests/test_product_runtime.py`
  - Tests that `PlanningRuntime.run(... use_react_research=False)` preserves current behavior and `True` passes react mode.

---

### Task 1: Add ReAct Loop Parser Tests

**Files:**
- Create: `tests/test_react_loop.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_react_loop.py` with:

```python
import json

from travel_planning_agent.core.react_loop import parse_react_decision


def test_parse_action_decision():
    decision = parse_react_decision(json.dumps({
        "rationale_summary": "Need weather before choosing activities.",
        "action": {
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18"},
        },
    }, ensure_ascii=False))

    assert decision.kind == "action"
    assert decision.rationale_summary == "Need weather before choosing activities."
    assert decision.tool == "get_weather_forecast"
    assert decision.args == {"city": "南京", "date": "2026-05-18"}
    assert decision.final is None


def test_parse_final_decision():
    decision = parse_react_decision(json.dumps({
        "rationale_summary": "Enough observations.",
        "final": {
            "findings": [{"category": "weather", "title": "南京天气", "detail": "小雨"}],
            "covered_items": ["南京天气"],
        },
    }, ensure_ascii=False))

    assert decision.kind == "final"
    assert decision.tool is None
    assert decision.args == {}
    assert decision.final["findings"][0]["title"] == "南京天气"


def test_parse_invalid_decision_returns_error_kind():
    decision = parse_react_decision("not json")

    assert decision.kind == "error"
    assert "Invalid JSON" in decision.error
```

- [ ] **Step 2: Run parser tests and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_react_loop.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'travel_planning_agent.core.react_loop'`.

---

### Task 2: Implement ReAct Data Types and Parser

**Files:**
- Create: `travel_planning_agent/core/react_loop.py`
- Test: `tests/test_react_loop.py`

- [ ] **Step 1: Add the initial module**

Create `travel_planning_agent/core/react_loop.py`:

```python
"""Bounded ReAct-style tool loop for travel research."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReActDecision:
    kind: str
    rationale_summary: str = ""
    tool: str | None = None
    args: dict = field(default_factory=dict)
    final: dict | None = None
    error: str | None = None


@dataclass
class ReActStep:
    step_index: int
    rationale_summary: str
    tool: str
    args: dict
    observation_status: str
    observation: str


@dataclass
class ReActRunResult:
    status: str
    final: dict = field(default_factory=dict)
    steps: list[ReActStep] = field(default_factory=list)
    tokens_used: int = 0
    error: str | None = None


def parse_react_decision(text: str) -> ReActDecision:
    try:
        data = json.loads((text or "").strip())
    except json.JSONDecodeError as exc:
        return ReActDecision(kind="error", error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return ReActDecision(kind="error", error="Decision must be a JSON object")

    rationale = str(data.get("rationale_summary") or "").strip()
    action = data.get("action")
    final = data.get("final")

    if isinstance(action, dict):
        tool = action.get("tool")
        args = action.get("args") or {}
        if not isinstance(tool, str) or not tool:
            return ReActDecision(kind="error", rationale_summary=rationale, error="Action tool is required")
        if not isinstance(args, dict):
            return ReActDecision(kind="error", rationale_summary=rationale, error="Action args must be an object")
        return ReActDecision(
            kind="action",
            rationale_summary=rationale,
            tool=tool,
            args=args,
        )

    if isinstance(final, dict):
        return ReActDecision(kind="final", rationale_summary=rationale, final=final)

    return ReActDecision(
        kind="error",
        rationale_summary=rationale,
        error="Decision must contain either action or final",
    )
```

- [ ] **Step 2: Run parser tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_react_loop.py -q
```

Expected: PASS for the three parser tests.

- [ ] **Step 3: Commit**

Run:

```powershell
git add travel_planning_agent/core/react_loop.py tests/test_react_loop.py
git commit -m "feat: add react decision parser"
```

---

### Task 3: Add ReAct Runner Tests

**Files:**
- Modify: `tests/test_react_loop.py`

- [ ] **Step 1: Add fake LLM and runner tests**

Append to `tests/test_react_loop.py`:

```python
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.core.react_loop import run_react_loop
from travel_planning_agent.types import ToolResult


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system_prompt: str, user_message: str, tools=None):
        self.calls.append({"system_prompt": system_prompt, "user_message": user_message, "tools": tools})
        text = self.responses.pop(0)
        return LLMResult(success=True, text=text, data=None, tokens_used=11)


def test_run_react_loop_executes_action_then_final(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Check weather first.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Weather observed.",
            "final": {
                "findings": [{"category": "weather", "title": "南京天气", "detail": "小雨"}],
                "covered_items": ["南京天气"],
            },
        }, ensure_ascii=False),
    ])
    executed = []

    def fake_execute(name, args):
        executed.append((name, args))
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=3,
    )

    assert result.status == "success"
    assert result.final["findings"][0]["title"] == "南京天气"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "get_weather_forecast"
    assert result.steps[0].observation == "南京小雨"
    assert executed == [("get_weather_forecast", {"city": "南京"})]
    assert "Observation 1" in llm.calls[1]["user_message"]


def test_run_react_loop_rejects_unknown_tool(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Try unsafe tool.",
            "action": {"tool": "delete_database", "args": {}},
        }, ensure_ascii=False),
    ])

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=3,
    )

    assert result.status == "failed"
    assert "not allowed" in result.error


def test_run_react_loop_stops_at_max_steps(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Still checking.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Still checking.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
    ])

    def fake_execute(name, args):
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=2,
    )

    assert result.status == "failed"
    assert result.error == "ReAct loop reached max_steps without final answer"
    assert len(result.steps) == 2
```

- [ ] **Step 2: Run tests and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_react_loop.py -q
```

Expected: FAIL because `run_react_loop` is not defined.

---

### Task 4: Implement ReAct Runner

**Files:**
- Modify: `travel_planning_agent/core/react_loop.py`
- Test: `tests/test_react_loop.py`

- [ ] **Step 1: Add runner implementation**

Append to `travel_planning_agent/core/react_loop.py`:

```python
from travel_planning_agent.tool_runtime import execute_registered_tool


REACT_SYSTEM_PROMPT = """You are a travel research tool-use agent.
Return only JSON.
At each step, choose exactly one of:
1. {"rationale_summary": "...", "action": {"tool": "...", "args": {...}}}
2. {"rationale_summary": "...", "final": {...}}

Rules:
- Use only allowed tools.
- Keep rationale_summary short and audit-friendly.
- Do not include hidden chain-of-thought.
- Final must contain findings and covered_items.
"""


def run_react_loop(
    llm_client,
    *,
    task: str,
    context: dict,
    allowed_tools: list[str],
    max_steps: int = 5,
) -> ReActRunResult:
    steps: list[ReActStep] = []
    tokens_used = 0
    observations: list[str] = []

    for step_index in range(1, max_steps + 1):
        user_message = _build_react_user_message(task, context, allowed_tools, observations)
        llm_result = llm_client.generate(REACT_SYSTEM_PROMPT, user_message, tools=None)
        tokens_used += llm_result.tokens_used or 0

        if not llm_result.success:
            error = llm_result.error or "LLM call failed"
            _record_react_trace("react_error", {"error": error, "step_index": step_index})
            return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)

        decision = parse_react_decision(llm_result.text or "")
        _record_react_trace(
            "react_decision",
            {
                "step_index": step_index,
                "kind": decision.kind,
                "rationale_summary": decision.rationale_summary,
                "tool": decision.tool,
                "args": decision.args,
                "error": decision.error,
            },
        )

        if decision.kind == "error":
            return ReActRunResult(
                status="failed",
                steps=steps,
                tokens_used=tokens_used,
                error=decision.error,
            )

        if decision.kind == "final":
            final = decision.final or {}
            _record_react_trace("react_final", {"step_index": step_index, "final": final})
            return ReActRunResult(
                status="success",
                final=final,
                steps=steps,
                tokens_used=tokens_used,
            )

        assert decision.tool is not None
        if decision.tool not in allowed_tools:
            error = f"Tool not allowed: {decision.tool}"
            _record_react_trace("react_error", {"error": error, "step_index": step_index})
            return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)

        tool_result = execute_registered_tool(decision.tool, decision.args)
        observation = tool_result.data or tool_result.error or ""
        steps.append(
            ReActStep(
                step_index=step_index,
                rationale_summary=decision.rationale_summary,
                tool=decision.tool,
                args=decision.args,
                observation_status=tool_result.status,
                observation=str(observation),
            )
        )
        observations.append(f"Observation {step_index} [{decision.tool}]: {observation}")
        _record_react_trace(
            "react_observation",
            {
                "step_index": step_index,
                "tool": decision.tool,
                "status": tool_result.status,
                "observation": str(observation)[:1000],
            },
        )

    error = "ReAct loop reached max_steps without final answer"
    _record_react_trace("react_error", {"error": error, "max_steps": max_steps})
    return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)


def _build_react_user_message(
    task: str,
    context: dict,
    allowed_tools: list[str],
    observations: list[str],
) -> str:
    return json.dumps(
        {
            "task": task,
            "context": context,
            "allowed_tools": allowed_tools,
            "observations": observations,
        },
        ensure_ascii=False,
        default=str,
    )


def _record_react_trace(event_type: str, data: dict) -> None:
    try:
        from travel_planning_agent.core.tracing import record_trace_event

        record_trace_event(event_type, "react", data)
    except Exception:
        return
```

- [ ] **Step 2: Run ReAct tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_react_loop.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add travel_planning_agent/core/react_loop.py tests/test_react_loop.py
git commit -m "feat: add bounded react tool loop"
```

---

### Task 5: Add Trace Event Test

**Files:**
- Modify: `tests/test_react_loop.py`

- [ ] **Step 1: Add trace test**

Append to `tests/test_react_loop.py`:

```python
def test_run_react_loop_writes_trace_events(monkeypatch, tmp_path):
    from travel_planning_agent.config import settings
    from travel_planning_agent.core.tracing import clear_trace_context, create_trace_id, set_trace_context

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    trace_id = create_trace_id()
    set_trace_context(trace_id, session_id="sess_react_trace")
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Check weather.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Enough.",
            "final": {"findings": [], "covered_items": ["南京天气"]},
        }, ensure_ascii=False),
    ])

    def fake_execute(name, args):
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    try:
        run_react_loop(
            llm,
            task="核实南京天气",
            context={"destination": "南京"},
            allowed_tools=["get_weather_forecast"],
            max_steps=3,
        )
    finally:
        clear_trace_context()

    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event_types = [event["event_type"] for event in trace["events"]]
    assert "react_decision" in event_types
    assert "react_observation" in event_types
    assert "react_final" in event_types
```

- [ ] **Step 2: Run trace test**

Run with workspace temp path:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_react_loop.py::test_run_react_loop_writes_trace_events -q --basetemp .tmp_pytest_run\pytest-react-trace
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add tests/test_react_loop.py
git commit -m "test: cover react trace events"
```

---

### Task 6: Integrate ReAct Mode Into ResearcherAgent

**Files:**
- Modify: `travel_planning_agent/agent/researcher.py`
- Create: `tests/test_researcher_react.py`

- [ ] **Step 1: Write Researcher ReAct tests**

Create `tests/test_researcher_react.py`:

```python
from datetime import date

from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.types import AgentRequest, Constraints, Traveler


class FinalOnlyLLM:
    def generate(self, system_prompt, user_message, tools=None):
        return LLMResult(
            success=True,
            text='{"rationale_summary":"Enough known data.","final":{"findings":[{"category":"poi","title":"玄武湖","detail":"适合慢游","source":"model"}],"covered_items":["玄武湖"]}}',
            tokens_used=9,
        )


def test_researcher_react_mode_returns_evidence(monkeypatch):
    agent = ResearcherAgent(FinalOnlyLLM())
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        interests=["玄武湖"],
    )

    response = agent.handle(
        AgentRequest(
            request_id="req_react",
            agent="researcher",
            context={},
            params={
                "mode": "react_research",
                "constraints": constraints,
                "research_needs": [{"type": "poi_detail", "item": "玄武湖"}],
            },
        )
    )

    assert response.status == "success"
    assert response.data["react"]["status"] == "success"
    assert response.data["evidence"][0]["claim"] == "玄武湖: 适合慢游"
    assert response.tokens_used == 9
```

- [ ] **Step 2: Run test and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_react.py -q
```

Expected: FAIL because `react_research` mode is not implemented.

- [ ] **Step 3: Add mode branch in `ResearcherAgent.handle`**

In `travel_planning_agent/agent/researcher.py`, inside `handle`, after:

```python
mode = params.get("mode", "")
```

add:

```python
        if mode == "react_research":
            return self._react_research(params)
```

- [ ] **Step 4: Add `_react_research` method**

Add this method before `_parallel_research`:

```python
    def _react_research(self, params: dict) -> AgentResponse:
        """Bounded ReAct research mode for dynamic tool decisions."""
        from travel_planning_agent.core.react_loop import run_react_loop

        constraints: Constraints = params.get("constraints")
        if not constraints:
            return AgentResponse(request_id="", status="failed", data={}, error="缺少 constraints")

        research_needs = params.get("research_needs", [])
        context = {
            "destination": constraints.destination,
            "origin": constraints.origin,
            "start_date": constraints.start_date.isoformat(),
            "days": constraints.days,
            "budget": constraints.budget,
            "pace": constraints.pace,
            "transport_mode": constraints.transport_mode,
            "interests": list(constraints.interests or []),
            "research_needs": research_needs,
        }
        result = run_react_loop(
            self.llm_client,
            task="Research travel facts for the requested itinerary. Return findings and covered_items.",
            context=context,
            allowed_tools=[
                "search_poi",
                "get_weather_forecast",
                "query_ticket_price",
                "search_hotel",
                "get_hotel_detail",
                "search_flight",
                "search_train",
                "geo_encode",
                "search_around",
            ],
            max_steps=5,
        )
        if result.status != "success":
            fallback = self._fallback_model_knowledge(params)
            fallback.data = dict(fallback.data or {})
            fallback.data["react"] = {"status": result.status, "error": result.error}
            return fallback

        evidence_list = []
        for finding in result.final.get("findings") or []:
            if isinstance(finding, dict):
                evidence_list.append(self._finding_to_evidence(finding, constraints.destination))

        return AgentResponse(
            request_id="",
            status="success",
            data={
                "evidence": evidence_list,
                "react": {
                    "status": result.status,
                    "steps": [
                        {
                            "step_index": step.step_index,
                            "tool": step.tool,
                            "args": step.args,
                            "observation_status": step.observation_status,
                            "rationale_summary": step.rationale_summary,
                        }
                        for step in result.steps
                    ],
                    "covered_items": result.final.get("covered_items") or [],
                },
            },
            tokens_used=result.tokens_used,
            source_note="react_tool_loop",
        )
```

- [ ] **Step 5: Run Researcher ReAct tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_react.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add travel_planning_agent/agent/researcher.py tests/test_researcher_react.py
git commit -m "feat: add react research mode"
```

---

### Task 7: Add PlanningRuntime Opt-In Flag

**Files:**
- Modify: `travel_planning_agent/core/planning_runtime.py`
- Modify: `tests/test_product_runtime.py`

- [ ] **Step 1: Write opt-in test**

Append to `tests/test_product_runtime.py`:

```python
def test_planning_runtime_accepts_react_research_flag(monkeypatch, db_session):
    from datetime import date
    from travel_planning_agent.core.planning_runtime import PlanningRuntime
    from travel_planning_agent.types import TripSpec, Traveler, PlanState

    seen = {}

    class FakeSupervisor:
        def __init__(self, llm, agents):
            seen["researcher"] = agents["researcher"]

        def run_planning_loop(self, constraints):
            seen["constraints"] = constraints
            return PlanState(trip_id="trip_react_flag", constraints=constraints)

    monkeypatch.setattr("travel_planning_agent.agent.supervisor.SupervisorAgent", FakeSupervisor)

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        must_have=["玄武湖"],
    )

    runtime = PlanningRuntime(db=db_session)
    runtime.run(spec, session_id="sess_react_flag", use_react_research=True)

    assert getattr(seen["researcher"], "use_react_research") is True
```

- [ ] **Step 2: Run test and confirm red**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_accepts_react_research_flag -q
```

Expected: FAIL because `PlanningRuntime.run` does not accept `use_react_research`.

- [ ] **Step 3: Add flag to `PlanningRuntime.run`**

Change the function signature in `travel_planning_agent/core/planning_runtime.py` from:

```python
    def run(
        self,
        spec: TripSpec,
        session_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        profile: str = "default",
        persist: bool = True,
        activate_plan: bool = True,
    ) -> dict:
```

to:

```python
    def run(
        self,
        spec: TripSpec,
        session_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        profile: str = "default",
        persist: bool = True,
        activate_plan: bool = True,
        use_react_research: bool = False,
    ) -> dict:
```

- [ ] **Step 4: Attach flag to ResearcherAgent**

Replace:

```python
        supervisor = SupervisorAgent(self.llm, {
            "researcher": ResearcherAgent(self.llm),
            "planner": PlannerAgent(self.llm),
            "verifier": VerifierAgent(self.llm),
        })
```

with:

```python
        researcher = ResearcherAgent(self.llm)
        researcher.use_react_research = use_react_research
        supervisor = SupervisorAgent(self.llm, {
            "researcher": researcher,
            "planner": PlannerAgent(self.llm),
            "verifier": VerifierAgent(self.llm),
        })
```

- [ ] **Step 5: Make ResearcherAgent honor the flag**

In `ResearcherAgent.__init__`, add:

```python
        self.use_react_research = False
```

In `ResearcherAgent.handle`, after the explicit mode check and before `research_needs` branching, add:

```python
        if self.use_react_research and params.get("research_needs"):
            return self._react_research(params)
```

- [ ] **Step 6: Run opt-in test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_accepts_react_research_flag -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add travel_planning_agent/core/planning_runtime.py travel_planning_agent/agent/researcher.py tests/test_product_runtime.py
git commit -m "feat: add react research runtime flag"
```

---

### Task 8: Verification Pass

**Files:**
- No source file changes unless verification exposes a bug.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_react_loop.py tests\test_researcher_react.py tests\test_product_runtime.py tests\test_tracing.py -q --basetemp .tmp_pytest_run\pytest-react-focused
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

- [ ] **Step 5: Manual smoke test with explicit ReAct mode**

Run a direct Python smoke test instead of changing the frontend:

```powershell
@'
from datetime import date
from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.llm import MockLLMClient
from travel_planning_agent.types import AgentRequest, Constraints, Traveler

llm = MockLLMClient({
    "rationale_summary": "Enough known information.",
    "final": {
        "findings": [{"category": "poi", "title": "玄武湖", "detail": "适合慢游", "source": "model"}],
        "covered_items": ["玄武湖"]
    }
})
agent = ResearcherAgent(llm)
res = agent.handle(AgentRequest(
    request_id="manual_react",
    agent="researcher",
    context={},
    params={
        "mode": "react_research",
        "constraints": Constraints(
            origin="杭州",
            destination="南京",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
            pace="slow",
            interests=["玄武湖"],
        ),
        "research_needs": [{"type": "poi_detail", "item": "玄武湖"}],
    },
))
print(res.status)
print(res.data.get("react"))
'@ | venv\Scripts\python.exe -
```

Expected: prints `success` and a `react` dict.

- [ ] **Step 6: Final commit**

Run:

```powershell
git status --short
git add travel_planning_agent/core/react_loop.py travel_planning_agent/agent/researcher.py travel_planning_agent/core/planning_runtime.py tests/test_react_loop.py tests/test_researcher_react.py tests/test_product_runtime.py
git commit -m "feat: add traceable react research loop"
```

Skip this commit if previous task commits already cover the final state.

---

## Self-Review

Spec coverage:
- The project gains a true ReAct-style `decision -> action -> observation -> final` loop.
- Existing planning architecture is preserved.
- Tool calls remain traceable through `tool_runtime.py` and additional `react_*` trace events.
- The loop is bounded by `max_steps` and `allowed_tools`.
- The implementation avoids storing hidden chain-of-thought by using `rationale_summary`.

Risk controls:
- Default chat behavior remains unchanged.
- ReAct is first available through explicit `mode="react_research"`.
- PlanningRuntime opt-in is a boolean flag, not a global default.
- Tests cover parser, loop behavior, unknown tools, max steps, trace events, Researcher integration, and runtime opt-in.

Type consistency:
- `ReActDecision`, `ReActStep`, and `ReActRunResult` names are used consistently across tests and implementation.
- `react` metadata returned by Researcher contains `status`, `steps`, and `covered_items`.
- Evidence conversion reuses `ResearcherAgent._finding_to_evidence`.
