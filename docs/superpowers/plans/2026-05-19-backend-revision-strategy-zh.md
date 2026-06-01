# Backend Revision Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前后端“修改行程”链路升级成一个稳定的分类执行系统：先把用户输入归入少数几个安全动作，再按动作执行最小修改、追加一天、重排受影响天或澄清。

**Architecture:** 保留现有 `ChatService -> ChatRevisionService -> plan_revision` 主入口，但把后端职责拆成四层：`revision scope parsing` 负责解析显式范围，`revision strategy routing` 负责把请求归类到固定动作，`revision execution` 负责按动作执行，`clarification response` 负责在高影响或模糊请求下返回一句追问。第一阶段不做“全懂自然语言”，只做“分类再动作”，并优先覆盖局部修改、追加一天、全局高影响修改这三类高频场景。

**Tech Stack:** Python 3.12、SQLAlchemy、pytest、现有 `ChatServiceResult`、`PlanVersion`、`RevisionAgent`、`planning runtime / supervisor` 链路。

---

## File Structure

- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_strategy.py`
  - 职责：把解析结果路由为 `patch_scope / append_day / replan_impacted / clarify` 之一。
- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_append.py`
  - 职责：处理“我还能多玩一天”这类追加一天的后端逻辑。
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_strategy.py`
  - 职责：验证后端动作路由规则。
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_append.py`
  - 职责：验证“追加一天但不重写前面”以及“顺延返程”的行为。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_scope_parser.py`
  - 职责：从仅解析局部范围，扩展为支持“追加一天 / 改总天数 / 全局交通 / 模糊反馈”等高层输入分类信号。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
  - 职责：从“parse scope 后直接 apply”升级成“parse -> route strategy -> clarify or execute”。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_revision.py`
  - 职责：保留局部 patch 能力，并抽出纯执行函数，避免继续承载越来越多的语义判断。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision_service.py`
  - 职责：验证 strategy 路由后的分流行为。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_service.py`
  - 职责：验证 `ChatService` 入口在“追加一天 / 高影响修改 / 模糊修改”下的真实行为。

## Shared Strategy Contract

所有后端修改请求统一落成这个结构：

```python
{
    "matched": True,
    "target_day": 2,
    "target_module": "afternoon",
    "target_segment": None,
    "change_type": "lighten_day",
    "scope_type": "day_module",
    "impact_level": "low",
    "strategy": "patch_scope",
    "clarification_needed": False,
    "clarification_question": "",
}
```

字段约束：

- `change_type`
  - 第一阶段至少支持：
    - `lighten_day`
    - `remove_segment`
    - `change_return_time`
    - `append_day`
    - `change_trip_days`
    - `change_transport_mode`
    - `ambiguous_feedback`
- `scope_type`
  - `segment`
  - `day_module`
  - `day`
  - `append`
  - `global`
  - `unknown`
- `impact_level`
  - `low`
  - `medium`
  - `high`
- `strategy`
  - `patch_scope`
  - `append_day`
  - `replan_impacted`
  - `clarify`

---

### Task 1: 先把策略路由测试补齐

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_strategy.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_scope_parser.py`

- [ ] **Step 1: 写策略路由的失败测试**

```python
from travel_planning_agent.core.revision_strategy import choose_revision_strategy


def test_choose_revision_strategy_for_scope_patch():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "lighten_day",
            "scope_type": "day_module",
            "impact_level": "low",
            "clarification_needed": False,
        }
    )
    assert strategy["strategy"] == "patch_scope"


def test_choose_revision_strategy_for_append_day_requires_confirmation():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "append_day",
            "scope_type": "append",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
        }
    )
    assert strategy["strategy"] == "clarify"
    assert strategy["clarification_question"] == "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？"


def test_choose_revision_strategy_for_global_transport_change():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "change_transport_mode",
            "scope_type": "global",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想只改返程，还是整趟交通方式都调整？",
        }
    )
    assert strategy["strategy"] == "clarify"


def test_choose_revision_strategy_for_unknown_feedback():
    strategy = choose_revision_strategy(
        {
            "matched": False,
            "change_type": "ambiguous_feedback",
            "scope_type": "unknown",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
        }
    )
    assert strategy["strategy"] == "clarify"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_revision_strategy.py -q`

Expected: `ModuleNotFoundError: No module named 'travel_planning_agent.core.revision_strategy'`

- [ ] **Step 3: 提交测试脚手架**

```bash
git add tests/test_revision_strategy.py
git commit -m "test: add revision strategy routing cases"
```

---

### Task 2: 实现 revision strategy router

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_strategy.py`
- Test: `D:\Python_Project\RealTripAssistant\tests\test_revision_strategy.py`

