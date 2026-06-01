# Personal Free Travel V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first personal free-travel user loop: generate multiple usable itinerary options, explain why each plan works, let the user revise locally, and produce an executable travel checklist.

**Architecture:** Keep the current FastAPI + SQLAlchemy + Vue structure. Add small product-facing services around the existing `PlanningRuntime`, `PlanComparisonService`, and revision pipeline instead of replacing the agent core. The first milestone stays synchronous because the user asked for functionality, but all new APIs should return stable records that can later move behind async jobs.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pytest, Vue 3, Element Plus, TypeScript.

---

## Scope

This plan targets personal independent travelers, not travel agencies or enterprise admin users.

In scope:
- User-friendly plan profiles: relaxed, classic, food-focused, economy.
- Decision cards for each generated plan.
- Local plan revision commands: lighten a day, replace an activity, reduce budget, handle rain, keep selected segments.
- Explanation cards for itinerary items.
- Execution checklist: reservations, transport, weather, packing, budget.
- Frontend surfaces in trip detail.

Out of scope for this milestone:
- Kubernetes, monitoring, authentication, RBAC, payment, booking.
- Full async job queue.
- Native mobile app.
- Knowledge graph.

---

## File Structure

Create:
- `travel_planning_agent/core/personalization.py`  
  Converts trip data and plan data into personal-travel summaries, decision cards, explanation cards, and execution checklist items.

- `travel_planning_agent/api/personal.py`  
  API endpoints for plan decision cards, explanations, checklist, and supported revision suggestions.

- `tests/test_personalization.py`  
  Unit tests for summaries, explanations, and checklist extraction.

- `tests/test_personal_api.py`  
  API-level tests for the new personal travel endpoints.

Modify:
- `travel_planning_agent/core/plan_comparison.py`  
  Replace generic comparison labels with personal free-travel profiles and richer summary fields.

- `travel_planning_agent/core/plan_revision.py`  
  Expand revision intent parsing for personal traveler commands.

- `travel_planning_agent/api/app.py`  
  Register the new router.

- `frontend/src/types/index.ts`  
  Add TypeScript interfaces for decision cards, explanations, checklist items, and revision suggestions.

- `frontend/src/api/index.ts`  
  Add client functions for the new endpoints.

- `frontend/src/views/TripDetail.vue`  
  Add plan cards, explanation drawer, checklist panel, and quick revision entry.

---

### Task 1: Personal Travel Summary Service

**Files:**
- Create: `travel_planning_agent/core/personalization.py`
- Test: `tests/test_personalization.py`

- [ ] **Step 1: Write failing tests for decision-card summaries**

Add this to `tests/test_personalization.py`:

```python
from travel_planning_agent.core.personalization import build_decision_card


def test_build_decision_card_summarizes_personal_plan():
    plan = {
        "days": [
            {
                "day_number": 1,
                "theme": "Arrive and explore",
                "segments": [
                    {"type": "transport", "title": "Train to Hangzhou", "estimated_cost": {"amount": 220}},
                    {"type": "activity", "title": "West Lake walk", "tags": ["classic"], "estimated_cost": {"amount": 0}},
                    {"type": "meal", "title": "Local noodle dinner", "estimated_cost": {"amount": 80}},
                ],
            }
        ]
    }

    card = build_decision_card("classic", plan)

    assert card["profile_id"] == "classic"
    assert card["label"] == "经典初游"
    assert card["total_cost"] == 300
    assert card["activity_count"] == 1
    assert card["pace_level"] in {"轻松", "适中", "紧凑"}
    assert card["best_for"]
    assert card["tradeoffs"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
python -m pytest tests/test_personalization.py::test_build_decision_card_summarizes_personal_plan -q
```

Expected: import failure because `travel_planning_agent.core.personalization` does not exist yet.

- [ ] **Step 3: Implement the minimal summary service**

Create `travel_planning_agent/core/personalization.py`:

```python
PROFILE_META = {
    "relaxed": {
        "label": "轻松慢游",
        "best_for": "不想赶路、希望每天留出休息时间的自由行用户",
        "tradeoffs": ["景点覆盖较少", "体验更从容"],
    },
    "classic": {
        "label": "经典初游",
        "best_for": "第一次到目的地、希望覆盖代表性景点的用户",
        "tradeoffs": ["热门点较多", "步行和换乘可能偏多"],
    },
    "food": {
        "label": "美食深度",
        "best_for": "把吃当地特色放在高优先级的用户",
        "tradeoffs": ["景点密度降低", "餐饮预算占比更高"],
    },
    "economy": {
        "label": "省钱优先",
        "best_for": "希望控制总预算、接受更朴素安排的用户",
        "tradeoffs": ["舒适度略低", "部分体验会被替换为低成本选项"],
    },
}


def build_decision_card(profile_id: str, plan: dict) -> dict:
    meta = PROFILE_META.get(profile_id, PROFILE_META["classic"])
    days = plan.get("days") or []
    segments = [seg for day in days for seg in day.get("segments", [])]
    total_cost = sum(_segment_cost(seg) for seg in segments)
    activity_count = sum(1 for seg in segments if seg.get("type") == "activity")
    daily_activity = activity_count / len(days) if days else 0
    pace_level = "轻松" if daily_activity <= 2 else "适中" if daily_activity <= 4 else "紧凑"
    return {
        "profile_id": profile_id,
        "label": meta["label"],
        "best_for": meta["best_for"],
        "tradeoffs": list(meta["tradeoffs"]),
        "total_cost": total_cost,
        "activity_count": activity_count,
        "day_count": len(days),
        "pace_level": pace_level,
    }


def _segment_cost(segment: dict) -> float:
    cost = segment.get("estimated_cost")
    if isinstance(cost, dict):
        return float(cost.get("amount") or 0)
    if isinstance(cost, (int, float)):
        return float(cost)
    return 0.0
```

- [ ] **Step 4: Run the test and confirm it passes**

Run:

```powershell
python -m pytest tests/test_personalization.py::test_build_decision_card_summarizes_personal_plan -q
```

Expected: `1 passed`.

---

### Task 2: Personal Plan Profiles

**Files:**
- Modify: `travel_planning_agent/core/plan_comparison.py`
- Test: `tests/test_product_runtime.py` or new tests in `tests/test_personalization.py`

- [ ] **Step 1: Write a test that compares personal profile labels**

Add to `tests/test_personalization.py`:

```python
from travel_planning_agent.core.plan_comparison import PLAN_PROFILES


def test_plan_profiles_are_personal_free_travel_profiles():
    ids = [p["id"] for p in PLAN_PROFILES]
    labels = [p["label"] for p in PLAN_PROFILES]

    assert ids == ["relaxed", "classic", "food", "economy"]
    assert labels == ["轻松慢游", "经典初游", "美食深度", "省钱优先"]
```

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
python -m pytest tests/test_personalization.py::test_plan_profiles_are_personal_free_travel_profiles -q
```

Expected: failure because the current profiles are economy, comfort, depth.

- [ ] **Step 3: Update profile definitions**

Modify `PLAN_PROFILES` in `travel_planning_agent/core/plan_comparison.py`:

```python
PLAN_PROFILES = [
    {"id": "relaxed", "label": "轻松慢游", "description": "降低每日活动密度，保留休息和弹性时间"},
    {"id": "classic", "label": "经典初游", "description": "覆盖目的地代表性景点，适合第一次到访"},
    {"id": "food", "label": "美食深度", "description": "围绕本地餐饮和街区体验组织行程"},
    {"id": "economy", "label": "省钱优先", "description": "优先控制总预算，减少高价项目"},
]
```

- [ ] **Step 4: Update `PlanningRuntime._apply_profile`**

Modify `travel_planning_agent/core/planning_runtime.py` so profile behavior matches personal travel:

```python
if profile == "relaxed":
    adjusted.pace = "slow"
    adjusted.budget = round(spec.budget * 0.95)
    return adjusted
if profile == "classic":
    adjusted.pace = "moderate"
    return adjusted
