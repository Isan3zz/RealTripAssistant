# Decoupling Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the current `core / agent / llm / tools / api` coupling by extracting a composition root, slimming `SupervisorAgent` and `ChatService`, and splitting the tool-calling loop out of `llm.py` without changing user-facing behavior.

**Architecture:** Keep the existing product behavior, test suite, and four-agent mental model, but move object creation into a runtime composition layer, move pipeline and chat subflows into narrower services, and isolate the LLM transport from tool execution. Each task leaves the codebase in a shippable state and adds tests that pin the new boundary so the code does not drift back into central god classes.

**Tech Stack:** Python 3.11, pytest, FastAPI, SQLAlchemy, existing `PlanRunService` / `PlanningRuntime` / `SupervisorAgent` / `ChatService`, existing `MockLLMClient`, existing tool registry and tracing helpers.

---

## Planned File Structure

- Create: `travel_planning_agent/runtime/__init__.py`
  - Runtime composition package marker and exports.
- Create: `travel_planning_agent/runtime/composition.py`
  - Builds `SupervisorAgent` and its collaborators from an LLM client.
- Modify: `travel_planning_agent/core/plan_run_service.py`
  - Stop instantiating concrete agents directly; consume the composition seam.
- Test: `tests/test_product_runtime.py`
  - Pin that `PlanRunService` now delegates assembly to the composition layer.

- Create: `travel_planning_agent/core/planning_state_service.py`
  - Owns repeated `PlanState` mutations used by the daily planning pipeline.
- Modify: `travel_planning_agent/core/daily_pipeline.py`
  - Move state-write helpers out of `SupervisorAgent`.
- Modify: `travel_planning_agent/agent/supervisor.py`
  - Keep dispatch/degrade logic and hand state mutation to the new state service.
- Test: `tests/test_supervisor.py`
  - Pin the new slimmer supervisor boundary.

- Create: `travel_planning_agent/core/chat_revision_service.py`
  - Owns revision detection + revision application flow.
- Create: `travel_planning_agent/core/chat_runtime_service.py`
  - Owns intake branching and successful planning flow.
- Modify: `travel_planning_agent/core/chat_service.py`
  - Become a thin entrypoint that coordinates the extracted services.
- Test: `tests/test_chat_service.py`
  - Cover both follow-up and revision paths through service seams.

- Create: `travel_planning_agent/core/tool_calling_service.py`
  - Owns the tool-calling loop and tool result replay into model messages.
- Modify: `travel_planning_agent/llm.py`
  - Limit it to transport and response parsing concerns.
- Test: `tests/test_react_loop.py`
  - Reuse existing loop-style tests to pin extracted tool-calling behavior.
- Test: `tests/test_product_runtime.py`
  - Verify the planner runtime still succeeds with the new tool-calling seam.

- Modify: `travel_planning_agent/api/chat.py`
  - Keep route transport-only and continue delegating to `ChatService`.
- Test: `tests/test_chat_api.py`
  - Confirm the HTTP boundary remains stable after the internal refactor.

---

### Task 1: Add a Runtime Composition Root

**Files:**
- Create: `travel_planning_agent/runtime/__init__.py`
- Create: `travel_planning_agent/runtime/composition.py`
- Modify: `travel_planning_agent/core/plan_run_service.py`
- Test: `tests/test_product_runtime.py`

- [ ] **Step 1: Write the failing composition-boundary test**

Add this test to `tests/test_product_runtime.py`:

```python
def test_plan_run_service_builds_supervisor_via_composition_root(monkeypatch):
    from datetime import date

    from travel_planning_agent.core.plan_run_service import PlanRunService
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.types import PlanState, TripSpec, Traveler

    seen = {}

    class FakeSupervisor:
        def run_planning_loop(self, constraints, **kwargs):
            seen["constraints"] = constraints
            return PlanState(trip_id="trip_from_composition", constraints=constraints)

    def fake_build_planning_supervisor(llm_client, use_react_research=False):
        seen["llm_client"] = llm_client
        seen["use_react_research"] = use_react_research
        return FakeSupervisor()

    monkeypatch.setattr(
        "travel_planning_agent.runtime.composition.build_planning_supervisor",
        fake_build_planning_supervisor,
    )

    spec = TripSpec(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 19),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=3000,
        pace="slow",
    )

    service = PlanRunService(db=None, llm_client=MockLLMClient())
    result = service.run(spec, persist=False, use_execution_plan=False, use_react_research=True)

    assert seen["llm_client"] is service.llm
    assert seen["use_react_research"] is True
    assert result["trip_id"] == "trip_from_composition"
```

