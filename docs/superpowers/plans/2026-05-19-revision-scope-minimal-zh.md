# Revision Scope Minimal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先实现“用户明确指定什么，就只修改什么；没有明确指定范围时，不自动修改，只追问一句”的最小修改链路。

**Architecture:** 保留现有 `ChatService -> ChatRevisionService -> plan_revision` 主链路，在中间新增一个轻量 `revision_scope_parser`。该解析器只负责识别明确范围（哪一天 / 哪个时段 / 哪个具体对象），`ChatRevisionService` 负责“执行还是澄清”的分流，`plan_revision` 负责在明确范围内做最小修改，不做全局智能推断。

**Tech Stack:** Python 3.12、SQLAlchemy、pytest、现有 `RevisionAgent` / `PlanVersion` / `ChatServiceResult` 结构。

---

## File Structure

- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_scope_parser.py`
  - 职责：把自然语言修改请求解析成最小结构化范围，不执行修改。
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_scope_parser.py`
  - 职责：验证“哪一天 / 哪个时段 / 哪个对象 / 是否需要澄清”的解析结果。
- Create: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision_service.py`
  - 职责：验证 `ChatRevisionService` 在“明确范围”和“范围不清”两类情况下的分流行为。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
  - 职责：接入 scope parser，并在“执行 / 澄清 / 不处理”之间分流。
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_revision.py`
  - 职责：补足“只改某天 / 只改某个模块 / 只改某个对象”所需的最小执行函数。
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision.py`
  - 职责：保留现有 revision 行为测试，并补最小范围修改相关回归用例。

## Shared Data Shape

所有新逻辑围绕这个最小结构工作：

```python
{
    "matched": True,
    "target_day": 2,
    "target_module": "afternoon",
    "target_segment": None,
    "change_type": "lighten_day",
    "replacement_text": None,
    "clarification_needed": False,
    "clarification_question": "",
}
```

字段约束：

- `target_day`: `int | None`
- `target_module`: `None | "morning" | "afternoon" | "evening" | "return"`
- `target_segment`: `str | None`，存当前计划中唯一命中的标题或关键词
- `change_type`: 第一版只允许 `lighten_day` / `rainy_day_backup` / `replace_activity` / `remove_segment` / `change_return_time`
- `clarification_needed`: 只要范围不唯一或缺失，就必须为 `True`

---

### Task 1: 先写范围解析器测试

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\tests\test_revision_scope_parser.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_revision.py`

- [ ] **Step 1: 写出解析器的失败测试**

```python
from travel_planning_agent.core.revision_scope_parser import parse_revision_scope


def _sample_plan():
    return {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"title": "中山路步行街", "type": "activity", "module": "evening"},
                ],
            },
            {
                "day_number": 2,
                "segments": [
                    {"title": "鼓浪屿", "type": "activity", "module": "morning"},
                    {"title": "午餐", "type": "meal", "module": "afternoon"},
                    {"title": "环岛路骑行", "type": "activity", "module": "afternoon"},
                ],
            },
        ]
    }


def test_parse_revision_scope_matches_day_level_request():
    parsed = parse_revision_scope("第二天轻松一点", _sample_plan())
    assert parsed["matched"] is True
    assert parsed["target_day"] == 2
    assert parsed["target_module"] is None
    assert parsed["change_type"] == "lighten_day"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_matches_day_module_request():
    parsed = parse_revision_scope("第二天下午轻松一点", _sample_plan())
    assert parsed["matched"] is True
    assert parsed["target_day"] == 2
    assert parsed["target_module"] == "afternoon"
    assert parsed["change_type"] == "lighten_day"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_matches_unique_segment_request():
    parsed = parse_revision_scope("把鼓浪屿换掉", _sample_plan())
    assert parsed["matched"] is True
    assert parsed["target_segment"] == "鼓浪屿"
    assert parsed["change_type"] == "remove_segment"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_requires_clarification_for_vague_request():
    parsed = parse_revision_scope("改一下", _sample_plan())
    assert parsed["matched"] is False
    assert parsed["clarification_needed"] is True
    assert parsed["clarification_question"] == "你想改哪一天，还是改某个具体景点/时段？"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_revision_scope_parser.py -q`

Expected: `ModuleNotFoundError: No module named 'travel_planning_agent.core.revision_scope_parser'`

- [ ] **Step 3: 提交测试脚手架**

```bash
git add tests/test_revision_scope_parser.py
git commit -m "test: add revision scope parser cases"
```

---

### Task 2: 实现最小 revision scope parser

**Files:**
- Create: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\revision_scope_parser.py`
- Test: `D:\Python_Project\RealTripAssistant\tests\test_revision_scope_parser.py`

- [ ] **Step 1: 写最小解析器实现**

```python
from __future__ import annotations

import re


