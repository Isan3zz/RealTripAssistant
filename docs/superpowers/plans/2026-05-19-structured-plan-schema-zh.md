# Structured Plan Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固定后端 `plan.v1` 输出契约，让前端右侧最终行程优先渲染结构化数据，而不是解析聊天文本。

**Architecture:** 后端新增一个稳定 view model 层，将内部 `PlanState` / `plan_data` 转换为 `plan.v1`。`ChatServiceResult`、`/api/chat`、revision 返回、session resume 都携带这个结构化 `plan`。前端新增 `PlanView` 类型和适配器，`TripList.vue` 优先使用 `response.plan` / `resume.plan` 渲染，旧历史数据才回退到 `parsePlanMessage(content)`。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy、pytest、Vue 3、TypeScript、Vitest。

---

## File Structure

- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_schema.py`
  - 负责生成稳定的 `plan.v1` view model。
- Create: `D:\Python_Project\RealTripAssistant\tests\test_plan_schema.py`
  - 覆盖 plan schema 字段、金额、地点、天数和 segment 形状。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_types.py`
  - `ChatServiceResult` 增加 `plan: Optional[dict]`。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\api\chat.py`
  - `ChatResponse` 增加 `plan` 字段，并从 service result 透传。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_runtime_service.py`
  - 首次规划完成时填充 `plan`，并写入 session context 的 `last_response.plan`。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
  - revision 成功后填充 `plan`。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\session_resume.py`
  - resume payload 增加 active plan 的结构化 `plan`。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\api\sessions.py`
  - `SessionResumeResponse` 增加 `plan` 字段。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_api.py`
  - 覆盖 `/api/chat` 返回结构化 plan。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_service.py`
  - 覆盖 service result 带 plan。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_session_resume.py`
  - 覆盖 session restore 带 plan。
- Modify: `D:\Python_Project\RealTripAssistant\frontend\src\types\index.ts`
  - 增加 `PlanView` / `PlanViewDay` / `PlanViewSegment` / `ChatResponse` 类型。
- Create: `D:\Python_Project\RealTripAssistant\frontend\src\utils\planViewAdapter.ts`
  - 将 `PlanView` 转为当前右侧组件可消费的 `ParsedPlanMessage`。
- Create: `D:\Python_Project\RealTripAssistant\frontend\src\utils\planViewAdapter.test.ts`
  - 覆盖结构化 plan 到前端展示模型的转换。
- Modify: `D:\Python_Project\RealTripAssistant\frontend\src\views\TripList.vue`
  - 新增 `structuredPlan` 状态，优先渲染结构化 plan。

## Schema Contract

第一版 `plan.v1` 固定为：

```python
{
    "schema_version": "plan.v1",
    "title": "杭州至厦门3日游",
    "origin": "杭州",
    "destination": "厦门",
    "day_count": 3,
    "budget": {"amount": 5000, "currency": "CNY"},
    "total_cost": {"amount": 2380, "currency": "CNY"},
    "summary": ["杭州 → 厦门", "3天", "预算 ¥5,000", "预计 ¥2,380"],
    "days": [
        {
            "day_number": 1,
            "title": "抵达厦门",
            "note": "",
            "segments": [
                {
                    "segment_id": "seg_1",
                    "type": "activity",
                    "module": "afternoon",
                    "start_time": "14:00",
                    "end_time": "16:00",
                    "time": "14:00-16:00",
                    "title": "中山路步行街",
                    "location": {"name": "中山路步行街", "city": "厦门"},
                    "estimated_cost": {"amount": 50, "currency": "CNY"},
                    "tags": ["classic"],
                    "note": "",
                    "why": "",
                    "attention": ""
                }
            ]
        }
    ]
}
```

---

### Task 1: Backend Plan Schema Tests

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\tests\test_plan_schema.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_run_service.py`

- [ ] **Step 1: Write failing tests for plan.v1**