- [ ] **Step 2: Run the targeted runtime test to verify it fails**

Run:

```bash
pytest tests/test_product_runtime.py::test_plan_run_service_builds_supervisor_via_composition_root -v
```

Expected: FAIL because `travel_planning_agent.runtime.composition.build_planning_supervisor` does not exist and `PlanRunService` still imports concrete agents directly.

- [ ] **Step 3: Create the composition module**

Create `travel_planning_agent/runtime/__init__.py`:

```python
from travel_planning_agent.runtime.composition import build_planning_supervisor

__all__ = ["build_planning_supervisor"]
```

Create `travel_planning_agent/runtime/composition.py`:

```python
from travel_planning_agent.agent.planner import PlannerAgent
from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.agent.supervisor import SupervisorAgent
from travel_planning_agent.agent.verifier import VerifierAgent


def build_planning_supervisor(llm_client, use_react_research: bool = False) -> SupervisorAgent:
    researcher = ResearcherAgent(llm_client)
    researcher.use_react_research = use_react_research
    return SupervisorAgent(
        llm_client,
        {
            "researcher": researcher,
            "planner": PlannerAgent(llm_client),
            "verifier": VerifierAgent(llm_client),
        },
    )
```

- [ ] **Step 4: Update `PlanRunService` to consume the composition seam**

Modify `travel_planning_agent/core/plan_run_service.py` imports and planning block:

```python
from travel_planning_agent.runtime.composition import build_planning_supervisor
```

Replace the direct agent instantiation block inside `PlanRunService.run()` with:

```python
supervisor = build_planning_supervisor(
    self.llm,
    use_react_research=use_react_research,
)

state = supervisor.run_planning_loop(
    constraints,
    initial_evidence=initial_evidence,
    execution_plan=execution_plan,
    tool_call_registry=tool_call_registry,
)
```

Delete these direct imports from inside `run()`:

```python
from travel_planning_agent.agent.planner import PlannerAgent
from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.agent.supervisor import SupervisorAgent
from travel_planning_agent.agent.verifier import VerifierAgent
```

- [ ] **Step 5: Re-run the focused runtime tests**

Run:

```bash
pytest tests/test_product_runtime.py::test_plan_run_service_builds_supervisor_via_composition_root -v
pytest tests/test_product_runtime.py::test_plan_run_service_persists_failed_run_status -v
pytest tests/test_product_runtime.py::test_plan_run_service_finalizes_failed_run_when_execution_plan_raises -v
```

Expected: PASS. The new seam test passes and existing runtime failure handling stays green.

- [ ] **Step 6: Commit**

```bash
git add travel_planning_agent/runtime/__init__.py travel_planning_agent/runtime/composition.py travel_planning_agent/core/plan_run_service.py tests/test_product_runtime.py
git commit -m "refactor: add runtime composition root"
```

---

### Task 2: Extract `PlanState` Mutation Helpers From `SupervisorAgent`

**Files:**
- Create: `travel_planning_agent/core/planning_state_service.py`
- Modify: `travel_planning_agent/core/daily_pipeline.py`
- Modify: `travel_planning_agent/agent/supervisor.py`
- Test: `tests/test_supervisor.py`

- [ ] **Step 1: Write the failing state-service seam test**

Add this test to `tests/test_supervisor.py`:

```python
def test_daily_pipeline_prefetch_delegates_state_write_to_state_service(monkeypatch):
    from datetime import date

    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.llm import MockLLMClient
    from travel_planning_agent.types import Constraints, PlanState, Traveler

    writes = []

    class FakePlanningStateService:
        def remember_prefetched_weather(self, state, weather_text):
            writes.append((state.trip_id, weather_text))

    monkeypatch.setattr(
        "travel_planning_agent.core.daily_pipeline.PlanningStateService",
        lambda: FakePlanningStateService(),
    )
    monkeypatch.setattr(
        "travel_planning_agent.tools.execute_tool",
        lambda tool_name, args: "【天气】HZ：\\n- 2026-05-01 晴/晴",
    )

    state = PlanState(
        trip_id="state_service_trip",
        constraints=Constraints(
            destination="HZ",
            origin="NJ",
            start_date=date(2026, 5, 1),
            days=1,
            travelers=[Traveler(age_group="adult")],
            budget=1000,
        ),
    )

    supervisor = SupervisorAgent(MockLLMClient(), {})
    supervisor._prefetch_shared_data(state)

    assert writes == [("state_service_trip", "【天气】HZ：\\n- 2026-05-01 晴/晴")]
```