- [ ] **Step 1: 写最小策略路由器实现**

```python
from __future__ import annotations


def choose_revision_strategy(parsed_scope: dict) -> dict:
    if parsed_scope.get("clarification_needed"):
        return {
            "strategy": "clarify",
            "clarification_question": parsed_scope.get("clarification_question", ""),
        }

    change_type = parsed_scope.get("change_type")
    scope_type = parsed_scope.get("scope_type")

    if change_type in {"lighten_day", "remove_segment", "change_return_time"} and scope_type in {
        "segment",
        "day_module",
        "day",
    }:
        return {"strategy": "patch_scope"}

    if change_type == "append_day" and scope_type == "append":
        return {"strategy": "append_day"}

    if change_type in {"change_trip_days", "change_transport_mode"} and scope_type == "global":
        return {"strategy": "replan_impacted"}

    return {
        "strategy": "clarify",
        "clarification_question": parsed_scope.get("clarification_question")
        or "你想改哪一天，还是改某个具体景点/时段？",
    }
```

- [ ] **Step 2: 运行路由测试并确认通过**

Run: `pytest tests/test_revision_strategy.py -q`

Expected: `4 passed`

- [ ] **Step 3: 提交策略路由器**

```bash
git add travel_planning_agent/core/revision_strategy.py tests/test_revision_strategy.py
git commit -m "feat: add revision strategy router"
```

---

### Task 3: 扩展 scope parser，支持“追加一天 / 全局修改 / 模糊反馈”

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_scope_parser.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_revision_scope_parser.py`

- [ ] **Step 1: 先补 parser 的新失败测试**

```python
def test_parse_revision_scope_detects_append_day_request():
    parsed = parse_revision_scope("我还能多玩一天", _sample_plan())
    assert parsed["matched"] is True
    assert parsed["change_type"] == "append_day"
    assert parsed["scope_type"] == "append"
    assert parsed["impact_level"] == "high"
    assert parsed["clarification_needed"] is True


def test_parse_revision_scope_detects_global_transport_change():
    parsed = parse_revision_scope("我要坐飞机", _sample_plan())
    assert parsed["matched"] is True
    assert parsed["change_type"] == "change_transport_mode"
    assert parsed["scope_type"] == "global"
    assert parsed["impact_level"] == "high"
    assert parsed["clarification_needed"] is True


def test_parse_revision_scope_marks_ambiguous_feedback():
    parsed = parse_revision_scope("感觉不太对", _sample_plan())
    assert parsed["matched"] is False
    assert parsed["change_type"] == "ambiguous_feedback"
    assert parsed["scope_type"] == "unknown"
    assert parsed["clarification_needed"] is True
```

- [ ] **Step 2: 运行 parser 测试并确认失败**

Run: `pytest tests/test_revision_scope_parser.py -q`

Expected: new append/global/ambiguous cases fail

- [ ] **Step 3: 扩展 parser 返回结构**

```python
APPEND_DAY_TOKENS = ("多玩一天", "多待一天", "还能玩一天", "加一天", "新增一天")
GLOBAL_TRANSPORT_TOKENS = ("坐飞机", "改飞机", "改高铁", "改动车")
AMBIGUOUS_FEEDBACK_TOKENS = ("感觉不太对", "改一下", "调整一下", "不太行")
```

```python
parsed = {
    "matched": False,
    "target_day": ...,
    "target_module": ...,
    "target_segment": ...,
    "change_type": ...,
    "scope_type": "unknown",
    "impact_level": "high",
    "replacement_text": None,
    "clarification_needed": False,
    "clarification_question": "",
}
```

```python
if any(token in text for token in APPEND_DAY_TOKENS):
    parsed.update(
        {
            "matched": True,
            "change_type": "append_day",
            "scope_type": "append",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
        }
    )
    return parsed
```

```python
if any(token in text for token in GLOBAL_TRANSPORT_TOKENS):
    parsed.update(
        {
            "matched": True,
            "change_type": "change_transport_mode",
            "scope_type": "global",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想只改返程，还是整趟交通方式都调整？",
        }
    )
    return parsed
