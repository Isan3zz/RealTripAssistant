# Researcher Dedup And Resume Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `ResearcherAgent` 复用全局工具去重 registry，并验证 `PlanState` 持久化与恢复后，重复工具调用仍会被正确跳过。

**Architecture:** 在现有 `tool_dedup` 的基础上继续向下游贯通，把 `state.module_context["_tool_calls"]` 传进 researcher 的执行计划，让 daily research 与 global execution plan、supervisor prefetch 共用一套 fingerprint registry。随后补一条“保存 state -> 恢复 state -> 再触发研究/预取”的验证链路，确认恢复后 dedup 仍然生效。

**Tech Stack:** Python 3.11、pytest、现有 `PlanState.module_context`、`file_store.py` 状态持久化、`tool_dedup.py`。

---

## Scope

本计划只覆盖后端去重链路和恢复验证，不改前端，不改数据库 schema，不做语义级去重。

本轮完成后应满足：

- `PlanningRuntime` 全局执行计划写入的 `_tool_calls` 可以继续被 researcher 使用
- `ResearcherAgent._parallel_research()` 对已执行过的同参数工具调用会直接复用 evidence
- `save_state()` / `load_state()` 往返后 `_tool_calls` 不丢失
- 恢复后的 `Supervisor._prefetch_shared_data()` 和 researcher 执行计划都能继续 dedup

---

## File Structure

- Modify: `travel_planning_agent/agent/researcher.py`
  - 接收共享 registry，并传给 `execute_execution_plan()`
  - 在返回数据里保留 `tool_calls` 或至少保证调用链可继续复用

- Modify: `travel_planning_agent/agent/supervisor.py`
  - 给 researcher 派发请求时注入共享 `_tool_calls`
  - 确保 state 生命周期内 registry 只维护一份

- Modify: `travel_planning_agent/storage/file_store.py`
  - 仅在测试暴露问题时调整；默认沿用 `module_context` 序列化

- Modify: `tests/test_researcher_execution_plan.py`
  - 覆盖 researcher 执行计划能接收并复用外部 registry

- Create: `tests/test_tool_dedup_resume.py`
  - 覆盖保存/恢复 state 后 `_tool_calls` 仍存在
  - 覆盖恢复后的 prefetch / researcher dedup

- Modify: `tests/test_supervisor.py`
  - 如有需要，补一条恢复后天气预取跳过的状态级测试

---

## Shared Registry Contract

共享 registry 继续使用：

```python
state.module_context["_tool_calls"]
```

researcher 请求参数新增约定：

```python
{
    "constraints": constraints,
    "research_needs": [...],
    "tool_call_registry": state.module_context.get("_tool_calls", {}),
}
```

researcher 执行时：

```python
execution_result = execute_execution_plan(
    execution_plan,
    reuse_context=tool_call_registry,
)
```

其中 `tool_call_registry` 必须是同一个可变 dict，而不是浅拷贝，这样执行后写入的 fingerprint 才会回流到 `state.module_context`。

---

### Task 1: Thread Shared Tool Registry Into Researcher Requests

**Files:**
- Modify: `travel_planning_agent/agent/supervisor.py`
- Modify: `travel_planning_agent/agent/researcher.py`
- Test: `tests/test_researcher_execution_plan.py`

- [ ] **Step 1: Write a failing test for researcher registry reuse**

Append to `tests/test_researcher_execution_plan.py`:

```python
def test_parallel_research_reuses_shared_tool_call_registry(monkeypatch):
    seen = {}

    def fake_execute(plan, reuse_context=None):
        seen["reuse_context"] = reuse_context
        return {
            "status": "completed",
            "plan": plan,
            "tasks": plan.tasks,
            "results": [],
            "evidence": [],
            "tool_calls": reuse_context,
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
    registry = {
        "sha256:weather": {
            "fingerprint": "sha256:weather",
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18", "days": 2},
            "status": "success",
            "evidence_ids": ["ev_weather"],
            "task_id": "global_weather",
            "updated_at": "2026-05-18T00:00:00",
        }
    }
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    response = agent.handle(AgentRequest(
        request_id="req_reuse_registry",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))

    assert response.status == "degraded" or response.status == "success"
    assert seen["reuse_context"] is registry
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py::test_parallel_research_reuses_shared_tool_call_registry -q --basetemp .tmp_pytest_run\pytest-researcher-registry-red
```

Expected: fail because `execute_execution_plan()` is currently called without `reuse_context`.