```python
from types import SimpleNamespace

from travel_planning_agent.core.plan_schema import format_plan_view


def test_format_plan_view_builds_stable_schema_from_plan_data():
    trip = SimpleNamespace(origin="杭州", destination="厦门", days=2, budget=5000)
    plan_data = {
        "days": [
            {
                "day_number": 1,
                "theme": "抵达厦门",
                "day_note": "轻松抵达",
                "segments": [
                    {
                        "segment_id": "s1",
                        "type": "activity",
                        "module": "afternoon",
                        "start_time": "14:00",
                        "end_time": "16:00",
                        "title": "中山路步行街",
                        "location": {"name": "中山路步行街", "city": "厦门"},
                        "estimated_cost": {"amount": 50, "currency": "CNY"},
                        "tags": ["classic"],
                        "note": "慢慢逛",
                    }
                ],
            }
        ]
    }

    view = format_plan_view(plan_data, trip=trip)

    assert view["schema_version"] == "plan.v1"
    assert view["origin"] == "杭州"
    assert view["destination"] == "厦门"
    assert view["day_count"] == 2
    assert view["budget"] == {"amount": 5000, "currency": "CNY"}
    assert view["total_cost"] == {"amount": 50, "currency": "CNY"}
    assert view["days"][0]["title"] == "抵达厦门"
    assert view["days"][0]["segments"][0]["time"] == "14:00-16:00"
    assert view["days"][0]["segments"][0]["estimated_cost"] == {"amount": 50, "currency": "CNY"}
```

- [ ] **Step 2: Run test and confirm failure**

Run: `pytest tests/test_plan_schema.py -q`

Expected: `ModuleNotFoundError: No module named 'travel_planning_agent.core.plan_schema'`

---

### Task 2: Implement Backend Plan Schema

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_schema.py`
- Test: `D:\Python_Project\RealTripAssistant\tests\test_plan_schema.py`

- [ ] **Step 1: Implement `format_plan_view`**

```python
from __future__ import annotations


def format_plan_view(plan_data: dict, *, trip=None, summary: dict | None = None) -> dict:
    origin = (getattr(trip, "origin", "") or "").strip()
    destination = (getattr(trip, "destination", "") or "").strip()
    days = [_format_day(day) for day in plan_data.get("days") or []]
    total_cost = sum(
        segment["estimated_cost"]["amount"]
        for day in days
        for segment in day["segments"]
        if segment.get("estimated_cost")
    )
    day_count = int(getattr(trip, "days", 0) or len(days))
    budget_amount = float(getattr(trip, "budget", 0) or 0)

    title_parts = [part for part in [origin, destination] if part]
    title = f"{'至'.join(title_parts)}{day_count}日游" if title_parts else "行程规划"

    return {
        "schema_version": "plan.v1",
        "title": title,
        "origin": origin,
        "destination": destination,
        "day_count": day_count,
        "budget": {"amount": budget_amount, "currency": "CNY"},
        "total_cost": {"amount": total_cost, "currency": "CNY"},
        "summary": _format_summary(origin, destination, day_count, budget_amount, total_cost),
        "days": days,
    }
```

- [ ] **Step 2: Implement day and segment helpers**

```python
def _format_day(day: dict) -> dict:
    day_number = int(day.get("day_number") or 0)
    return {
        "day_number": day_number,
        "title": day.get("theme") or f"Day {day_number}",
        "note": day.get("day_note") or "",
        "segments": [_format_segment(segment) for segment in day.get("segments") or []],
    }


def _format_segment(segment: dict) -> dict:
    start = segment.get("start_time") or ""
    end = segment.get("end_time") or ""
    return {
        "segment_id": segment.get("segment_id") or "",
        "type": segment.get("type") or "activity",
        "module": segment.get("module") or _module_from_time(start),
        "start_time": start,
        "end_time": end,
        "time": f"{start}-{end}" if start or end else "",
        "title": segment.get("title") or "",
        "location": _format_location(segment.get("location")),
        "estimated_cost": _format_cost(segment.get("estimated_cost")),
        "tags": list(segment.get("tags") or []),
        "note": segment.get("note") or "",
        "why": segment.get("why") or "",
        "attention": segment.get("attention") or "",
    }