```

```python
if any(token in text for token in AMBIGUOUS_FEEDBACK_TOKENS):
    parsed.update(
        {
            "matched": False,
            "change_type": "ambiguous_feedback",
            "scope_type": "unknown",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
        }
    )
    return parsed
```

- [ ] **Step 4: 给局部 patch 补齐 scope_type / impact_level**

```python
if parsed["change_type"] and parsed["target_segment"]:
    parsed["scope_type"] = "segment"
    parsed["impact_level"] = "low"
elif parsed["change_type"] and parsed["target_day"] and parsed["target_module"]:
    parsed["scope_type"] = "day_module"
    parsed["impact_level"] = "low"
elif parsed["change_type"] and parsed["target_day"]:
    parsed["scope_type"] = "day"
    parsed["impact_level"] = "medium"
```

- [ ] **Step 5: 运行 parser 测试并确认通过**

Run: `pytest tests/test_revision_scope_parser.py -q`

Expected: all parser tests pass

- [ ] **Step 6: 提交 parser 扩展**

```bash
git add travel_planning_agent/core/revision_scope_parser.py tests/test_revision_scope_parser.py
git commit -m "feat: extend revision scope parser with strategy signals"
```

---

### Task 4: 改造 ChatRevisionService，接 strategy router

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision_service.py`

- [ ] **Step 1: 先补 service 分流测试**

```python
def test_chat_revision_service_returns_clarification_for_append_day():
    service = ChatRevisionService(db=None, session_store=None)
    result = service._build_strategy_result(
        session_id="sess_1",
        trip_id="trip_1",
        strategy_result={
            "strategy": "clarify",
            "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
        },
    )
    assert result.type == "question"


def test_chat_revision_service_returns_false_for_patch_strategy():
    service = ChatRevisionService(db=None, session_store=None)
    result = service._build_strategy_result(
        session_id="sess_1",
        trip_id="trip_1",
        strategy_result={"strategy": "patch_scope"},
    )
    assert result is False
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_chat_revision_service.py -q`

Expected: FAIL because `_build_strategy_result` does not exist

- [ ] **Step 3: 在 service 中接入 choose_revision_strategy**

```python
from travel_planning_agent.core.revision_strategy import choose_revision_strategy
```

```python
def _build_strategy_result(self, session_id: str, trip_id: str, strategy_result: dict):
    if strategy_result.get("strategy") == "clarify":
        return ChatServiceResult(
            type="question",
            content=strategy_result["clarification_question"],
            trip_id=trip_id,
            session_id=session_id,
        )
    return False
```

```python
parsed_scope = parse_revision_scope(message, plan_data)
strategy_result = choose_revision_strategy(parsed_scope)
service_result = self._build_strategy_result(session_id, trip_id, strategy_result)
if isinstance(service_result, ChatServiceResult):
    return service_result
```

- [ ] **Step 4: 运行 service 测试并确认通过**

Run: `pytest tests/test_chat_revision_service.py -q`

Expected: all service tests pass

- [ ] **Step 5: 提交 service 分流**

```bash
git add travel_planning_agent/core/chat_revision_service.py tests/test_chat_revision_service.py
git commit -m "feat: route revision requests by strategy"
```

---

### Task 5: 单独落地 append_day 执行器

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_append.py`
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_append.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\agent\supervisor.py`

- [ ] **Step 1: 先写 append_day 的失败测试**

```python
from travel_planning_agent.core.revision_append import append_one_day_plan


def test_append_one_day_plan_preserves_existing_days():
    plan_data = {
        "days": [
            {"day_number": 1, "theme": "第一天", "segments": [{"title": "中山路"}]},
            {"day_number": 2, "theme": "第二天", "segments": [{"title": "鼓浪屿"}]},
        ]
    }
    new_day = {
        "day_number": 3,
        "theme": "新增一天",
        "segments": [{"title": "植物园"}],
    }

    updated = append_one_day_plan(plan_data, new_day)

    assert [day["day_number"] for day in updated["days"]] == [1, 2, 3]
    assert updated["days"][0]["theme"] == "第一天"
    assert updated["days"][1]["theme"] == "第二天"
    assert updated["days"][2]["theme"] == "新增一天"
```

- [ ] **Step 2: 再写返程顺延测试**