if profile == "food":
    adjusted.food_preference = (adjusted.food_preference + " 本地特色餐饮、小吃街、老字号").strip()
    adjusted.must_have = list(dict.fromkeys([*adjusted.must_have, "本地美食"]))
    return adjusted
if profile == "economy":
    adjusted.budget = round(spec.budget * 0.75)
    adjusted.pace = "slow" if spec.pace != "fast" else "moderate"
    return adjusted
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/test_personalization.py tests/test_product_runtime.py -q
```

Expected: all selected tests pass.

---

### Task 3: Explanation Cards

**Files:**
- Modify: `travel_planning_agent/core/personalization.py`
- Test: `tests/test_personalization.py`

- [ ] **Step 1: Write failing test for segment explanations**

Add:

```python
from travel_planning_agent.core.personalization import build_explanation_cards


def test_build_explanation_cards_explains_activity_and_transport():
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"segment_id": "a1", "type": "activity", "title": "West Lake", "tags": ["classic"], "note": "Good first visit"},
                    {"segment_id": "t1", "type": "transport", "title": "Metro to hotel", "note": "Avoids traffic"},
                ],
            }
        ]
    }

    cards = build_explanation_cards(plan)

    assert cards[0]["segment_id"] == "a1"
    assert "为什么推荐" in cards[0]["sections"]
    assert "注意事项" in cards[0]["sections"]
    assert cards[1]["segment_id"] == "t1"
```

- [ ] **Step 2: Implement explanation card builder**

Add to `travel_planning_agent/core/personalization.py`:

```python
def build_explanation_cards(plan: dict) -> list[dict]:
    cards = []
    for day in plan.get("days") or []:
        for seg in day.get("segments", []) or []:
            cards.append({
                "segment_id": seg.get("segment_id") or seg.get("title", ""),
                "day_number": day.get("day_number"),
                "title": seg.get("title", ""),
                "type": seg.get("type", ""),
                "sections": {
                    "为什么推荐": _why_recommended(seg),
                    "为什么这样安排": _why_scheduled(day, seg),
                    "注意事项": _attention_notes(seg),
                },
            })
    return cards


def _why_recommended(seg: dict) -> str:
    if seg.get("note"):
        return str(seg["note"])
    if seg.get("type") == "activity":
        return "这是行程中的主要体验点，适合作为当天的核心安排。"
    if seg.get("type") == "meal":
        return "用于补足当天餐饮节奏，避免游玩时间过长。"
    if seg.get("type") == "transport":
        return "用于连接相邻安排，帮助用户判断当天是否可执行。"
    return "该安排用于保持行程完整。"


def _why_scheduled(day: dict, seg: dict) -> str:
    time_text = "-".join(x for x in [seg.get("start_time"), seg.get("end_time")] if x)
    if time_text:
        return f"安排在 {time_text}，便于衔接 Day {day.get('day_number')} 的其他项目。"
    return f"安排在 Day {day.get('day_number')}，与当天主题相匹配。"


def _attention_notes(seg: dict) -> str:
    tags = seg.get("tags") or []
    if "rain" in tags or "indoor" in tags:
        return "适合作为天气不稳定时的备选。"
    if seg.get("type") == "activity":
        return "建议出发前确认开放时间、预约要求和现场排队情况。"
    if seg.get("type") == "transport":
        return "建议预留缓冲时间，避免影响后续安排。"
    return "建议根据当天体力和天气灵活调整。"
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m pytest tests/test_personalization.py -q
```

Expected: all personalization tests pass.

---

### Task 4: Execution Checklist

**Files:**
- Modify: `travel_planning_agent/core/personalization.py`
- Test: `tests/test_personalization.py`

- [ ] **Step 1: Write failing checklist test**

Add:

```python
from travel_planning_agent.core.personalization import build_execution_checklist


def test_build_execution_checklist_groups_actionable_items():
    trip = {"destination": "Hangzhou", "start_date": "2026-06-01", "budget": 3000}
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"type": "transport", "title": "High-speed train", "estimated_cost": {"amount": 220}},
                    {"type": "activity", "title": "Museum", "tags": ["reservation"]},
                    {"type": "accommodation", "title": "Hotel near metro"},
                ],
            }
        ]
    }

    checklist = build_execution_checklist(trip, plan)

    categories = [item["category"] for item in checklist]
    assert "交通" in categories
    assert "预约" in categories
    assert "住宿" in categories
    assert "预算" in categories