- [ ] **Step 2: Run the targeted supervisor seam test to verify it fails**

Run:

```bash
pytest tests/test_supervisor.py::test_daily_pipeline_prefetch_delegates_state_write_to_state_service -v
```

Expected: FAIL because `PlanningStateService` does not exist and `_prefetch_shared_data()` still mutates `PlanState` directly.

- [ ] **Step 3: Create the state service**

Create `travel_planning_agent/core/planning_state_service.py`:

```python
from datetime import datetime

from travel_planning_agent.types import Evidence


class PlanningStateService:
    def remember_prefetched_weather(self, state, weather_text: str) -> None:
        if not weather_text:
            return
        state.evidence[f"{state.trip_id}_pref_weather"] = Evidence(
            evidence_id=f"{state.trip_id}_pref_weather",
            source="get_weather_forecast",
            source_type="api",
            confidence="high",
            claim=weather_text,
            retrieved_at=datetime.now().isoformat(),
        )
```

- [ ] **Step 4: Use the state service in the daily pipeline**

Modify `travel_planning_agent/core/daily_pipeline.py` to import and own the state service:

```python
from travel_planning_agent.core.planning_state_service import PlanningStateService


class DailyPipelineRunner:
    def __init__(self, supervisor):
        self.supervisor = supervisor
        self.state_service = PlanningStateService()
```

Replace the direct evidence write in the weather prefetch path with:

```python
self.state_service.remember_prefetched_weather(state, weather_text)
```

Modify `travel_planning_agent/agent/supervisor.py` so `_prefetch_shared_data()` delegates to `DailyPipelineRunner(self)._prefetch_shared_data(state)` instead of owning the state write itself:

```python
def _prefetch_shared_data(self, state):
    from travel_planning_agent.core.daily_pipeline import DailyPipelineRunner

    runner = DailyPipelineRunner(self)
    return runner._prefetch_shared_data(state)
```

- [ ] **Step 5: Re-run the supervisor tests**

Run:

```bash
pytest tests/test_supervisor.py::test_prefetch_shared_data_only_fetches_weather -v
pytest tests/test_supervisor.py::test_prefetch_shared_data_skips_duplicate_weather_tool_call -v
pytest tests/test_supervisor.py::test_daily_pipeline_prefetch_delegates_state_write_to_state_service -v
```

Expected: PASS. Existing prefetch behavior survives, and the new test proves state writes now flow through the state service seam.

- [ ] **Step 6: Commit**

```bash
git add travel_planning_agent/core/planning_state_service.py travel_planning_agent/core/daily_pipeline.py travel_planning_agent/agent/supervisor.py tests/test_supervisor.py
git commit -m "refactor: extract planning state mutations"
```

---

### Task 3: Split Revision and Runtime Branches Out of `ChatService`

**Files:**
- Create: `travel_planning_agent/core/chat_revision_service.py`
- Create: `travel_planning_agent/core/chat_runtime_service.py`
- Modify: `travel_planning_agent/core/chat_service.py`
- Test: `tests/test_chat_service.py`

- [ ] **Step 1: Write the failing revision-service test**

Append this test to `tests/test_chat_service.py`:

```python
def test_chat_service_uses_revision_service_before_intake(monkeypatch):
    from travel_planning_agent.core.chat_service import ChatService, ChatServiceResult

    class FakeRevisionService:
        def try_handle_revision(self, session_id, message, context, trace_id):
            return ChatServiceResult(
                type="plan",
                content="已按要求修改行程",
                trip_id="trip_revision",
                session_id=session_id,
            )

    class FakeSessionStore:
        def load_context(self, session_id):
            return {"extracted": {}, "messages": []}

        def remember_trace_id(self, context, trace_id):
            context["trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, kind=None):
            context.setdefault("messages", []).append((role, content, kind))

        def save_context(self, session_id, context):
            context["saved"] = session_id

    service = ChatService(
        db=None,
        session_store=FakeSessionStore(),
    )
    service.revision_service = FakeRevisionService()

    result = service.handle_message("把第二天下午改成博物馆", session_id="sess_rev")

    assert result.type == "plan"
    assert result.trip_id == "trip_revision"
    assert result.content == "已按要求修改行程"
```

