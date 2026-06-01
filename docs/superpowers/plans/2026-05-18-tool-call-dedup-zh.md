# Tool Call Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为后端工具调用增加“同工具 + 同规范化参数”的精确去重，避免全局执行计划、Supervisor 预取等链路重复查询同一份数据，并在 trace 中记录复用证据。

**Architecture:** 新增一个小型 `tool_dedup` 核心模块，负责参数规范化、fingerprint 生成、registry 读写和 evidence 复用查询。`execute_execution_plan()` 接收可选共享 registry，执行任务前先查重，成功执行后写入 registry；`Supervisor._prefetch_shared_data()` 查天气前使用同一套 fingerprint 判断是否已由全局执行计划完成。第一版只做精确去重，不做语义相似去重。

**Tech Stack:** Python 3.11、pytest、现有 `PlanState.module_context`、现有 JSON trace (`travel_planning_agent.core.tracing`)。

---

## Scope

本计划只覆盖后端工具调用去重，不改前端，不改工具 API，不引入数据库表。

第一阶段去重范围：

- `travel_planning_agent.core.execution_executor.execute_execution_plan`
- `travel_planning_agent.agent.supervisor.SupervisorAgent._prefetch_shared_data`
- `travel_planning_agent.core.planning_runtime.PlanningRuntime.run` 在全局执行计划和 supervisor 之间传递 registry

暂不覆盖：

- LLM 自由生成的 ReAct 工具调用跨 agent 复用
- 语义相似参数合并，例如 “南京” 与 “南京市”
- 工具失败后的重试策略优化

---

## File Structure

- Create: `travel_planning_agent/core/tool_dedup.py`
  - 负责工具参数规范化、fingerprint、registry 读写。
  - 不依赖 agent，不调用真实工具。

- Modify: `travel_planning_agent/core/execution_executor.py`
  - `execute_execution_plan(plan, reuse_context=None)` 支持共享去重 registry。
  - 重复任务返回 `ExecutionResult(status="skipped_duplicate")`，复用已有 `evidence_ids`。

- Modify: `travel_planning_agent/core/planning_runtime.py`
  - 创建全局 `tool_call_registry`。
  - 调用全局执行计划时传入 registry。
  - 调用 supervisor 时把 registry 传入。

- Modify: `travel_planning_agent/agent/supervisor.py`
  - `run_planning_loop(..., tool_call_registry=None)` 接收并存入 `state.module_context["_tool_calls"]`。
  - `_prefetch_shared_data()` 查天气前先通过 fingerprint 查重；如果已有成功记录，直接跳过。
  - 预取成功后把天气调用写入 registry。

- Modify: `travel_planning_agent/types.py`
  - 不新增字段。继续使用 `PlanState.module_context` 保存 `_tool_calls`，避免扩大数据模型。

- Test: `tests/test_tool_dedup.py`
  - 覆盖 fingerprint 稳定性、参数顺序无关、registry 读写。

- Test: `tests/test_execution_plan.py`
  - 覆盖执行计划中重复任务只执行一次、第二个任务复用 evidence。

- Test: `tests/test_supervisor.py`
  - 覆盖已有全局天气工具调用时，`_prefetch_shared_data()` 不再调用 `execute_tool`。

- Test: `tests/test_product_runtime.py`
  - 覆盖 `PlanningRuntime` 将全局 execution registry 传给 supervisor。

---

## Data Shape

`PlanState.module_context["_tool_calls"]` 保存为普通 dict，方便 JSON 持久化：

```python
{
    "sha256:8d3c...": {
        "fingerprint": "sha256:8d3c...",
        "tool": "get_weather_forecast",
        "args": {"city": "南京", "date": "2026-05-18", "days": 2},
        "status": "success",
        "evidence_ids": ["ev_weather_123"],
        "task_id": "global_weather_nanjing_2026-05-18",
        "updated_at": "2026-05-18T10:00:00"
    }
}
```

重复调用的执行结果：

```python
ExecutionResult(
    task_id="weather_duplicate",
    status="skipped_duplicate",
    output=None,
    evidence_ids=["ev_weather_123"],
    error=None,
)
```