```

- [ ] **Step 2: Implement checklist builder**

Add:

```python
def build_execution_checklist(trip: dict, plan: dict) -> list[dict]:
    items = []
    total_cost = 0.0
    for day in plan.get("days") or []:
        for seg in day.get("segments", []) or []:
            total_cost += _segment_cost(seg)
            if seg.get("type") == "transport":
                items.append(_checklist_item("交通", day, f"确认交通安排：{seg.get('title', '')}"))
            if seg.get("type") == "accommodation":
                items.append(_checklist_item("住宿", day, f"确认入住信息：{seg.get('title', '')}"))
            if "reservation" in (seg.get("tags") or []):
                items.append(_checklist_item("预约", day, f"提前预约或购票：{seg.get('title', '')}"))
    items.append({
        "category": "预算",
        "day_number": None,
        "title": f"预计花费 {total_cost:,.0f} 元，出发前确认是否符合预算",
        "priority": "medium",
        "done": False,
    })
    items.append({
        "category": "天气",
        "day_number": None,
        "title": f"出发前查看 {trip.get('destination', '')} 天气并准备雨具或防晒",
        "priority": "medium",
        "done": False,
    })
    return items


def _checklist_item(category: str, day: dict, title: str) -> dict:
    return {
        "category": category,
        "day_number": day.get("day_number"),
        "title": title,
        "priority": "high" if category in {"交通", "住宿", "预约"} else "medium",
        "done": False,
    }
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m pytest tests/test_personalization.py -q
```

Expected: all personalization tests pass.

---

### Task 5: Personal Travel API

**Files:**
- Create: `travel_planning_agent/api/personal.py`
- Modify: `travel_planning_agent/api/app.py`
- Test: `tests/test_personal_api.py`

- [ ] **Step 1: Write API tests**

Create `tests/test_personal_api.py`:

```python
from fastapi.testclient import TestClient

from travel_planning_agent.api.app import app
from travel_planning_agent.db.models import Trip, PlanVersion, User, Session


def test_personal_plan_details_endpoint_returns_cards(db_session):
    user = User(email="personal@example.com", password_hash="", display_name="Personal")
    db_session.add(user)
    db_session.commit()
    session = Session(user_id=user.user_id, title="Hangzhou")
    db_session.add(session)
    db_session.commit()
    trip = Trip(
        session_id=session.session_id,
        user_id=user.user_id,
        destination="Hangzhou",
        start_date="2026-06-01",
        days=1,
        budget=3000,
        pace="moderate",
    )
    db_session.add(trip)
    db_session.commit()
    plan = PlanVersion(
        trip_id=trip.trip_id,
        version=1,
        is_active=True,
        plan_data={"days": [{"day_number": 1, "segments": [{"segment_id": "a1", "type": "activity", "title": "West Lake"}]}]},
    )
    db_session.add(plan)
    db_session.commit()

    client = TestClient(app)
    res = client.get(f"/api/trips/{trip.trip_id}/personal")

    assert res.status_code == 200
    body = res.json()
    assert body["decision_card"]["day_count"] == 1
    assert body["explanations"][0]["segment_id"] == "a1"
    assert body["checklist"]
```

- [ ] **Step 2: Implement router**

Create `travel_planning_agent/api/personal.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.core.personalization import (
    build_decision_card,
    build_explanation_cards,
    build_execution_checklist,
)
from travel_planning_agent.db.models import PlanVersion, Trip
from travel_planning_agent.db.session import get_db

router = APIRouter(prefix="/api/trips", tags=["个人自由行"])