- [ ] **Step 2: Run the targeted chat test to verify it fails**

Run:

```bash
pytest tests/test_chat_service.py::test_chat_service_uses_revision_service_before_intake -v
```

Expected: FAIL because `ChatService` has no `revision_service` seam and still owns the revision branch directly.

- [ ] **Step 3: Create the revision service**

Create `travel_planning_agent/core/chat_revision_service.py`:

```python
from travel_planning_agent.core.plan_revision import looks_like_plan_revision


class ChatRevisionService:
    def __init__(self, owner):
        self.owner = owner

    def try_handle_revision(self, session_id, message, context, trace_id):
        if not looks_like_plan_revision(message, context):
            return None
        return self.owner._try_apply_plan_revision(session_id, message, context)
```

- [ ] **Step 4: Create the runtime branch service**

Create `travel_planning_agent/core/chat_runtime_service.py`:

```python
from travel_planning_agent.types import AgentRequest


class ChatRuntimeService:
    def __init__(self, owner):
        self.owner = owner

    def run_intake(self, llm, message: str, extracted: dict):
        intake = self.owner.intake_agent_factory(llm)
        intake_request = AgentRequest(
            request_id=self.owner._build_intake_request_id(),
            agent="intake",
            context={},
            params={"message": message, "extracted": extracted},
        )
        return intake.handle(intake_request)
```

- [ ] **Step 5: Refactor `ChatService` to use the new seams**

Modify `travel_planning_agent/core/chat_service.py` constructor:

```python
from travel_planning_agent.core.chat_revision_service import ChatRevisionService
from travel_planning_agent.core.chat_runtime_service import ChatRuntimeService
```

Inside `ChatService.__init__()` add:

```python
self.intake_agent_factory = intake_agent_factory or (lambda llm_client: __import__(
    "travel_planning_agent.agent.intake",
    fromlist=["IntakeAgent"],
).IntakeAgent(llm_client))
self.revision_service = ChatRevisionService(self)
self.runtime_service = ChatRuntimeService(self)
```

Add helper:

```python
def _build_intake_request_id(self) -> str:
    return f"intake_{uuid.uuid4().hex[:8]}"
```

Replace the revision branch in `handle_message()` with:

```python
revised = self.revision_service.try_handle_revision(session_id, message, context, trace_id)
if revised:
    self.session_store.append_message(context, "assistant", revised.content, "plan")
    context["last_response"] = {
        "type": "plan",
        "content": revised.content,
        "trip_id": revised.trip_id,
    }
    self.session_store.save_context(session_id, context)
    record_trace_event(
        "revision_applied",
        "revision",
        {
            "message": message,
            "trip_id": revised.trip_id,
            "plan_summary": revised.plan_summary,
        },
        trace_id=trace_id,
        session_id=session_id,
        trip_id=revised.trip_id,
    )
    return revised
```

Replace the direct intake construction with:

```python
intake_resp = self.runtime_service.run_intake(llm, message, extracted)
```

- [ ] **Step 6: Re-run the chat service tests**

Run:

```bash
pytest tests/test_chat_service.py -v
pytest tests/test_chat_api.py -v
```

Expected: PASS. Existing follow-up behavior remains stable, and the revision path now has an explicit service seam.

- [ ] **Step 7: Commit**

```bash
git add travel_planning_agent/core/chat_revision_service.py travel_planning_agent/core/chat_runtime_service.py travel_planning_agent/core/chat_service.py tests/test_chat_service.py tests/test_chat_api.py
git commit -m "refactor: split chat revision and runtime branches"
```

---

### Task 4: Extract the Tool-Calling Loop From `llm.py`

**Files:**
- Create: `travel_planning_agent/core/tool_calling_service.py`
- Modify: `travel_planning_agent/llm.py`
- Modify: `tests/test_react_loop.py`
- Modify: `tests/test_product_runtime.py`