---

### Task 1: Add Tool Dedup Core Module

**Files:**
- Create: `travel_planning_agent/core/tool_dedup.py`
- Test: `tests/test_tool_dedup.py`

- [ ] **Step 1: Write failing tests for fingerprint and registry**

Create `tests/test_tool_dedup.py`:

```python
from datetime import date

from travel_planning_agent.core.tool_dedup import (
    find_tool_call,
    remember_tool_call,
    tool_call_fingerprint,
)


def test_tool_call_fingerprint_ignores_dict_arg_order():
    first = tool_call_fingerprint("get_weather_forecast", {"city": "南京", "days": 2, "date": "2026-05-18"})
    second = tool_call_fingerprint("get_weather_forecast", {"date": "2026-05-18", "city": "南京", "days": 2})

    assert first == second
    assert first.startswith("sha256:")


def test_tool_call_fingerprint_normalizes_dates_and_nested_values():
    first = tool_call_fingerprint("search_train", {"date": date(2026, 5, 18), "filters": {"seat": ["二等座", "一等座"]}})
    second = tool_call_fingerprint("search_train", {"filters": {"seat": ["二等座", "一等座"]}, "date": "2026-05-18"})

    assert first == second


def test_remember_and_find_tool_call_reuses_successful_evidence_ids():
    registry = {}
    fingerprint = remember_tool_call(
        registry,
        "get_weather_forecast",
        {"city": "南京", "date": "2026-05-18", "days": 2},
        status="success",
        evidence_ids=["ev_weather"],
        task_id="weather",
    )

    found = find_tool_call(registry, "get_weather_forecast", {"days": 2, "date": "2026-05-18", "city": "南京"})

    assert found["fingerprint"] == fingerprint
    assert found["status"] == "success"
    assert found["evidence_ids"] == ["ev_weather"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_tool_dedup.py -q --basetemp .tmp_pytest_run\pytest-tool-dedup-red
```

Expected: fail with `ModuleNotFoundError: No module named 'travel_planning_agent.core.tool_dedup'`.

- [ ] **Step 3: Implement minimal core module**

Create `travel_planning_agent/core/tool_dedup.py`:

```python
"""Exact tool-call deduplication helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, MutableMapping
from datetime import date, datetime
from typing import Any


REGISTRY_KEY = "_tool_calls"


def normalize_tool_args(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): normalize_tool_args(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
            if value[key] is not None
        }
    if isinstance(value, list):
        return [normalize_tool_args(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_tool_args(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def tool_call_fingerprint(tool_name: str, args: Mapping[str, Any] | None) -> str:
    payload = {
        "tool": tool_name,
        "args": normalize_tool_args(args or {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_tool_call_registry(context: MutableMapping[str, Any] | None) -> MutableMapping[str, dict]:
    if context is None:
        return {}
    registry = context.setdefault(REGISTRY_KEY, {})
    if not isinstance(registry, dict):
        registry = {}
        context[REGISTRY_KEY] = registry
    return registry


def find_tool_call(
    registry: Mapping[str, dict] | None,
    tool_name: str,
    args: Mapping[str, Any] | None,
) -> dict | None:
    if not registry:
        return None
    fingerprint = tool_call_fingerprint(tool_name, args)
    item = registry.get(fingerprint)
    if not isinstance(item, dict):
        return None
    if item.get("status") != "success":
        return None
    if not item.get("evidence_ids"):
        return None
    return item


def remember_tool_call(
    registry: MutableMapping[str, dict],
    tool_name: str,
    args: Mapping[str, Any] | None,
    *,
    status: str,
    evidence_ids: list[str] | None = None,
    task_id: str | None = None,
) -> str:
    fingerprint = tool_call_fingerprint(tool_name, args)
    registry[fingerprint] = {
        "fingerprint": fingerprint,
        "tool": tool_name,
        "args": normalize_tool_args(args or {}),
        "status": status,
        "evidence_ids": list(evidence_ids or []),
        "task_id": task_id,
        "updated_at": datetime.now().isoformat(),
    }
    return fingerprint
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_tool_dedup.py -q --basetemp .tmp_pytest_run\pytest-tool-dedup-green
```