```

- [ ] **Step 3: Implement simple normalizers**

```python
def _format_location(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {"name": value.get("name") or "", "city": value.get("city") or ""}
    return {"name": str(value), "city": ""}


def _format_cost(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {"amount": float(value.get("amount") or 0), "currency": value.get("currency") or "CNY"}
    return {"amount": float(value or 0), "currency": "CNY"}


def _module_from_time(value: str) -> str:
    if not value or ":" not in value:
        return "afternoon"
    hour = int(value.split(":", 1)[0])
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def _format_summary(origin: str, destination: str, days: int, budget: float, total: float) -> list[str]:
    route = " → ".join([part for part in [origin, destination] if part])
    items = []
    if route:
        items.append(route)
    if days:
        items.append(f"{days}天")
    if budget:
        items.append(f"预算 ¥{budget:,.0f}")
    items.append(f"预计 ¥{total:,.0f}")
    return items
```

- [ ] **Step 4: Verify schema tests pass**

Run: `pytest tests/test_plan_schema.py -q`

Expected: `1 passed`

---

### Task 3: Add Plan Field To Chat Response Contract

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_types.py`
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\api\chat.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_api.py`

- [ ] **Step 1: Add failing API response test**

```python
def test_chat_response_model_includes_structured_plan(client, monkeypatch):
    from travel_planning_agent.core.chat_types import ChatServiceResult

    def fake_handle_message(self, message, session_id=None):
        return ChatServiceResult(
            type="plan_result",
            content="行程已生成",
            trip_id="trip_1",
            session_id="sess_1",
            plan={"schema_version": "plan.v1", "days": []},
        )

    monkeypatch.setattr("travel_planning_agent.core.chat_service.ChatService.handle_message", fake_handle_message)

    res = client.post("/api/chat", json={"message": "杭州去厦门三天"})

    assert res.status_code == 200
    assert res.json()["plan"]["schema_version"] == "plan.v1"
```

- [ ] **Step 2: Extend dataclass and Pydantic model**

```python
# travel_planning_agent/core/chat_types.py
@dataclass
class ChatServiceResult:
    type: str
    content: str
    trip_id: Optional[str] = None
    plan_summary: Optional[dict] = None
    session_id: Optional[str] = None
    plan: Optional[dict] = None
```

```python
# travel_planning_agent/api/chat.py
class ChatResponse(BaseModel):
    type: str
    content: str
    trip_id: Optional[str] = None
    plan_summary: Optional[dict] = None
    session_id: Optional[str] = None
    plan: Optional[dict] = None
```

- [ ] **Step 3: Return `plan=result.plan` from API**

```python
return ChatResponse(
    type=result.type,
    content=result.content,
    trip_id=result.trip_id,
    plan_summary=result.plan_summary,
    session_id=result.session_id,
    plan=result.plan,
)
```

- [ ] **Step 4: Verify API test**

Run: `pytest tests/test_chat_api.py -k structured_plan -q`

Expected: targeted test passes

---

### Task 4: Return Structured Plan From Initial Planning

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_runtime_service.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_service.py`

- [ ] **Step 1: Add service-level test**

```python
def test_chat_service_plan_result_contains_structured_plan(monkeypatch):
    from travel_planning_agent.core.chat_types import ChatServiceResult

    result = ChatServiceResult(
        type="plan_result",
        content="行程已生成",
        trip_id="trip_1",
        session_id="sess_1",
        plan={"schema_version": "plan.v1", "days": []},
    )

    assert result.plan["schema_version"] == "plan.v1"
```

- [ ] **Step 2: Build plan view after runtime returns**

```python
from travel_planning_agent.core.plan_schema import format_plan_view

plan_view = format_plan_view(result["plan_data"], trip=state.constraints, summary=summary)
```

- [ ] **Step 3: Store plan in context and return it**

```python
context["last_response"] = {
    "type": "plan",
    "content": content,
    "trip_id": state.trip_id,
    "plan": plan_view,
}

return ChatServiceResult(
    type="plan_result",
    content=content,
    trip_id=state.trip_id,
    plan_summary=summary,
    session_id=session_id,
    plan=plan_view,
)
```

- [ ] **Step 4: Verify chat service tests**

Run: `pytest tests/test_chat_service.py -q`

Expected: all chat service tests pass

---

### Task 5: Return Structured Plan From Revision

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision_service.py`

- [ ] **Step 1: Add revision service result test**

```python
def test_revision_service_result_can_carry_structured_plan():
    from travel_planning_agent.core.chat_types import ChatServiceResult

    result = ChatServiceResult(
        type="plan_result",
        content="已修改",
        trip_id="trip_1",
        session_id="sess_1",
        plan={"schema_version": "plan.v1", "days": []},
    )

    assert result.plan["schema_version"] == "plan.v1"
```

- [ ] **Step 2: Generate plan view after mutation**

```python
from travel_planning_agent.core.plan_schema import format_plan_view

summary = format_plan_data_summary(plan_data, trip)
plan_view = format_plan_view(plan_data, trip=trip, summary=summary)
```

- [ ] **Step 3: Return plan view**

```python
return ChatServiceResult(
    type="plan_result",
    content=content,
    trip_id=trip_id,
    plan_summary=summary,
    session_id=session_id,
    plan=plan_view,
)
```

- [ ] **Step 4: Verify revision tests**

Run: `pytest tests/test_chat_revision_service.py tests/test_chat_revision.py -q`

Expected: all revision tests pass

---

### Task 6: Include Structured Plan In Session Resume

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\session_resume.py`
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\api\sessions.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_session_resume.py`

- [ ] **Step 1: Add resume test**

```python
def test_session_resume_includes_structured_plan(db_session):
    payload = build_session_resume(db_session, "sess_with_plan", include_context_pack=True)

    assert payload["plan"]["schema_version"] == "plan.v1"
```

Use the existing test fixture pattern in `tests/test_session_resume.py` to create a session, trip, and active `PlanVersion`.

- [ ] **Step 2: Build plan view in resume payload**

```python
from travel_planning_agent.core.plan_schema import format_plan_view

active_plan = ...
trip = ...
plan_view = format_plan_view(active_plan.plan_data or {}, trip=trip) if active_plan else None
payload["plan"] = plan_view
```

- [ ] **Step 3: Extend API model**

```python
class SessionResumeResponse(BaseModel):
    ...
    plan: Optional[dict] = None
```

- [ ] **Step 4: Verify resume tests**

Run: `pytest tests/test_session_resume.py -q`

Expected: all session resume tests pass

---

### Task 7: Frontend Types And Plan View Adapter

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\frontend\src\types\index.ts`
- Create: `D:\Python_Project\RealTripAssistant\frontend\src\utils\planViewAdapter.ts`
- Create: `D:\Python_Project\RealTripAssistant\frontend\src\utils\planViewAdapter.test.ts`

- [ ] **Step 1: Add PlanView TypeScript types**

```ts
export interface PlanViewCost {
  amount: number
  currency: string
}

export interface PlanViewSegment {
  segment_id: string
  type: string
  module: string
  start_time: string
  end_time: string
  time: string
  title: string
  location: { name?: string; city?: string } | null
  estimated_cost: PlanViewCost | null
  tags: string[]
  note: string
  why: string
  attention: string
}

export interface PlanViewDay {
  day_number: number
  title: string
  note: string
  segments: PlanViewSegment[]
}

export interface PlanView {
  schema_version: 'plan.v1'
  title: string
  origin: string
  destination: string
  day_count: number
  budget: PlanViewCost
  total_cost: PlanViewCost
  summary: string[]
  days: PlanViewDay[]
}

export interface ChatResponse {
  type: string
  content: string
  trip_id?: string
  plan_summary?: Record<string, unknown>
  session_id?: string
  plan?: PlanView | null
}
```

- [ ] **Step 2: Add adapter test**

```ts
import { describe, expect, it } from 'vitest'
import { planViewToParsedPlan } from './planViewAdapter'
import type { PlanView } from '@/types'

describe('planViewToParsedPlan', () => {
  it('groups structured segments by category', () => {
    const plan: PlanView = {
      schema_version: 'plan.v1',
      title: '杭州至厦门3日游',
      origin: '杭州',
      destination: '厦门',
      day_count: 3,
      budget: { amount: 5000, currency: 'CNY' },
      total_cost: { amount: 50, currency: 'CNY' },
      summary: ['杭州 → 厦门', '3天'],
      days: [{
        day_number: 1,
        title: '抵达厦门',
        note: '',
        segments: [{
          segment_id: 's1',
          type: 'activity',
          module: 'afternoon',
          start_time: '14:00',
          end_time: '16:00',
          time: '14:00-16:00',
          title: '中山路步行街',
          location: { name: '中山路步行街', city: '厦门' },
          estimated_cost: { amount: 50, currency: 'CNY' },
          tags: [],
          note: '',
          why: '',
          attention: '',
        }],
      }],
    }

    const parsed = planViewToParsedPlan(plan)

    expect(parsed.title).toBe('杭州至厦门3日游')
    expect(parsed.days[0].categories[0].name).toBe('游玩')
    expect(parsed.days[0].categories[0].segments[0].cost).toBe('¥50')
  })
})
```

- [ ] **Step 3: Implement adapter**

```ts
import type { PlanView } from '@/types'
import type { ParsedPlanMessage, PlanCategoryView, PlanSegmentView } from './planParser'

const TYPE_LABELS: Record<string, string> = {
  transport: '路程',
  activity: '游玩',
  meal: '用餐',
  accommodation: '住宿',
}

export function planViewToParsedPlan(plan: PlanView): ParsedPlanMessage {
  return {
    title: plan.title || '行程规划完成',
    summary: plan.summary || [],
    days: (plan.days || []).map((day) => {
      const categories: PlanCategoryView[] = []
      for (const segment of day.segments || []) {
        const name = TYPE_LABELS[segment.type] || '安排'
        let category = categories.find((item) => item.name === name)
        if (!category) {
          category = { name, segments: [] }
          categories.push(category)
        }
        category.segments.push(toSegmentView(segment))
      }
      return {
        title: `Day ${day.day_number} - ${day.title}`,
        note: day.note || '',
        categories,
      }
    }),
  }
}

function toSegmentView(segment: PlanView['days'][number]['segments'][number]): PlanSegmentView {
  return {
    time: segment.time || [segment.start_time, segment.end_time].filter(Boolean).join('-'),
    title: segment.title,
    cost: formatCost(segment.estimated_cost),
    why: segment.why || '',
    attention: segment.attention || segment.note || '',
  }
}

function formatCost(cost: { amount: number; currency: string } | null): string {
  if (!cost || !cost.amount) return ''
  return cost.currency === 'CNY' ? `¥${cost.amount.toLocaleString()}` : `${cost.amount.toLocaleString()} ${cost.currency}`
}
```

- [ ] **Step 4: Verify frontend adapter tests**

Run: `cd frontend && npm test -- planViewAdapter`

Expected: adapter test passes

---

### Task 8: TripList Uses Structured Plan First

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\frontend\src\views\TripList.vue`
- Test: `D:\Python_Project\RealTripAssistant\frontend\src\utils\planViewAdapter.test.ts`

- [ ] **Step 1: Add structured plan state**

```ts
import type { ChatResponse, PlanView } from '@/types'
import { planViewToParsedPlan } from '@/utils/planViewAdapter'

const structuredPlan = ref<PlanView | null>(null)
const parsedPlan = computed(() =>
  structuredPlan.value
    ? planViewToParsedPlan(structuredPlan.value)
    : parseStoredPlanMessage(planContent.value)
)
```

- [ ] **Step 2: Update result visibility**

```vue
<el-tag v-if="structuredPlan || planContent" type="success" size="small" effect="plain">已生成</el-tag>

<div v-if="(structuredPlan || planContent) && parsedPlan.days.length" class="plan-result-card">
```

- [ ] **Step 3: Store plan from chat response**

```ts
const data: ChatResponse = await res.json()

if (data.type === 'plan_result') {
  structuredPlan.value = data.plan || null
  planContent.value = data.content
  messages.value.push({ role: 'assistant', type: 'plan_note', content: '行程已生成，右侧可以查看最终结果。你也可以继续说想怎么调整。' })
}
```

- [ ] **Step 4: Restore plan from session resume**

```ts
structuredPlan.value = data.plan || null
const lastPlan = [...data.messages].reverse().find((msg: any) => msg.type === 'plan')
planContent.value = lastPlan?.content || ''
```

- [ ] **Step 5: Clear structured plan on new session**

```ts
structuredPlan.value = null
planContent.value = ''
```

- [ ] **Step 6: Verify frontend build**

Run: `cd frontend && npm test && npm run build`

Expected: tests and build pass

---

### Task 9: Backend Integration Verification

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_api.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_session_resume.py`

- [ ] **Step 1: Run backend target tests**

Run:

```bash
pytest tests/test_plan_schema.py tests/test_chat_api.py tests/test_chat_service.py tests/test_chat_revision_service.py tests/test_session_resume.py -q
```

Expected: all selected backend tests pass

- [ ] **Step 2: Run frontend target tests**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: frontend tests and build pass

- [ ] **Step 3: Document behavior boundary in PR notes**

```text
New behavior:
- New plan_result responses include plan.v1.
- Session resume includes active structured plan when available.
- TripList renders response.plan first.
- parsePlanMessage remains only as a legacy fallback for old sessions.
```

---

## Self-Review

### Spec coverage

- 后端固定 plan schema：Task 1、Task 2 覆盖。
- 首次规划返回结构化 plan：Task 3、Task 4 覆盖。
- revision 返回结构化 plan：Task 5 覆盖。
- session restore 返回结构化 plan：Task 6 覆盖。
- 前端只优先吃结构化数据：Task 7、Task 8 覆盖。
- 旧文本解析只做兼容兜底：Task 8 覆盖。

### Placeholder scan

本计划没有 `TBD`、`TODO` 或“补适当逻辑”这类占位任务；每个任务都有明确文件、测试、代码骨架和验证命令。

### Type consistency

- 后端字段统一叫 `plan`。
- schema 版本固定为 `plan.v1`。
- 前端类型统一叫 `PlanView`。
- 前端适配器统一叫 `planViewToParsedPlan`。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-structured-plan-schema-zh.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