@router.get("/{trip_id}/personal")
def get_personal_trip_view(trip_id: str, db: DBSession = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(404, "行程不存在")
    plan = db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id,
        PlanVersion.is_active == True,  # noqa: E712
    ).order_by(PlanVersion.version.desc()).first()
    if not plan:
        raise HTTPException(404, "当前行程还没有可用方案")
    trip_data = {
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat(),
        "budget": trip.budget,
        "pace": trip.pace,
    }
    return {
        "decision_card": build_decision_card("classic", plan.plan_data),
        "explanations": build_explanation_cards(plan.plan_data),
        "checklist": build_execution_checklist(trip_data, plan.plan_data),
        "revision_suggestions": [
            "这一天太累了，帮我轻松一点",
            "下雨的话，把户外项目换成室内",
            "预算降一点，但保留必去景点",
            "保留酒店和交通，只改景点",
        ],
    }
```

- [ ] **Step 3: Register router**

Modify `travel_planning_agent/api/app.py`:

```python
from travel_planning_agent.api.personal import router as personal_router

app.include_router(personal_router)
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
python -m pytest tests/test_personal_api.py -q
```

Expected: personal API tests pass.

---

### Task 6: Revision Intent Expansion

**Files:**
- Modify: `travel_planning_agent/core/plan_revision.py`
- Test: `tests/test_chat_revision.py`

- [ ] **Step 1: Add tests for personal revision commands**

Add to `tests/test_chat_revision.py`:

```python
from travel_planning_agent.core.plan_revision import analyze_change_intent


def test_analyze_change_intent_detects_lighter_day():
    intent = analyze_change_intent("第二天太累了，轻松一点", {"days": [{"day_number": 1}, {"day_number": 2}]})

    assert intent["type"] == "lighten_day"
    assert intent["target_day"] == 2
    assert intent["requires_tools"] is False


def test_analyze_change_intent_detects_rainy_day():
    intent = analyze_change_intent("第三天下雨的话换成室内", {"days": [{"day_number": 1}, {"day_number": 2}, {"day_number": 3}]})

    assert intent["type"] == "rainy_day_backup"
    assert intent["target_day"] == 3
    assert intent["requires_tools"] is True
```

- [ ] **Step 2: Extend intent parser**

Modify `analyze_change_intent` in `travel_planning_agent/core/plan_revision.py` before replacement-activity parsing:

```python
if any(token in message for token in ("太累", "轻松一点", "少走路", "慢一点")):
    return {
        "type": "lighten_day",
        "target_day": target_day,
        "requires_tools": False,
    }

if any(token in message for token in ("下雨", "雨天", "室内", "天气不好")):
    return {
        "type": "rainy_day_backup",
        "target_day": target_day,
        "requires_tools": True,
    }

if any(token in message for token in ("预算降", "便宜一点", "省钱", "花费少")):
    return {
        "type": "reduce_budget",
        "target_day": target_day,
        "requires_tools": False,
    }
```

- [ ] **Step 3: Teach evidence collection for rainy-day backups**

Modify `_collect_revision_evidence`:

```python
if intent.get("type") == "rainy_day_backup":
    result = tool_executor("search_poi", {
        "destination": getattr(trip, "destination", ""),
        "category": "cultural",
        "context": "室内 博物馆 展览 商场",
    })
    return [{
        "tool": "search_poi",
        "status": getattr(result, "status", ""),
        "data": getattr(result, "data", ""),
        "evidence": getattr(result, "evidence", []),
    }]
```

- [ ] **Step 4: Run revision tests**

Run:

```powershell
python -m pytest tests/test_chat_revision.py -q
```

Expected: revision tests pass.

---

### Task 7: Frontend API and Types

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add TypeScript types**

Add to `frontend/src/types/index.ts`:

```ts
export interface PersonalDecisionCard {
  profile_id: string
  label: string
  best_for: string
  tradeoffs: string[]
  total_cost: number
  activity_count: number
  day_count: number
  pace_level: string
}

export interface ExplanationCard {
  segment_id: string
  day_number: number
  title: string
  type: string
  sections: Record<string, string>
}

export interface ChecklistItem {
  category: string
  day_number: number | null
  title: string
  priority: 'high' | 'medium' | 'low'
  done: boolean
}