Expected: `3 passed`.

---

### Task 2: Deduplicate Tasks Inside Execution Plans

**Files:**
- Modify: `travel_planning_agent/core/execution_executor.py`
- Test: `tests/test_execution_plan.py`

- [ ] **Step 1: Write failing test for duplicate execution task reuse**

Append to `tests/test_execution_plan.py`:

```python
def test_execute_execution_plan_skips_duplicate_tool_call_and_reuses_evidence(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_duplicate",
        scope="global",
        created_from={},
        tasks=[
            ExecutionTask(
                task_id="weather_a",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"city": "南京", "date": "2026-05-18", "days": 2},
            ),
            ExecutionTask(
                task_id="weather_b",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"days": 2, "city": "南京", "date": "2026-05-18"},
            ),
        ],
    )
    calls = []

    def fake_execute(name, args):
        calls.append((name, args))
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

    reuse_context = {}
    result = execute_execution_plan(plan, reuse_context=reuse_context)

    assert len(calls) == 1
    assert result["results"][0].status == "success"
    assert result["results"][1].status == "skipped_duplicate"
    assert result["results"][1].evidence_ids == result["results"][0].evidence_ids
    assert result["tasks"][1].status == "skipped_duplicate"
    assert result["evidence"][0]["claim"] == "南京小雨"
    assert len(result["evidence"]) == 1
    assert result["tool_calls"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py::test_execute_execution_plan_skips_duplicate_tool_call_and_reuses_evidence -q --basetemp .tmp_pytest_run\pytest-exec-dedup-red
```

Expected: fail with `TypeError: execute_execution_plan() got an unexpected keyword argument 'reuse_context'`.

- [ ] **Step 3: Update execution executor**

Modify `travel_planning_agent/core/execution_executor.py`:

```python
from collections.abc import MutableMapping
```

Add imports:

```python
from travel_planning_agent.core.tool_dedup import (
    find_tool_call,
    get_tool_call_registry,
    remember_tool_call,
)
```

Change signature and initialize registry:

```python
def execute_execution_plan(plan: ExecutionPlan, reuse_context: MutableMapping | None = None) -> dict:
    results: list[ExecutionResult] = []
    evidence: list[dict] = []
    has_required_error = False
    tool_calls = get_tool_call_registry(reuse_context)
```

Before `execute_registered_tool(...)`, add:

```python
        reused = find_tool_call(tool_calls, task.tool_name, task.args)
        if reused:
            task.status = "skipped_duplicate"
            task.evidence_ids = list(reused.get("evidence_ids") or [])
            result = ExecutionResult(
                task_id=task.task_id,
                status="skipped_duplicate",
                evidence_ids=list(task.evidence_ids),
            )
            results.append(result)
            _trace(
                "execution_task_skipped_duplicate",
                {
                    "plan_id": plan.plan_id,
                    "task_id": task.task_id,
                    "tool": task.tool_name,
                    "reused_evidence_ids": list(task.evidence_ids),
                    "fingerprint": reused.get("fingerprint"),
                },
            )
            continue
```

After successful task evidence is assigned, add:

```python
            remember_tool_call(
                tool_calls,
                task.tool_name,
                task.args,
                status="success",
                evidence_ids=list(task.evidence_ids),
                task_id=task.task_id,
            )
```

After failed task result is created, add:

```python
            remember_tool_call(
                tool_calls,
                task.tool_name,
                task.args,
                status="failed",
                evidence_ids=[],
                task_id=task.task_id,
            )
```

Return `tool_calls` in payload:

```python
        "tool_calls": tool_calls,
```