```python
def test_append_one_day_plan_removes_old_return_segment_from_previous_last_day():
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "theme": "返程日",
                "segments": [
                    {"title": "酒店早餐", "type": "meal"},
                    {"title": "从厦门返回杭州", "type": "transport", "tags": ["return"]},
                ],
            }
        ]
    }
    new_day = {
        "day_number": 3,
        "theme": "新增一天",
        "segments": [{"title": "沙坡尾", "type": "activity"}],
    }

    updated = append_one_day_plan(plan_data, new_day)

    assert [seg["title"] for seg in updated["days"][0]["segments"]] == ["酒店早餐"]
    assert updated["days"][1]["day_number"] == 3
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_revision_append.py -q`

Expected: `ModuleNotFoundError: No module named 'travel_planning_agent.core.revision_append'`

- [ ] **Step 4: 写最小 append_day 实现**

```python
from __future__ import annotations


def append_one_day_plan(plan_data: dict, new_day: dict) -> dict:
    updated = {"days": [dict(day) for day in plan_data.get("days") or []]}
    if updated["days"]:
        last_day = dict(updated["days"][-1])
        last_day["segments"] = [
            dict(seg)
            for seg in last_day.get("segments", [])
            if "return" not in list(seg.get("tags") or [])
        ]
        updated["days"][-1] = last_day
    updated["days"].append(dict(new_day))
    updated["days"] = sorted(updated["days"], key=lambda day: int(day.get("day_number") or 0))
    return updated
```

- [ ] **Step 5: 运行 append_day 测试并确认通过**

Run: `pytest tests/test_revision_append.py -q`

Expected: `2 passed`

- [ ] **Step 6: 提交 append_day 执行器**

```bash
git add travel_planning_agent/core/revision_append.py tests/test_revision_append.py
git commit -m "feat: add append-day plan executor"
```

---

### Task 6: 把 append_day 和 replan_impacted 接到 revision 执行入口

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_revision.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision.py`

- [ ] **Step 1: 先写 append_day 入口测试**

```python
def test_apply_change_request_to_plan_appends_new_day_when_strategy_is_append():
    trip = SimpleNamespace(destination="厦门", days=2)
    plan_data = {
        "days": [
            {"day_number": 1, "theme": "第一天", "segments": [{"title": "中山路", "type": "activity"}]},
            {"day_number": 2, "theme": "返程日", "segments": [{"title": "从厦门返回杭州", "type": "transport", "tags": ["return"]}]},
        ]
    }
    new_day = {"day_number": 3, "theme": "新增一天", "segments": [{"title": "植物园", "type": "activity"}]}

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "我还能多玩一天",
        {},
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "change_type": "append_day",
            "scope_type": "append",
            "impact_level": "high",
        },
        append_day=new_day,
    )

    assert changed is True
    assert [day["day_number"] for day in plan_data["days"]] == [1, 2, 3]
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `pytest tests/test_chat_revision.py -k append_new_day -q`

Expected: FAIL because `apply_change_request_to_plan()` does not accept `append_day`

- [ ] **Step 3: 扩展执行入口参数**

```python
def apply_change_request_to_plan(
    plan_data: dict,
    trip,
    message: str,
    context: dict | None = None,
    revision_agent=None,
    tool_executor=None,
    parsed_scope: dict | None = None,
    append_day: dict | None = None,
) -> bool:
```

```python
from travel_planning_agent.core.revision_append import append_one_day_plan
```

```python
if intent.get("type") == "append_day" and append_day:
    updated = append_one_day_plan(plan_data, append_day)
    plan_data["days"] = updated["days"]
    return True
```

- [ ] **Step 4: 给 replan_impacted 先留最小占位执行边界**

```python
if strategy_result.get("strategy") == "replan_impacted":
    return ChatServiceResult(
        type="question",
        content="这次修改会影响多天安排，我需要先确认具体范围。",
        trip_id=trip_id,
        session_id=session_id,
    )
```

这一步的目标不是立刻实现完整重规划，而是先在后端链路里占住正确入口，避免高影响修改继续误走局部 patch。

- [ ] **Step 5: 运行 revision 相关测试并确认通过**

Run: `pytest tests/test_chat_revision.py tests/test_chat_revision_service.py -q`

Expected: all selected tests pass

- [ ] **Step 6: 提交执行入口扩展**

```bash
git add travel_planning_agent/core/chat_revision_service.py travel_planning_agent/core/plan_revision.py tests/test_chat_revision.py tests/test_chat_revision_service.py
git commit -m "feat: add append-day and replan strategy entry points"
```

---