- [ ] **Step 3: Pass the shared registry through supervisor and researcher**

Modify `travel_planning_agent/agent/supervisor.py` where it dispatches researcher requests so `params` includes:

```python
"tool_call_registry": state.module_context.get("_tool_calls", {}),
```

Modify `travel_planning_agent/agent/researcher.py` inside `_parallel_research()`:

```python
        tool_call_registry = params.get("tool_call_registry")
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
```

If `execution_result` contains `tool_calls`, preserve it in the response:

```python
                    "tool_calls": execution_result.get("tool_calls") or tool_call_registry,
```

- [ ] **Step 4: Run the researcher execution-plan tests**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py -q --basetemp .tmp_pytest_run\pytest-researcher-registry-green
```

Expected: all selected tests pass.

---

### Task 2: Ensure Researcher Actually Skips Duplicate Calls When Registry Is Warm

**Files:**
- Modify: `tests/test_researcher_execution_plan.py`
- Modify only if test exposes a bug: `travel_planning_agent/agent/researcher.py`

- [ ] **Step 1: Write a failing duplicate-skip test**

Append to `tests/test_researcher_execution_plan.py`:

```python
def test_parallel_research_skips_duplicate_tool_call_from_shared_registry(monkeypatch):
    calls = []

    def fake_execute(plan, reuse_context=None):
        from travel_planning_agent.core.execution_executor import execute_execution_plan
        return execute_execution_plan(plan, reuse_context=reuse_context)

    def fake_registered_tool(name, args):
        calls.append((name, args))
        return ToolResult(
            status="success",
            data="玄武湖免费",
            evidence=[{
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_registered_tool)
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
    registry = {}
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    first = agent.handle(AgentRequest(
        request_id="req_first",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))
    second = agent.handle(AgentRequest(
        request_id="req_second",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))

    assert first.status == "success"
    assert second.status == "success"
    assert len(calls) == 1
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py::test_parallel_research_skips_duplicate_tool_call_from_shared_registry -q --basetemp .tmp_pytest_run\pytest-researcher-dedup-red
```

Expected: fail because registry is not yet threaded through researcher.

- [ ] **Step 3: Fix any mismatch exposed by the test**

If the test fails after Task 1 due to fallback behavior or response shape, keep changes minimal:

- Preserve `execution_result["tool_calls"]`
- Avoid copying the registry
- Do not clear `tool_call_registry` between requests

- [ ] **Step 4: Re-run the selected test**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_researcher_execution_plan.py::test_parallel_research_skips_duplicate_tool_call_from_shared_registry -q --basetemp .tmp_pytest_run\pytest-researcher-dedup-green
```

Expected: pass with exactly one tool execution across two researcher runs.

---

### Task 3: Add State Persistence And Resume Coverage For `_tool_calls`

**Files:**
- Create: `tests/test_tool_dedup_resume.py`
- Modify only if needed: `travel_planning_agent/storage/file_store.py`

- [ ] **Step 1: Write failing state round-trip tests**

Create `tests/test_tool_dedup_resume.py`:

```python
from datetime import date

from travel_planning_agent.storage.file_store import load_state, save_state
from travel_planning_agent.types import Constraints, PlanState, Traveler


def test_tool_call_registry_survives_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_planning_agent.config.settings.data_dir", str(tmp_path))

    state = PlanState(
        trip_id="trip_resume_dedup",
        constraints=Constraints(
            destination="南京",
            origin="杭州",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
        ),
    )
    state.module_context["_tool_calls"] = {
        "sha256:weather": {
            "fingerprint": "sha256:weather",
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18", "days": 2},
            "status": "success",
            "evidence_ids": ["ev_weather"],
            "task_id": "global_weather",
            "updated_at": "2026-05-18T00:00:00",
        }
    }

    save_state(state)
    loaded = load_state("trip_resume_dedup")

    assert loaded is not None
    assert loaded.module_context["_tool_calls"]["sha256:weather"]["evidence_ids"] == ["ev_weather"]
```

- [ ] **Step 2: Run the test and verify it fails if serialization drops the registry**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_tool_dedup_resume.py::test_tool_call_registry_survives_save_and_load -q --basetemp .tmp_pytest_run\pytest-resume-red
```

Expected: either pass immediately or fail with missing `_tool_calls`.

- [ ] **Step 3: Adjust storage only if needed**

If the test fails, keep the fix minimal in `travel_planning_agent/storage/file_store.py`:

- Preserve `module_context` as-is in `_plan_state_to_dict()`
- Preserve `module_context` as-is in `load_state()`
- Do not coerce inner dict types

- [ ] **Step 4: Run the resume test again**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_tool_dedup_resume.py -q --basetemp .tmp_pytest_run\pytest-resume-green
```

Expected: selected tests pass.

---

### Task 4: Verify Restored State Still Deduplicates Prefetch And Research

**Files:**
- Modify: `tests/test_tool_dedup_resume.py`
- Modify only if needed: `travel_planning_agent/agent/supervisor.py`, `travel_planning_agent/agent/researcher.py`

- [ ] **Step 1: Write a failing restored-prefetch test**

Append to `tests/test_tool_dedup_resume.py`:

```python
def test_restored_state_skips_weather_prefetch(monkeypatch):
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient

    calls = []

    def fake_execute_tool(tool_name, args):
        calls.append((tool_name, args))
        return "should not be called"

    monkeypatch.setattr("travel_planning_agent.tools.execute_tool", fake_execute_tool)

    state = PlanState(
        trip_id="trip_restore_prefetch",
        constraints=Constraints(
            destination="南京",
            origin="杭州",
            start_date=date(2026, 5, 18),
            days=2,
            travelers=[Traveler(age_group="adult")],
            budget=2000,
        ),
    )
    state.module_context["_tool_calls"] = {
        "sha256:weather": {
            "fingerprint": "sha256:weather",
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18", "days": 2},
            "status": "success",
            "evidence_ids": ["ev_weather"],
            "task_id": "global_weather",
            "updated_at": "2026-05-18T00:00:00",
        }
    }

    SupervisorAgent(MockLLMClient(), {})._prefetch_shared_data(state)

    assert calls == []
```

- [ ] **Step 2: Write a failing restored-researcher test**

Append to `tests/test_tool_dedup_resume.py`:

```python
def test_restored_registry_skips_duplicate_research_tool_call(monkeypatch):
    from travel_planning_agent.agent.researcher import ResearcherAgent
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.types import AgentRequest, ToolResult

    calls = []

    def fake_registered_tool(name, args):
        calls.append((name, args))
        return ToolResult(
            status="success",
            data="玄武湖免费",
            evidence=[{
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_registered_tool)

    constraints = Constraints(
        destination="南京",
        origin="杭州",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        interests=["玄武湖"],
    )
    registry = {}
    agent = ResearcherAgent(MockLLMClient({"findings": []}))

    first = agent.handle(AgentRequest(
        request_id="restore_first",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))
    second = agent.handle(AgentRequest(
        request_id="restore_second",
        agent="researcher",
        context={},
        params={
            "constraints": constraints,
            "research_needs": [{"type": "ticket_price", "item": "玄武湖"}],
            "tool_call_registry": registry,
        },
    ))

    assert first.status == "success"
    assert second.status == "success"
    assert len(calls) == 1
```

- [ ] **Step 3: Run the new resume-focused suite**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests\test_tool_dedup_resume.py tests\test_researcher_execution_plan.py tests\test_supervisor.py -q --basetemp .tmp_pytest_run\pytest-resume-dedup-green
```

Expected: selected tests pass.

---

### Task 5: Full Verification

**Files:**
- Modify only if tests expose a real integration issue.

- [ ] **Step 1: Run focused suite**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest_run'
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
venv\Scripts\python.exe -m pytest tests\test_tool_dedup.py tests\test_tool_dedup_resume.py tests\test_researcher_execution_plan.py tests\test_execution_plan.py tests\test_supervisor.py tests\test_product_runtime.py -q --basetemp .tmp_pytest_run\pytest-researcher-dedup-focused
```

Expected: focused dedup suite passes.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_run\pytest-researcher-dedup-full
```

Expected: full backend suite passes.

- [ ] **Step 3: Clean temporary test directory**

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

- Spec coverage: plan covers registry handoff to researcher, duplicate-skip validation inside researcher, save/load persistence of `_tool_calls`, and restored-state dedup verification.
- Placeholder scan: no `TODO`, `TBD`, or vague “handle later” steps remain.
- Type consistency: shared registry stays a plain dict under `module_context["_tool_calls"]`; `execute_execution_plan(..., reuse_context=...)` remains the single integration seam; tests use existing `ToolResult`, `PlanState`, and `AgentRequest` shapes.