export interface PersonalTripView {
  decision_card: PersonalDecisionCard
  explanations: ExplanationCard[]
  checklist: ChecklistItem[]
  revision_suggestions: string[]
}
```

- [ ] **Step 2: Add API client function**

Add to `frontend/src/api/index.ts`:

```ts
export const getPersonalTripView = (tripId: string) =>
  api.get(`/trips/${tripId}/personal`)
```

- [ ] **Step 3: Run frontend typecheck**

Run:

```powershell
npm run build
```

Expected: TypeScript and Vite build pass.

---

### Task 8: Trip Detail Personal Travel UI

**Files:**
- Modify: `frontend/src/views/TripDetail.vue`

- [ ] **Step 1: Load personal view data**

In the script section, import the new API and add state:

```ts
import { getPersonalTripView } from '@/api'

const personalView = ref<any>(null)

async function loadPersonalView() {
  const id = route.params.id as string
  try {
    const res = await getPersonalTripView(id)
    personalView.value = res.data
  } catch (e) {
    personalView.value = null
  }
}
```

Call `await loadPersonalView()` after `await loadTrip()` refreshes plan data.

- [ ] **Step 2: Add decision card panel**

Add a panel above the timeline when `personalView?.decision_card` exists:

```vue
<el-card v-if="personalView?.decision_card" shadow="never" style="margin-bottom: 16px;">
  <template #header>
    <span>方案判断</span>
  </template>
  <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;">
    <div><small>类型</small><br><strong>{{ personalView.decision_card.label }}</strong></div>
    <div><small>节奏</small><br><strong>{{ personalView.decision_card.pace_level }}</strong></div>
    <div><small>预算</small><br><strong>￥{{ personalView.decision_card.total_cost.toLocaleString() }}</strong></div>
    <div><small>活动</small><br><strong>{{ personalView.decision_card.activity_count }} 个</strong></div>
  </div>
  <p style="margin: 12px 0 0;">{{ personalView.decision_card.best_for }}</p>
  <el-tag v-for="item in personalView.decision_card.tradeoffs" :key="item" size="small" style="margin-right: 6px;">
    {{ item }}
  </el-tag>
</el-card>
```

- [ ] **Step 3: Add checklist panel**

Add below the timeline:

```vue
<el-card v-if="personalView?.checklist?.length" shadow="never" style="margin-bottom: 16px;">
  <template #header>
    <span>出发前清单</span>
  </template>
  <el-checkbox
    v-for="item in personalView.checklist"
    :key="`${item.category}-${item.title}`"
    v-model="item.done"
    style="display: block; margin: 8px 0;"
  >
    <el-tag size="small" style="margin-right: 6px;">{{ item.category }}</el-tag>
    <span>{{ item.day_number ? `Day ${item.day_number}：` : '' }}{{ item.title }}</span>
  </el-checkbox>
</el-card>
```

- [ ] **Step 4: Run frontend build**

Run:

```powershell
npm run build
```

Expected: build passes. If Vite still warns about chunk size, record it but do not block this feature.

---

## Verification

Run all backend tests:

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
python -m pytest -q
```

Expected: all tests pass.

Run frontend build:

```powershell
cd D:\Python_Project\RealTripAssistant\frontend
npm run build
```

Expected: TypeScript and Vite build pass.

Manual verification:
- Create or open a trip.
- Generate a plan.
- Open trip detail.
- Confirm the decision card appears.
- Confirm explanation/checklist data loads.
- Run plan comparison and verify labels are personal-travel profiles.
- Send revision text such as `第二天太累了，轻松一点` and confirm the backend classifies it as `lighten_day`.

---

## Self-Review

Spec coverage:
- Multi-plan personal profiles are covered by Tasks 2 and 8.
- Explanation cards are covered by Tasks 3 and 5.
- Execution checklist is covered by Tasks 4, 5, and 8.
- Local revision intent expansion is covered by Task 6.
- Frontend user experience is covered by Tasks 7 and 8.

Scope control:
- The plan avoids infrastructure work and keeps the first milestone inside current modules.
- The plan does not introduce authentication, payments, booking, or async workers.

Known follow-up:
- After V1 is working, the next plan should add persisted checklist state, richer user preference memory, and async plan-run progress.