### Task 7: 补 ChatService 端到端回归

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_service.py`

- [ ] **Step 1: 写“追加一天先澄清”的入口测试**

```python
def test_chat_service_returns_append_day_clarification():
    from travel_planning_agent.core.chat_service import ChatService
    from travel_planning_agent.core.chat_types import ChatServiceResult

    class FakeSessionStore:
        def load_context(self, session_id):
            return {"last_trip_id": "trip_1", "extracted": {}}

        def remember_trace_id(self, context, trace_id):
            context["last_trace_id"] = trace_id

        def touch_session(self, session_id, destination):
            return None

        def append_message(self, context, role, content, message_type=None):
            context.setdefault("messages", []).append((role, content, message_type))

        def save_context(self, session_id, context):
            context["saved"] = session_id

    class FakeRevisionService:
        def try_apply(self, session_id, message, context):
            return ChatServiceResult(
                type="question",
                content="你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
                trip_id="trip_1",
                session_id=session_id,
            )

    service = ChatService(
        db=db,
        session_store=FakeSessionStore(),
        revision_service_factory=lambda _db, _store: FakeRevisionService(),
    )
    result = service.handle_message("我还能多玩一天", session_id="sess_append_day")
    assert result.type == "question"
```

- [ ] **Step 2: 写“坐飞机先澄清”的入口测试**

```python
def test_chat_service_returns_transport_change_clarification():
    ...
    result = service.handle_message("我要坐飞机", session_id="sess_transport_change")
    assert result.type == "question"
    assert "只改返程" in result.content
```

- [ ] **Step 3: 运行 chat service 测试并确认通过**

Run: `pytest tests/test_chat_service.py -q`

Expected: all chat service tests pass

- [ ] **Step 4: 提交端到端回归**

```bash
git add tests/test_chat_service.py
git commit -m "test: cover append-day and global-change clarification"
```

---

### Task 8: 完整验证与后端行为边界整理

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\docs\superpowers\plans\2026-05-19-backend-revision-strategy-zh.md`

- [ ] **Step 1: 跑完整目标测试集**

Run: `pytest tests/test_revision_scope_parser.py tests/test_revision_strategy.py tests/test_revision_append.py tests/test_chat_revision_service.py tests/test_chat_revision.py tests/test_chat_service.py -q`

Expected: all targeted backend revision tests pass

- [ ] **Step 2: 记录第一阶段后端边界**

把下面这段同步到 PR 描述或交接说明：

```text
直接执行：
- 第二天下午轻松一点
- 把鼓浪屿换掉

先澄清：
- 我还能多玩一天
- 我要坐飞机
- 预算改 3000
- 感觉不太对

第一阶段暂不做：
- 一句话多个修改意图自动拆分
- 全局修改后自动重跑完整行程
- 基于累计草案的复杂影响分析
```

- [ ] **Step 3: 创建最终提交**

```bash
git add travel_planning_agent/core/revision_strategy.py travel_planning_agent/core/revision_append.py travel_planning_agent/core/revision_scope_parser.py travel_planning_agent/core/chat_revision_service.py travel_planning_agent/core/plan_revision.py tests/test_revision_strategy.py tests/test_revision_append.py tests/test_revision_scope_parser.py tests/test_chat_revision_service.py tests/test_chat_revision.py tests/test_chat_service.py docs/superpowers/plans/2026-05-19-backend-revision-strategy-zh.md
git commit -m "feat: add backend revision strategy routing"
```

---

## Self-Review

### Spec coverage

- “不要试图全懂自然语言，只做分类再动作”：Task 1、Task 2、Task 3 覆盖。
- “局部修改只改指定范围”：Task 3、Task 4、Task 6 覆盖。
- “追加一天默认走追加策略，不重写前面”：Task 5、Task 6、Task 7 覆盖。
- “高影响修改先澄清，不误走 patch”：Task 2、Task 3、Task 4、Task 7 覆盖。
- “后端行为边界清楚”：Task 8 覆盖。

没有缺口；本计划刻意不覆盖多意图拆分和完整全局重规划实现。

### Placeholder scan

没有使用 `TODO/TBD/后续补上` 这类占位语；每个任务都给了具体文件、测试、命令和最小代码骨架。

### Type consistency

- `parse_revision_scope(...)` 负责解析
- `choose_revision_strategy(...)` 负责路由
- `append_one_day_plan(...)` 负责追加一天
- `apply_change_request_to_plan(...)` 仍是底层执行入口

命名在所有任务中保持一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-backend-revision-strategy-zh.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