- [ ] **Step 1: Write the failing tool-loop extraction test**

Add this test to `tests/test_product_runtime.py`:

```python
def test_openai_client_generate_delegates_tool_loop_to_tool_calling_service(monkeypatch):
    from travel_planning_agent.llm import OpenAICompatibleClient

    seen = {}

    class FakeToolCallingService:
        def run_loop(self, client, model, messages, tools):
            seen["client"] = client
            seen["model"] = model
            seen["messages"] = messages
            seen["tools"] = tools
            return {
                "success": True,
                "data": {"ok": True},
                "text": '{"ok": true}',
                "tokens_used": 12,
                "tool_calls_log": [],
            }

    monkeypatch.setattr(
        "travel_planning_agent.llm.ToolCallingService",
        lambda: FakeToolCallingService(),
    )

    openai_client = OpenAICompatibleClient(base_url="http://example.com/v1", api_key="k", model="m")
    monkeypatch.setattr(openai_client, "_get_client", lambda: object())

    result = openai_client.generate("system prompt", "user prompt", tools=[{"type": "function"}])

    assert seen["model"] == "m"
    assert seen["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert result.success is True
    assert result.data == {"ok": True}
```

- [ ] **Step 2: Run the focused tool-loop test to verify it fails**

Run:

```bash
pytest tests/test_product_runtime.py::test_openai_client_generate_delegates_tool_loop_to_tool_calling_service -v
```

Expected: FAIL because `ToolCallingService` does not exist and `OpenAICompatibleClient.generate()` still owns the loop inline.

- [ ] **Step 3: Create the tool-calling service**

Create `travel_planning_agent/core/tool_calling_service.py`:

```python
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from travel_planning_agent.tools import execute_tool

logger = logging.getLogger(__name__)


class ToolCallingService:
    def run_loop(self, client, model, messages, tools):
        total_tokens = 0
        tool_calls_log = []
        max_rounds = 25

        for _ in range(max_rounds):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools if tools else None,
                max_tokens=4096,
            )
            choice = response.choices[0]
            message = choice.message

            if response.usage:
                total_tokens += (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

            if not message.tool_calls:
                return {
                    "success": True,
                    "data": None,
                    "text": message.content or "",
                    "tokens_used": total_tokens,
                    "tool_calls_log": tool_calls_log,
                }

            assistant_msg = {"role": "assistant", "content": message.content or "", "tool_calls": []}
            tc_list = []
            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_input = {}
                assistant_msg["tool_calls"].append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": tc.function.arguments},
                    }
                )
                tc_list.append((tc.id, tool_name, tool_input))

            results = {}
            with ThreadPoolExecutor(max_workers=min(len(tc_list), 5)) as executor:
                fut_map = {executor.submit(execute_tool, name, args): (tc_id, name, args) for tc_id, name, args in tc_list}
                for fut in as_completed(fut_map):
                    tc_id, tool_name, tool_input = fut_map[fut]
                    try:
                        results[tc_id] = fut.result()
                    except Exception as exc:
                        logger.warning("tool call failed: %s", exc)
                        results[tc_id] = f"{tool_name}: 执行异常 - {exc}"

            messages.append(assistant_msg)
            for tc_id, tool_name, tool_input in tc_list:
                tool_result = results.get(tc_id, "查询失败")
                tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": tool_result[:500]})
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_result})

        return {
            "success": False,
            "error": "工具调用超过最大轮数（25 轮）",
            "tokens_used": total_tokens,
            "tool_calls_log": tool_calls_log,
        }
```

- [ ] **Step 4: Refactor `llm.py` to consume the tool-calling service**

Modify `travel_planning_agent/llm.py` imports:

```python
from travel_planning_agent.core.tool_calling_service import ToolCallingService
```

Inside `OpenAICompatibleClient.generate()` replace the inline loop with:

```python
client = self._get_client()
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_message},
]

service = ToolCallingService()
loop_result = service.run_loop(client, self.model, messages, tools)
if not loop_result.get("success"):
    return LLMResult(
        success=False,
        error=loop_result.get("error"),
        tokens_used=loop_result.get("tokens_used", 0),
        tool_calls_log=loop_result.get("tool_calls_log", []),
    )

parsed = self._extract_json(loop_result.get("text", ""))
return LLMResult(
    success=True,
    data=parsed,
    text=loop_result.get("text", ""),
    tokens_used=loop_result.get("tokens_used", 0),
    tool_calls_log=loop_result.get("tool_calls_log", []),
)
```