DAY_PATTERNS = [
    (re.compile(r"最后一天"), lambda plan: len(plan.get("days") or [])),
    (re.compile(r"第([一二三四五六七八九十\\d]+)天"), None),
    (re.compile(r"day\\s*(\\d+)", re.I), None),
]

MODULE_MAP = {
    "上午": "morning",
    "中午": "afternoon",
    "下午": "afternoon",
    "晚上": "evening",
    "返程": "return",
}


def parse_revision_scope(message: str, plan_data: dict) -> dict:
    text = (message or "").strip()
    parsed = {
        "matched": False,
        "target_day": _extract_day(text, plan_data),
        "target_module": _extract_module(text),
        "target_segment": _extract_unique_segment(text, plan_data),
        "change_type": _extract_change_type(text),
        "replacement_text": None,
        "clarification_needed": False,
        "clarification_question": "",
    }
    if parsed["target_segment"] and parsed["change_type"] is None:
        parsed["change_type"] = "remove_segment"
    if parsed["change_type"] and (parsed["target_day"] or parsed["target_module"] or parsed["target_segment"]):
        parsed["matched"] = True
        return parsed
    parsed["clarification_needed"] = True
    parsed["clarification_question"] = "你想改哪一天，还是改某个具体景点/时段？"
    return parsed


def _extract_day(text: str, plan_data: dict) -> int | None:
    for pattern, resolver in DAY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if resolver:
            return resolver(plan_data)
        token = match.group(1)
        return _cn_number_to_int(token)
    return None


def _extract_module(text: str) -> str | None:
    for token, module in MODULE_MAP.items():
        if token in text:
            return module
    return None


def _extract_change_type(text: str) -> str | None:
    if any(token in text for token in ("轻松一点", "少走路", "慢一点", "别太赶")):
        return "lighten_day"
    if any(token in text for token in ("下雨", "雨天", "室内")):
        return "rainy_day_backup"
    if any(token in text for token in ("换掉", "不要", "去掉", "取消")):
        return "remove_segment"
    if any(token in text for token in ("晚一点回去", "改到下午", "返程改晚")):
        return "change_return_time"
    return None
```

- [ ] **Step 2: 补齐唯一对象匹配和中文数字解析**

```python
def _extract_unique_segment(text: str, plan_data: dict) -> str | None:
    matches = []
    for day in plan_data.get("days") or []:
        for seg in day.get("segments") or []:
            title = (seg.get("title") or "").strip()
            if title and title in text:
                matches.append(title)
    unique_matches = list(dict.fromkeys(matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def _cn_number_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    mapping = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    return mapping.get(token)
```

- [ ] **Step 3: 运行解析器测试并确认通过**

Run: `pytest tests/test_revision_scope_parser.py -q`

Expected: `4 passed`

- [ ] **Step 4: 提交解析器实现**

```bash
git add travel_planning_agent/core/revision_scope_parser.py tests/test_revision_scope_parser.py
git commit -m "feat: add minimal revision scope parser"
```

---

### Task 3: 让 ChatRevisionService 支持“执行或澄清”

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_revision_service.py`
- Create: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision_service.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_types.py`

- [ ] **Step 1: 先写 ChatRevisionService 分流测试**

```python
from travel_planning_agent.core.chat_revision_service import ChatRevisionService
from travel_planning_agent.core.chat_types import ChatServiceResult


def test_chat_revision_service_returns_clarification_for_vague_scope():
    service = ChatRevisionService(db=None, session_store=None)
    result = service._build_scope_result(
        session_id="sess_1",
        trip_id="trip_1",
        parsed_scope={
            "matched": False,
            "clarification_needed": True,
            "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
        },
    )
    assert isinstance(result, ChatServiceResult)
    assert result.type == "question"
    assert result.content == "你想改哪一天，还是改某个具体景点/时段？"


def test_chat_revision_service_returns_none_when_not_revision_scope():
    service = ChatRevisionService(db=None, session_store=None)
    result = service._build_scope_result(
        session_id="sess_1",
        trip_id="trip_1",
        parsed_scope={"matched": False, "clarification_needed": False, "clarification_question": ""},
    )
    assert result is None
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_chat_revision_service.py -q`

Expected: `AttributeError: 'ChatRevisionService' object has no attribute '_build_scope_result'`

- [ ] **Step 3: 在 ChatRevisionService 中接入 parser 和 scope result**

```python
from travel_planning_agent.core.revision_scope_parser import parse_revision_scope


def _build_scope_result(self, session_id: str, trip_id: str, parsed_scope: dict):
    if parsed_scope.get("clarification_needed"):
        return ChatServiceResult(
            type="question",
            content=parsed_scope["clarification_question"],
            trip_id=trip_id,
            session_id=session_id,
        )
    if not parsed_scope.get("matched"):
        return None
    return False
```

```python
parsed_scope = parse_revision_scope(message, plan_data)
scope_result = self._build_scope_result(session_id, trip_id, parsed_scope)
if isinstance(scope_result, ChatServiceResult):
    return scope_result
if scope_result is None:
    return None
changed = apply_change_request_to_plan(
    plan_data,
    trip,
    message,
    context,
    RevisionAgent(llm),
    parsed_scope=parsed_scope,
)
```

- [ ] **Step 4: 运行分流测试并确认通过**

Run: `pytest tests/test_chat_revision_service.py -q`

Expected: `2 passed`

- [ ] **Step 5: 提交服务层分流**

```bash
git add travel_planning_agent/core/chat_revision_service.py tests/test_chat_revision_service.py
git commit -m "feat: add revision clarification flow"
```

---

### Task 4: 在 plan_revision 中实现“只改指定范围”

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\plan_revision.py`
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_revision.py`

- [ ] **Step 1: 先补一个“只改模块”的失败测试**

```python
def test_change_request_lighten_only_replaces_target_module():
    trip = SimpleNamespace(destination="厦门", days=3)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "theme": "厦门深度游",
                "segments": [
                    {"segment_id": "m1", "type": "activity", "title": "南普陀", "start_time": "09:00", "end_time": "11:00", "module": "morning"},
                    {"segment_id": "a1", "type": "activity", "title": "环岛路骑行", "start_time": "13:00", "end_time": "16:00", "module": "afternoon"},
                    {"segment_id": "e1", "type": "meal", "title": "海鲜晚餐", "start_time": "18:00", "end_time": "19:00", "module": "evening"},
                ],
            }
        ]
    }
    llm = RecordingLLM({
        "day_number": 2,
        "theme": "厦门轻松下午",
        "segments": [
            {"segment_id": "a2", "type": "activity", "title": "咖啡馆休息", "start_time": "14:00", "end_time": "15:30", "module": "afternoon"},
        ],
    })

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "第二天下午轻松一点",
        context,
        RevisionAgent(llm),
        parsed_scope={
            "matched": True,
            "target_day": 2,
            "target_module": "afternoon",
            "target_segment": None,
            "change_type": "lighten_day",
            "clarification_needed": False,
            "clarification_question": "",
        },
    )

    assert changed is True
    titles = [seg["title"] for seg in plan_data["days"][0]["segments"]]
    assert titles == ["南普陀", "咖啡馆休息", "海鲜晚餐"]
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `pytest tests/test_chat_revision.py -k target_module -q`