- [ ] **Step 4: Run execution plan tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_execution_plan.py tests\test_tool_dedup.py -q --basetemp .tmp_pytest_run\pytest-exec-dedup-green
```

Expected: all selected tests pass.

---

### Task 3: Skip Supervisor Weather Prefetch When Evidence Was Already Fetched

**Files:**
- Modify: `travel_planning_agent/agent/supervisor.py`
- Test: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing test for prefetch skip**

Append to `tests/test_supervisor.py`:

```python
def test_prefetch_shared_data_skips_duplicate_weather_tool_call(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.core.tool_dedup import get_tool_call_registry, remember_tool_call
    from travel_planning_agent.llm import MockLLMClient

    calls = []

    def fake_execute_tool(tool_name, args):
        calls.append((tool_name, args))
        return "should not be called"

    monkeypatch.setattr("travel_planning_agent.tools.execute_tool", fake_execute_tool)

    state = PlanState(
        trip_id="pref_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=5000,
        ),
    )
    registry = get_tool_call_registry(state.module_context)
    remember_tool_call(
        registry,
        "get_weather_forecast",
        {"city": "HZ", "date": "2026-05-01", "days": 2},
        status="success",
        evidence_ids=["ev_existing_weather"],
        task_id="global_weather",
    )

    supervisor = SupervisorAgent(MockLLMClient(), {})
    supervisor._prefetch_shared_data(state)

    assert calls == []
    assert state.evidence == {}
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_supervisor.py::test_prefetch_shared_data_skips_duplicate_weather_tool_call -q --basetemp .tmp_pytest_run\pytest-prefetch-dedup-red
```

Expected: fail because `_prefetch_shared_data()` still calls `execute_tool`.

- [ ] **Step 3: Update supervisor prefetch**

Modify imports inside `_prefetch_shared_data()`:

```python
        from travel_planning_agent.core.tool_dedup import (
            find_tool_call,
            get_tool_call_registry,
            remember_tool_call,
        )
```

After computing `destination`, `start_date`, and `days`, add:

```python
        weather_args = {"city": destination, "date": start_date, "days": days}
        tool_calls = get_tool_call_registry(state.module_context)
        reused = find_tool_call(tool_calls, "get_weather_forecast", weather_args)
        if reused:
            logger.info(
                "跳过天气预取，复用已有工具调用: %s evidence=%s",
                reused.get("fingerprint"),
                reused.get("evidence_ids"),
            )
            try:
                from travel_planning_agent.core.tracing import record_trace_event

                record_trace_event(
                    "prefetch_skipped_duplicate",
                    "supervisor",
                    {
                        "tool": "get_weather_forecast",
                        "args": weather_args,
                        "fingerprint": reused.get("fingerprint"),
                        "reused_evidence_ids": list(reused.get("evidence_ids") or []),
                    },
                )
            except Exception:
                pass
            return
```

Replace execute call:

```python
            result_text = execute_tool("get_weather_forecast", weather_args)
```

After writing `state.evidence[ev_id]`, add:

```python
        remember_tool_call(
            tool_calls,
            "get_weather_forecast",
            weather_args,
            status="success",
            evidence_ids=[ev_id],
            task_id="supervisor_prefetch_weather",
        )
```

- [ ] **Step 4: Run supervisor tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_supervisor.py -q --basetemp .tmp_pytest_run\pytest-prefetch-dedup-green
```

Expected: all supervisor tests pass.

---

### Task 4: Pass Tool Registry From PlanningRuntime To Supervisor

**Files:**
- Modify: `travel_planning_agent/core/planning_runtime.py`
- Modify: `travel_planning_agent/agent/supervisor.py`
- Test: `tests/test_product_runtime.py`

- [ ] **Step 1: Write failing runtime test**

Append to `tests/test_product_runtime.py`:

```python
def test_planning_runtime_passes_tool_call_registry_to_supervisor(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        from travel_planning_agent.core.tool_dedup import remember_tool_call

        remember_tool_call(
            reuse_context,
            "get_weather_forecast",
            {"city": "南京", "date": "2026-05-18", "days": 2},
            status="success",
            evidence_ids=["ev_weather"],
            task_id="global_weather",
        )
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
            "tool_calls": reuse_context,
        }

    class FakeSupervisor:
        def __init__(self, llm, agents):
            pass

        def run_planning_loop(self, constraints, initial_evidence=None, execution_plan=None, tool_call_registry=None):
            seen["tool_call_registry"] = tool_call_registry
            return PlanState(trip_id="trip_registry", constraints=constraints)

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
    )

    PlanningRuntime().run(spec, persist=False, use_execution_plan=True)

    assert seen["tool_call_registry"]
    assert list(seen["tool_call_registry"].values())[0]["evidence_ids"] == ["ev_weather"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_passes_tool_call_registry_to_supervisor -q --basetemp .tmp_pytest_run\pytest-runtime-dedup-red
```

Expected: fail because runtime does not yet pass `reuse_context` and `tool_call_registry`.

- [ ] **Step 3: Update supervisor signature and state storage**

Modify `travel_planning_agent/agent/supervisor.py`:

```python
    def run_planning_loop(
        self,
        constraints: Constraints,
        initial_evidence: list[dict] | None = None,
        execution_plan=None,
        tool_call_registry: dict | None = None,
    ) -> PlanState:
```

After existing `state.module_context["execution_plan"] = execution_plan.to_dict()`, add:

```python
        if tool_call_registry is not None:
            state.module_context["_tool_calls"] = tool_call_registry
```

- [ ] **Step 4: Update planning runtime**

Modify `travel_planning_agent/core/planning_runtime.py` before executing the global plan:

```python
        tool_call_registry = {}
```

Replace:

```python
            execution_result = execute_execution_plan(execution_plan)
```

with:

```python
            execution_result = execute_execution_plan(
                execution_plan,
                reuse_context=tool_call_registry,
            )
            tool_call_registry = execution_result.get("tool_calls") or tool_call_registry
```

Replace supervisor call:

```python
        state = supervisor.run_planning_loop(
            constraints,
            initial_evidence=initial_evidence,
            execution_plan=execution_plan,
            tool_call_registry=tool_call_registry,
        )
```

- [ ] **Step 5: Run runtime tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_product_runtime.py::test_planning_runtime_passes_tool_call_registry_to_supervisor tests\test_product_runtime.py::test_planning_runtime_executes_global_plan_and_passes_initial_evidence -q --basetemp .tmp_pytest_run\pytest-runtime-dedup-green
```

Expected: selected runtime tests pass.

---

### Task 5: Trace And Verification Pass

**Files:**
- Modify only if tests expose a real issue.
- Test: all backend tests.

- [ ] **Step 1: Run focused dedup suite**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_tool_dedup.py tests\test_execution_plan.py tests\test_supervisor.py tests\test_product_runtime.py -q --basetemp .tmp_pytest_run\pytest-tool-dedup-focused
```

Expected: selected tests pass.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_run\pytest-tool-dedup-full
```

Expected: full backend suite passes.

- [ ] **Step 3: Clean pytest temp directory**

Run:

```powershell
Remove-Item -Recurse -Force -LiteralPath .tmp_pytest_run -ErrorAction SilentlyContinue
```

- [ ] **Step 4: Restart backend and verify health**

Run:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 1 }
Start-Process -FilePath 'D:\Python_Project\RealTripAssistant\venv\Scripts\python.exe' -ArgumentList '-m','travel_planning_agent.main' -WorkingDirectory 'D:\Python_Project\RealTripAssistant' -WindowStyle Hidden
Start-Sleep -Seconds 3
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 10 | ConvertTo-Json -Depth 4
```

Expected:

```json
{
  "status": "ok",
  "version": "0.3.0",
  "llm_configured": true,
  "db_configured": true
}
```

---

## Self-Review

- Spec coverage: plan covers exact fingerprint dedup, evidence ID reuse, execution plan duplicate skip, supervisor weather prefetch skip, runtime registry handoff, and trace visibility.
- Placeholder scan: no `TBD`, `TODO`, or “implement later” remains.
- Type consistency: `tool_call_registry` is a plain dict stored under `PlanState.module_context["_tool_calls"]`; `execute_execution_plan()` returns the same registry under `result["tool_calls"]`; `ExecutionResult.status` uses string status and does not require enum changes.