Delete the direct import:

```python
from travel_planning_agent.tools import execute_tool
```

- [ ] **Step 5: Re-run the focused LLM and runtime tests**

Run:

```bash
pytest tests/test_product_runtime.py::test_openai_client_generate_delegates_tool_loop_to_tool_calling_service -v
pytest tests/test_react_loop.py -v
pytest tests/test_product_runtime.py -v
```

Expected: PASS. The tool loop has its own seam, and runtime behavior remains green.

- [ ] **Step 6: Commit**

```bash
git add travel_planning_agent/core/tool_calling_service.py travel_planning_agent/llm.py tests/test_react_loop.py tests/test_product_runtime.py
git commit -m "refactor: extract llm tool calling loop"
```

---

### Task 5: Keep `/api/chat` Transport-Only and Re-verify the Public Surface

**Files:**
- Modify: `travel_planning_agent/api/chat.py`
- Test: `tests/test_chat_api.py`

- [ ] **Step 1: Write the transport-boundary test**

Add this test to `tests/test_chat_api.py`:

```python
def test_chat_route_only_maps_service_result(monkeypatch):
    from fastapi.testclient import TestClient

    from travel_planning_agent.api.app import app

    class FakeChatServiceResult:
        type = "question"
        content = "请补充出发日期"
        trip_id = None
        plan_summary = None
        session_id = "sess_route"

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        def handle_message(self, message, session_id=None):
            assert message == "去南京"
            assert session_id == "sess_route"
            return FakeChatServiceResult()

    monkeypatch.setattr("travel_planning_agent.api.chat.ChatService", FakeChatService)

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "去南京", "session_id": "sess_route"})

    assert response.status_code == 200
    assert response.json() == {
        "type": "question",
        "content": "请补充出发日期",
        "trip_id": None,
        "plan_summary": None,
        "session_id": "sess_route",
    }
```

- [ ] **Step 2: Run the focused API test to verify it passes before any route change**

Run:

```bash
pytest tests/test_chat_api.py::test_chat_route_only_maps_service_result -v
```

Expected: PASS or near-pass with tiny fixture adjustments. If it fails, fix the test fixture first so it reflects the real app wiring before refactoring route code.

- [ ] **Step 3: Reduce route logic to pure transport mapping**

Keep `travel_planning_agent/api/chat.py` in this shape:

```python
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: DBSession = Depends(get_db)):
    result = ChatService(db=db).handle_message(
        message=req.message,
        session_id=req.session_id,
    )
    return ChatResponse(
        type=result.type,
        content=result.content,
        trip_id=result.trip_id,
        plan_summary=result.plan_summary,
        session_id=result.session_id,
    )
```

If helper functions remain that are not route-only, move them back into `core/chat_service.py` or remove them if dead.

- [ ] **Step 4: Run the full chat-facing verification set**

Run:

```bash
pytest tests/test_chat_service.py tests/test_chat_api.py tests/test_product_runtime.py tests/test_supervisor.py -v
```

Expected: PASS. The public HTTP shape is stable, and internal decoupling did not break planning/runtime behavior.

- [ ] **Step 5: Commit**

```bash
git add travel_planning_agent/api/chat.py tests/test_chat_api.py
git commit -m "refactor: keep chat api transport only"
```

---

## Self-Review

### Spec coverage

This plan covers the five major goals from the decoupling proposal:

- Remove `core -> concrete agent` creation: Task 1
- Slim `SupervisorAgent`: Task 2
- Slim `ChatService`: Task 3
- Split LLM transport from tool execution: Task 4
- Keep API thin and stable: Task 5

No proposal section is left without an implementation task.

### Placeholder scan

Checked for forbidden placeholders:

- No `TODO`
- No `TBD`
- No “add tests” without concrete test code
- No “same as above” references

### Type consistency

Key names are consistent across tasks:

- `build_planning_supervisor`
- `PlanningStateService`
- `ChatRevisionService`
- `ChatRuntimeService`
- `ToolCallingService`

These names are used consistently in file structure, tests, and code snippets.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-19-decoupling-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