Expected: FAIL because `apply_change_request_to_plan()` does not accept `parsed_scope`

- [ ] **Step 3: 给执行函数增加 parsed_scope 参数并按范围 merge**

```python
def apply_change_request_to_plan(
    plan_data: dict,
    trip,
    message: str,
    context: dict | None = None,
    revision_agent=None,
    tool_executor=None,
    parsed_scope: dict | None = None,
) -> bool:
    intent = analyze_change_intent(message, plan_data, parsed_scope=parsed_scope)
    ...
```

```python
def analyze_change_intent(message: str, plan_data: dict, parsed_scope: dict | None = None) -> dict[str, Any]:
    if parsed_scope:
        return {
            "type": parsed_scope.get("change_type"),
            "target_day": parsed_scope.get("target_day") or len(plan_data.get("days", []) or [1]),
            "target_module": parsed_scope.get("target_module"),
            "target_segment": parsed_scope.get("target_segment"),
            "requires_tools": parsed_scope.get("change_type") in {"rainy_day_backup", "replace_activity"},
        }
    ...
```

```python
def _merge_day_by_scope(original_day: dict, replacement_day: dict, intent: dict) -> dict:
    target_module = intent.get("target_module")
    if not target_module:
        return replacement_day
    preserved = [
        dict(seg)
        for seg in original_day.get("segments", [])
        if seg.get("module") != target_module
    ]
    injected = [
        dict(seg)
        for seg in replacement_day.get("segments", [])
        if seg.get("module") == target_module or target_module == "return"
    ]
    merged = dict(original_day)
    merged["theme"] = replacement_day.get("theme") or original_day.get("theme")
    merged["segments"] = sorted(preserved + injected, key=lambda s: s.get("start_time") or "")
    return merged
```

- [ ] **Step 4: 补一个“唯一对象移除”的最小测试**

```python
def test_change_request_remove_unique_segment_only_drops_that_segment():
    trip = SimpleNamespace(destination="厦门", days=2)
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "segments": [
                    {"segment_id": "a1", "type": "activity", "title": "鼓浪屿", "start_time": "09:00", "end_time": "11:00", "module": "morning"},
                    {"segment_id": "a2", "type": "activity", "title": "环岛路", "start_time": "13:00", "end_time": "15:00", "module": "afternoon"},
                ],
            }
        ]
    }

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "把鼓浪屿换掉",
        {},
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "target_day": None,
            "target_module": None,
            "target_segment": "鼓浪屿",
            "change_type": "remove_segment",
            "clarification_needed": False,
            "clarification_question": "",
        },
    )

    assert changed is True
    assert [seg["title"] for seg in plan_data["days"][0]["segments"]] == ["环岛路"]
```

- [ ] **Step 5: 为 remove_segment 补最小执行逻辑**

```python
def _remove_target_segment(plan_data: dict, target_segment: str) -> bool:
    changed = False
    for day in plan_data.get("days") or []:
        before = list(day.get("segments") or [])
        after = [seg for seg in before if seg.get("title") != target_segment]
        if len(after) != len(before):
            day["segments"] = after
            changed = True
    return changed
```

```python
if intent.get("type") == "remove_segment" and intent.get("target_segment"):
    return _remove_target_segment(plan_data, intent["target_segment"])
```

- [ ] **Step 6: 运行 revision 测试并确认通过**

Run: `pytest tests/test_chat_revision.py -q`

Expected: existing tests pass, and new target-scope tests pass

- [ ] **Step 7: 提交最小范围执行层**

```bash
git add travel_planning_agent/core/plan_revision.py tests/test_chat_revision.py
git commit -m "feat: restrict revisions to explicit scope"
```

---

### Task 5: 打通 ChatService 端到端回归

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\tests\test_chat_service.py`
- Reference: `D:\Python_Project\RealTripAssistant\travel_planning_agent\core\chat_service.py`

- [ ] **Step 1: 写一个“范围不清时返回澄清问题”的集成测试**

```python
def test_chat_service_returns_revision_clarification_question():
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
                content="你想改哪一天，还是改某个具体景点/时段？",
                trip_id="trip_1",
                session_id=session_id,
            )

    service = ChatService(
        db=db,
        session_store=FakeSessionStore(),
        revision_service_factory=lambda _db, _store: FakeRevisionService(),
    )
    result = service.handle_message("改一下", session_id="sess_revision_question")
    assert result.type == "question"
    assert result.content == "你想改哪一天，还是改某个具体景点/时段？"
```

- [ ] **Step 2: 运行测试并确认通过**

Run: `pytest tests/test_chat_service.py -q`

Expected: all existing chat service tests pass, plus the new clarification case

- [ ] **Step 3: 提交端到端回归**

```bash
git add tests/test_chat_service.py
git commit -m "test: cover revision clarification path in chat service"
```

---

### Task 6: 完整验证与文档同步

**Files:**
- Modify: `D:\Python_Project\RealTripAssistant\docs\superpowers\plans\2026-05-19-revision-scope-minimal-zh.md`

- [ ] **Step 1: 运行完整测试集合**

Run: `pytest tests/test_revision_scope_parser.py tests/test_chat_revision_service.py tests/test_chat_revision.py tests/test_chat_service.py -q`

Expected: all targeted revision and chat tests pass

- [ ] **Step 2: 记录最终行为边界**

将以下边界补进实现说明或 PR 描述：

```text
支持：
- 第二天轻松一点
- 第二天下午轻松一点
- 把鼓浪屿换掉

不自动执行：
- 我要坐飞机
- 改便宜一点
- 感觉有点赶
```

- [ ] **Step 3: 创建最终提交**

```bash
git add travel_planning_agent/core/revision_scope_parser.py travel_planning_agent/core/chat_revision_service.py travel_planning_agent/core/plan_revision.py tests/test_revision_scope_parser.py tests/test_chat_revision_service.py tests/test_chat_revision.py tests/test_chat_service.py docs/superpowers/plans/2026-05-19-revision-scope-minimal-zh.md
git commit -m "feat: add minimal explicit-scope revision flow"
```

---

## Self-Review

### Spec coverage

- “用户指定某一天就只改某一天”：Task 1、Task 2、Task 4 覆盖。
- “用户指定某个时段就只改某个时段”：Task 1、Task 4 覆盖。
- “用户指定某个具体对象就只改那个对象”：Task 1、Task 4 覆盖。
- “范围不清时不要自动修改，只追问一句”：Task 3、Task 5 覆盖。

没有缺口；本计划刻意不覆盖全局交通方式和复杂多意图拆分。

### Placeholder scan

已避免 `TODO/TBD/适当处理` 这类占位表述；每个任务都给了明确文件、示例代码、命令和预期结果。

### Type consistency

- `parse_revision_scope(...)` 在所有任务中名称一致。
- `parsed_scope` 在 `ChatRevisionService` 与 `plan_revision` 中名称一致。
- `target_module` 枚举始终使用 `morning / afternoon / evening / return`。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-revision-scope-minimal-zh.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
