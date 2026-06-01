# 修订意图统一分类器：LLM 优先 + 规则兜底

> **给执行代理的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。所有步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 新增一个 LLM 优先、规则兜底的统一意图分类入口 `classify_revision_intent()`，解决"3 个正则函数各自做检测、中文表达多变导致覆盖率低"的问题。不删除旧文件，不破坏现有修订测试。

**核心原则：**
- **LLM 分类 + 规则兜底**：LLM 可用时走 structured JSON；不可用/失败/关键字段缺失时 fallback 到现有正则。
- **不删旧文件**：`revision_scope_parser.py`、`revision_strategy.py`、`plan_revision.py` 保留不动。
- **先收敛支持范围**：本期自动执行仅限 `lighten_day / remove_segment / return_time_change`，其余类型统一追问。

**技术栈：** Python 3.11、pytest、`LLMClient.generate(system_prompt, user_message, tools=None) -> LLMResult`。

---

## 前置知识：LLM 接口

```python
# llm.py
class LLMClient(Protocol):
    def generate(self, system_prompt: str, user_message: str, tools: list[dict] = None) -> LLMResult: ...

@dataclass
class LLMResult:
    success: bool
    data: Optional[dict] = None   # 已解析的 JSON（由 _extract_json 提取）
    text: str = ""                 # LLM 原始文本
    error: Optional[str] = None
    tokens_used: int = 0

class MockLLMClient:
    def __init__(self, mock_data: Optional[dict] = None): ...
    def generate(self, system_prompt, user_message, tools=None) -> LLMResult:
        return LLMResult(success=True, data=self.mock_data, text=json.dumps(self.mock_data), tokens_used=100)
```

分类器调用方式：`llm.generate(REVISION_CLASSIFY_PROMPT, user_message, tools=None)`，从 `result.data` 取 JSON，fallback 到 `result.text`。

---

## 前置知识：意图枚举不一致（需在兼容层统一）

| 出处 | 使用的值 |
|------|---------|
| `revision_scope_parser.py` L143 | `change_return_time` |
| `revision_strategy.py` L14 | `change_return_time` |
| `plan_revision.py` L75,89,104,134 | `return_time_change` |

**本期统一标准名：`return_time_change`。** 在 fallback 兼容层将旧值 `change_return_time` 映射为 `return_time_change`。

---

## 范围

本期支持（自动执行）：
- `lighten_day` — 某天太累/太赶/少走路
- `remove_segment` — 不去/取消/换掉某个景点
- `return_time_change` — 返程时间变更

本期不支持（统一追问）：
- `append_day` — 加一天（见下文分析，当前执行路径不完整）
- `rainy_day_backup` / `replace_activity` / `reduce_budget` — 本期未放行策略分支
- `change_transport_mode` / `change_trip_days` — 全局变更，需确认范围

本期不包含：
- 删除 `revision_scope_parser.py` 或 `plan_revision.py` 中任何旧函数。
- 修改 `RevisionAgent`、`apply_change_request_to_plan()` 等执行路径。
- 修改前端。

---

## 文件结构

新增：
- `travel_planning_agent/core/revision_intent_classifier.py`
- `tests/test_revision_intent_classifier.py`

修改：
- `travel_planning_agent/core/chat_service.py`
- `travel_planning_agent/core/chat_revision_service.py`
- `travel_planning_agent/core/plan_revision.py`（仅透传 `parsed_scope` 中的返程时间字段，不改执行分支）

---

## 任务 1：定义统一 RevisionIntent schema + 分类函数

**文件：**
- 新增：`travel_planning_agent/core/revision_intent_classifier.py`

- [ ] **步骤 1：创建模块**

```python
"""统一修订意图分类器 — LLM 优先 + 规则兜底。"""

import json
import logging
from typing import Optional

from travel_planning_agent.core.plan_revision import format_plan_data_days_text

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
#  统一内部 intent 枚举
# ═══════════════════════════════════════════════════

# 本期自动执行
_AUTO_EXEC_TYPES = {"lighten_day", "remove_segment", "return_time_change"}
# 兼容映射：旧值 → 新标准值
_INTENT_ALIASES = {
    "change_return_time": "return_time_change",
}

# ═══════════════════════════════════════════════════
#  Prompt（仅列出本期支持的类型）
# ═══════════════════════════════════════════════════

REVISION_CLASSIFY_SYSTEM_PROMPT = """\
你是一个旅行行程修订意图分类器。根据用户消息和当前行程摘要，判断修改意图。

返回严格 JSON，不包含额外文本：

{
  "is_revision": true或false,
  "intent_type": "lighten_day|remove_segment|return_time_change|null",
  "target_day": 数字或null,
  "target_module": "morning|afternoon|evening|return|null",
  "target_segment": "具体景点/活动名"或null,
  "scope_type": "segment|day_module|day|unknown",
  "impact_level": "low|medium|high",
  "confidence": 0.0到1.0,
  "clarification_needed": true或false,
  "clarification_question": "追问内容"或"",
  "detail": "一句话描述修改意图"
}

规则：
- 与行程修改无关 → is_revision=false, intent_type=null。
- 意图明确（定位到天/时段/具体项目） → confidence >= 0.8, clarification_needed=false。
- 有修改意愿但范围模糊 → confidence < 0.8, clarification_needed=true。
- "不要太累/轻松一点/少走路/慢一点/别太赶" → intent_type: lighten_day
- "不去X/换掉X/取消X/不要X" → intent_type: remove_segment
- "晚点回/早点回/返程改X/改到下午回" → intent_type: return_time_change
- 以下情形均设为 clarification_needed=true：
  - "加一天/多待一天" → is_revision=true, intent_type=null
  - "下雨/雨天/室内" → is_revision=true, intent_type=null
  - "预算降/便宜一点" → is_revision=true, intent_type=null
  - "X换成Y/改X" → is_revision=true, intent_type=null
  - "改一下/调整一下/不太行" → is_revision=true, intent_type=null
"""


def _build_classify_message(message: str, plan_summary: str) -> str:
    return (
        f"当前行程摘要：\n{plan_summary}\n\n"
        f"用户消息：{message}\n\n"
        f"请分类修订意图。"
    )


# ═══════════════════════════════════════════════════
#  Schema 校验（严格模式）
# ═══════════════════════════════════════════════════

def _validate_and_normalize(raw: dict) -> Optional[dict]:
    """严格校验 LLM 返回的 JSON。关键字段缺失 → 返回 None 触发规则兜底。"""
    # 必须包含 is_revision
    if "is_revision" not in raw:
        return None

    is_rev = bool(raw.get("is_revision", False))
    intent_raw = raw.get("intent_type")

    # 明确修订但需要追问时允许 intent_type=null；明确可执行修订才必须有 intent_type
    if is_rev and not intent_raw and not raw.get("clarification_needed"):
        return None

    # 应用别名映射
    intent_type = _INTENT_ALIASES.get(intent_raw, intent_raw) if intent_raw else None

    # 校验 intent_type 合法性
    valid_types = {"lighten_day", "remove_segment", "return_time_change", None}
    if intent_type not in valid_types and intent_type is not None:
        return None

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)

    return {
        "is_revision": is_rev,
        "intent_type": intent_type,
        "target_day": raw.get("target_day") if isinstance(raw.get("target_day"), int) else None,
        "target_module": raw.get("target_module"),
        "target_segment": raw.get("target_segment"),
        "scope_type": raw.get("scope_type", "unknown"),
        "impact_level": raw.get("impact_level", "high"),
        "confidence": confidence,
        "clarification_needed": bool(raw.get("clarification_needed", False)),
        "clarification_question": raw.get("clarification_question", ""),
        "detail": raw.get("detail", ""),
        "classification_failed": False,
        "_source": "llm",
    }


# ═══════════════════════════════════════════════════
#  LLM 分类
# ═══════════════════════════════════════════════════

def _classify_via_llm(llm_client, message: str, plan_summary: str) -> Optional[dict]:
    """用 LLM 做结构化分类，失败返回 None。"""
    try:
        result = llm_client.generate(
            REVISION_CLASSIFY_SYSTEM_PROMPT,
            _build_classify_message(message, plan_summary),
            tools=None,
        )
        if not result.success:
            logger.warning("LLM 修订分类调用失败: %s", result.error)
            return None

        # 优先从已解析的 data 字段取 JSON
        raw = result.data
        if raw is None:
            # fallback: 从 text 提取 JSON
            raw = _extract_json_from_text(result.text)

        if raw is None:
            return None

        return _validate_and_normalize(raw)
    except Exception as e:
        logger.warning("LLM 修订意图分类异常: %s", e)
        return None


def _extract_json_from_text(text: str) -> Optional[dict]:
    """从 LLM 原始文本中提取 JSON。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if "```json" in text:
        try:
            inner = text.split("```json")[1].split("```")[0].strip()
            return json.loads(inner)
        except (json.JSONDecodeError, IndexError):
            pass
    if "```" in text:
        try:
            inner = text.split("```")[1].split("```")[0].strip()
            return json.loads(inner)
        except (json.JSONDecodeError, IndexError):
            pass
    return None


# ═══════════════════════════════════════════════════
#  规则 Fallback
# ═══════════════════════════════════════════════════

def _classify_via_rules(message: str, plan_data: dict, context: dict) -> dict:
    """使用现有正则逻辑作为兜底。以 looks_like_plan_revision() 守门。"""
    from travel_planning_agent.core.plan_revision import looks_like_plan_revision
    from travel_planning_agent.core.revision_scope_parser import parse_revision_scope

    is_rev = looks_like_plan_revision(message, context)
    parsed = parse_revision_scope(message, plan_data)

    # 兼容映射：change_return_time → return_time_change
    change_type = parsed.get("change_type")
    intent_type = _INTENT_ALIASES.get(change_type, change_type) if change_type else None

    return {
        "is_revision": bool(
            is_rev and (parsed.get("matched") or parsed.get("clarification_needed"))
        ),
        "intent_type": intent_type,
        "target_day": parsed.get("target_day"),
        "target_module": parsed.get("target_module"),
        "target_segment": parsed.get("target_segment"),
        "scope_type": parsed.get("scope_type", "unknown"),
        "impact_level": parsed.get("impact_level", "high"),
        "confidence": 0.70 if is_rev else 0.30,
        "clarification_needed": bool(parsed.get("clarification_needed")),
        "clarification_question": parsed.get("clarification_question", ""),
        "detail": "",
        "classification_failed": False,
        "_source": "rules",
    }


# ═══════════════════════════════════════════════════
#  统一入口
# ═══════════════════════════════════════════════════

def classify_revision_intent(
    llm_client,
    message: str,
    plan_data: dict,
    context: dict,
) -> dict:
    """
    统一修订意图分类入口。

    优先级：LLM structured JSON → 规则 fallback。
    返回 RevisionIntent dict（字段见上文 _validate_and_normalize 输出）。
    """
    plan_summary = format_plan_data_days_text(plan_data)
    result: Optional[dict] = None

    # 1. 尝试 LLM 分类
    if llm_client is not None:
        result = _classify_via_llm(llm_client, message, plan_summary)
        if result is not None and result["confidence"] >= 0.5:
            return result
        if result is None:
            logger.info("LLM 分类失败，降级到规则 fallback")

    # 2. 规则兜底
    fallback = _classify_via_rules(message, plan_data, context)

    # LLM 返回了但置信度 < 0.5 → 标记分类失败
    if result is not None:
        fallback["classification_failed"] = True

    return fallback
```

- [ ] **步骤 2：运行导入验证**

```powershell
python -c "from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent; print('import OK')"
```

预期：`import OK`。

---

## 任务 2：补全测试

**文件：**
- 新增：`tests/test_revision_intent_classifier.py`

- [ ] **步骤 1：写测试——LLM 返回有效 intent（lighten_day）**

```python
from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent
from travel_planning_agent.llm import MockLLMClient


def _plan_data():
    return {
        "days": [
            {"day_number": 1, "theme": "到达日", "segments": [
                {"title": "西湖漫步", "type": "activity"}]},
            {"day_number": 2, "theme": "经典日", "segments": [
                {"title": "雷峰塔", "type": "activity"},
                {"title": "南宋御街", "type": "activity"}]},
        ]
    }


def test_llm_classify_lighten_day():
    """LLM 可用时返回结构化 lighten_day intent。"""
    llm = MockLLMClient(mock_data={
        "is_revision": True,
        "intent_type": "lighten_day",
        "target_day": 2,
        "target_module": "afternoon",
        "target_segment": None,
        "scope_type": "day_module",
        "impact_level": "low",
        "confidence": 0.88,
        "clarification_needed": False,
        "clarification_question": "",
        "detail": "用户觉得第二天下午太累，希望减少活动量",
    })

    result = classify_revision_intent(llm, "第二天下午太累了，轻松一点", _plan_data(), {})

    assert result["is_revision"] is True
    assert result["intent_type"] == "lighten_day"
    assert result["target_day"] == 2
    assert result["_source"] == "llm"
    assert result["confidence"] == 0.88
    assert result["clarification_needed"] is False
```

- [ ] **步骤 2：LLM 不可用时走规则 fallback**

```python
def test_fallback_when_llm_is_none():
    """llm_client=None 时走规则 fallback。"""
    result = classify_revision_intent(None, "第三天太累了少走路", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"
    # 规则 fallback 能识别 lighten_day
    assert result["is_revision"] is True


def test_fallback_when_llm_returns_invalid_json():
    """LLM 返回非法 JSON 时走规则 fallback。"""
    llm = MockLLMClient(mock_data={
        "days": [{"day_number": 1}]  # 缺少 is_revision/intent_type
    })
    result = classify_revision_intent(llm, "换掉雷峰塔", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"


def test_llm_failure_triggers_fallback():
    """LLM 返回 success=False 时走规则 fallback。"""
    from travel_planning_agent.llm import LLMResult

    class FailingLLM:
        def generate(self, system_prompt, user_message, tools=None):
            return LLMResult(success=False, error="timeout")

    result = classify_revision_intent(FailingLLM(), "不去雷峰塔了", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"
```

- [ ] **步骤 3：关键字段缺失 → 触发规则兜底**

```python
def test_missing_is_revision_triggers_fallback():
    """LLM 返回的 JSON 不含 is_revision → fallback。"""
    llm = MockLLMClient(mock_data={"some": "garbage"})
    result = classify_revision_intent(llm, "少走点路", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"


def test_is_revision_true_without_intent_type_triggers_fallback():
    """is_revision=true 但无 intent_type → fallback。"""
    llm = MockLLMClient(mock_data={"is_revision": True})
    result = classify_revision_intent(llm, "改一下", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"
```

- [ ] **步骤 4：低置信度触发追问**

```python
def test_low_confidence_sets_classification_failed():
    """LLM 返回置信度 < 0.5 → classification_failed=True。"""
    llm = MockLLMClient(mock_data={
        "is_revision": True,
        "intent_type": None,
        "target_day": None,
        "target_module": None,
        "target_segment": None,
        "scope_type": "unknown",
        "impact_level": "high",
        "confidence": 0.45,
        "clarification_needed": True,
        "clarification_question": "你想改哪一天？",
        "detail": "",
    })
    result = classify_revision_intent(llm, "改一下", _plan_data(), {"last_trip_id": "t1"})
    assert result["classification_failed"] is True
```

- [ ] **步骤 5：非修改消息**

```python
def test_non_revision_message_returns_false():
    """纯聊天 → is_revision=false。"""
    llm = MockLLMClient(mock_data={
        "is_revision": False,
        "intent_type": None,
        "target_day": None,
        "target_module": None,
        "target_segment": None,
        "scope_type": "unknown",
        "impact_level": "high",
        "confidence": 0.95,
        "clarification_needed": False,
        "clarification_question": "",
        "detail": "",
    })
    result = classify_revision_intent(llm, "杭州天气怎么样", _plan_data(), {})
    assert result["is_revision"] is False
```

- [ ] **步骤 6：意图别名兼容**

```python
def test_change_return_time_alias_mapped():
    """规则 fallback 中 change_return_time → return_time_change。"""
    result = classify_revision_intent(None, "晚一点回去", _plan_data(), {"last_trip_id": "t1"})
    assert result["_source"] == "rules"
    if result["is_revision"]:
        assert result["intent_type"] != "change_return_time"
```

- [ ] **步骤 7：运行全部新测试**

```powershell
$env:TMP="D:/Python_Project/RealTripAssistant/.tmp_pytest"; $env:TEMP="D:/Python_Project/RealTripAssistant/.tmp_pytest"; python -m pytest tests/test_revision_intent_classifier.py -q
```

预期：全部通过。

---

## 任务 3：修改 ChatService，用新入口替换旧守卫

**文件：**
- 修改：`travel_planning_agent/core/chat_service.py`

- [ ] **步骤 1：替换 import**

将：
```python
from travel_planning_agent.core.plan_revision import (
    format_plan_data_days_text,
    format_plan_data_summary,
    looks_like_plan_revision,
)
```

改为：
```python
from travel_planning_agent.core.plan_revision import (
    format_plan_data_days_text,
    format_plan_data_summary,
)
from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent
```

- [ ] **步骤 2：替换守卫调用**

将：
```python
if looks_like_plan_revision(message, context):
    revised = self.revision_service_factory(self.db, self.session_store).try_apply(
        session_id, message, context,
    )
```

改为：
```python
# 统一意图分类
revision_intent = None
trip_id = context.get("last_trip_id")
if trip_id:
    from travel_planning_agent.db.models import PlanVersion
    active = (
        self.db.query(PlanVersion)
        .filter(PlanVersion.trip_id == trip_id, PlanVersion.is_active == True)  # noqa: E712
        .order_by(PlanVersion.version.desc())
        .first()
    )
    if active and active.plan_data:
        llm_factory = self.llm_factory or create_llm_client
        llm = llm_factory(mock=not bool(_settings.llm_api_key))
        revision_intent = classify_revision_intent(
            llm, message, active.plan_data, context
        )

if revision_intent and revision_intent.get("is_revision"):
    revised = self.revision_service_factory(self.db, self.session_store).try_apply(
        session_id, message, context, revision_intent,
    )
```

- [ ] **步骤 3：确认旧 import 未被删除**

`looks_like_plan_revision` 仍保留在 `plan_revision.py` 中，作为 fallback 调用方。

---

## 任务 4：透传返程时间窗口

**文件：**
- 修改：`travel_planning_agent/core/plan_revision.py`
- 测试：`tests/test_chat_revision.py`

- [ ] **步骤 1：补充回归测试——parsed_scope 返程时间不丢失**

在 `tests/test_chat_revision.py` 中新增：

```python
def test_parsed_scope_return_revision_preserves_requested_time_window():
    trip = SimpleNamespace(destination="南京", days=2)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = _sample_plan_data()

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "我第二天18点回去",
        context,
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "target_day": 2,
            "change_type": "return_time_change",
            "scope_type": "day",
            "return_start": "18:00",
            "return_end": "20:00",
        },
    )

    assert changed is True
    day2_segments = plan_data["days"][1]["segments"]
    return_segments = [seg for seg in day2_segments if "return" in (seg.get("tags") or [])]
    assert return_segments[-1]["start_time"] == "18:00"
    assert return_segments[-1]["end_time"] == "20:00"
```

- [ ] **步骤 2：运行测试确认失败**

```powershell
python -m pytest tests/test_chat_revision.py::test_parsed_scope_return_revision_preserves_requested_time_window -q
```

预期：失败，因为 `analyze_change_intent()` 尚未透传 `return_start/return_end`。

- [ ] **步骤 3：修改 `analyze_change_intent()` 的 parsed_scope 分支**

在 `travel_planning_agent/core/plan_revision.py` 的 `if parsed_scope:` 分支中，将返回 dict 从：

```python
return {
    "type": change_type,
    "target_day": parsed_scope.get("target_day") or len(plan_data.get("days", []) or [1]),
    "target_module": parsed_scope.get("target_module"),
    "target_segment": parsed_scope.get("target_segment"),
    "requires_tools": change_type in {"rainy_day_backup", "replace_activity"},
}
```

改为：

```python
intent = {
    "type": change_type,
    "target_day": parsed_scope.get("target_day") or len(plan_data.get("days", []) or [1]),
    "target_module": parsed_scope.get("target_module"),
    "target_segment": parsed_scope.get("target_segment"),
    "requires_tools": change_type in {"rainy_day_backup", "replace_activity"},
}
if change_type == "return_time_change":
    intent["return_start"] = parsed_scope.get("return_start") or return_window_from_message(message)[0]
    intent["return_end"] = parsed_scope.get("return_end") or return_window_from_message(message)[1]
return intent
```

- [ ] **步骤 4：运行测试确认通过**

```powershell
python -m pytest tests/test_chat_revision.py::test_parsed_scope_return_revision_preserves_requested_time_window -q
```

预期：`1 passed`。

---

## 任务 5：修改 ChatRevisionService，接收统一 intent

**文件：**
- 修改：`travel_planning_agent/core/chat_revision_service.py`

- [ ] **步骤 1：修改 try_apply 签名和内部逻辑**

删除 import：
```python
# 删除这两行
from travel_planning_agent.core.revision_scope_parser import parse_revision_scope
from travel_planning_agent.core.revision_strategy import choose_revision_strategy
```

`try_apply` 方法增加 `revision_intent` 参数，内部改为：

```python
def try_apply(self, session_id: str, message: str, context: dict, revision_intent: dict):
    from travel_planning_agent.agent.revision import RevisionAgent
    from travel_planning_agent.db.models import PlanVersion, Trip
    from travel_planning_agent.llm import create_llm_client

    trip_id = context.get("last_trip_id")
    trip = self.db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        return None

    active = (
        self.db.query(PlanVersion)
        .filter(PlanVersion.trip_id == trip_id, PlanVersion.is_active == True)  # noqa: E712
        .order_by(PlanVersion.version.desc())
        .first()
    )
    if not active:
        return None

    plan_data = dict(active.plan_data or {})

    # ── clarification / classification_failed → 追问 ──
    if revision_intent.get("classification_failed"):
        return ChatServiceResult(
            type="question",
            content="我不太确定你想怎么改，可以具体说一下吗？比如改哪一天、哪个景点？",
            trip_id=trip_id,
            session_id=session_id,
        )
    if revision_intent.get("clarification_needed"):
        return ChatServiceResult(
            type="question",
            content=revision_intent.get("clarification_question", "你想具体怎么修改？"),
            trip_id=trip_id,
            session_id=session_id,
        )

    intent_type = revision_intent.get("intent_type")
    scope_type = revision_intent.get("scope_type")

    # ── 策略路由（仅放行本期支持的 3 种类型） ──
    if intent_type in {"lighten_day", "remove_segment", "return_time_change"} and scope_type in {
        "segment", "day_module", "day",
    }:
        pass  # → patch_scope，继续执行
    else:
        # 不支持的类型 → 追问
        return ChatServiceResult(
            type="question",
            content="你想改哪一天，还是改某个具体景点/时段？",
            trip_id=trip_id,
            session_id=session_id,
        )

    # ── 构建 parsed_scope 兼容格式传给 apply_change_request_to_plan ──
    parsed_scope = {
        "matched": True,
        "target_day": revision_intent.get("target_day"),
        "target_module": revision_intent.get("target_module"),
        "target_segment": revision_intent.get("target_segment"),
        "change_type": revision_intent.get("intent_type"),
        "scope_type": revision_intent.get("scope_type"),
        "impact_level": revision_intent.get("impact_level"),
        "clarification_needed": False,
        "clarification_question": "",
    }
    if intent_type == "return_time_change":
        from travel_planning_agent.core.plan_revision import return_window_from_message

        return_start, return_end = return_window_from_message(message)
        parsed_scope["return_start"] = return_start
        parsed_scope["return_end"] = return_end

    llm = create_llm_client(mock=not bool(_settings.llm_api_key))
    changed = apply_change_request_to_plan(
        plan_data, trip, message, context,
        RevisionAgent(llm),
        parsed_scope=parsed_scope,
    )
    if not changed:
        return None

    # ── 持久化（同原来） ──
    self.db.query(PlanVersion).filter(PlanVersion.trip_id == trip_id).update({"is_active": False})
    new_version = (active.version or 0) + 1
    new_plan = PlanVersion(
        trip_id=trip_id,
        version=new_version,
        plan_data=plan_data,
        verification={"overall_pass": True, "warnings": [{"detail": "用户做了局部行程修订"}]},
        diff_previous={"reason": message, "type": "change_request_revision"},
        is_active=True,
    )
    trip.days = len(plan_data.get("days", [])) or trip.days
    trip.status = "completed"
    self.db.add(new_plan)

    context["last_plan_version"] = new_version
    context.setdefault("extracted", {})["days"] = trip.days
    record_revision_note(
        context, message=message, trace_id=context.get("last_trace_id"),
        trip_id=trip_id, plan_version=new_version,
    )
    self.session_store.append_message(context, "user", message)
    self.db.commit()

    summary = format_plan_data_summary(plan_data, trip)
    plan_view = format_plan_view(plan_data, trip=trip, summary=summary)
    content = (
        "已根据你的要求重新规划了受影响的行程，并保留未受影响的部分。\n\n"
        f"{format_plan_data_days_text(plan_data)}"
    )
    return ChatServiceResult(
        type="plan_result", content=content, trip_id=trip_id,
        plan_summary=summary, session_id=session_id, plan=plan_view,
    )
```

- [ ] **步骤 2：移除不再需要的旧 import**

确认 `chat_revision_service.py` 中不再有 `parse_revision_scope` 和 `choose_revision_strategy` 的导入。

- [ ] **步骤 3：运行修订相关回归测试**

```powershell
python -m pytest tests/test_chat_revision.py tests/test_chat_api.py -q
```

预期：全部通过。

---

## 任务 6：最终验证

- [ ] **步骤 1：运行全部测试**

```powershell
$env:TMP="D:/Python_Project/RealTripAssistant/.tmp_pytest"; $env:TEMP="D:/Python_Project/RealTripAssistant/.tmp_pytest"; python -m pytest tests/ -q --tb=short
```

预期：全部通过。

- [ ] **步骤 2：确认旧文件保留**

```powershell
if (Test-Path "travel_planning_agent/core/revision_scope_parser.py") { "OK" } else { "FAIL" }
if (Test-Path "travel_planning_agent/core/revision_strategy.py") { "OK" } else { "FAIL" }
if (Test-Path "travel_planning_agent/core/plan_revision.py") { "OK" } else { "FAIL" }
```

- [ ] **步骤 3：完整导入链验证**

```powershell
python -c "from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent; print('classifier OK')"
python -c "from travel_planning_agent.core.revision_scope_parser import parse_revision_scope; print('fallback OK')"
python -c "from travel_planning_agent.core.chat_service import ChatService; print('chat_service OK')"
python -c "from travel_planning_agent.core.chat_revision_service import ChatRevisionService; print('revision_service OK')"
```

---

## 自检结果

核心原则落实：
- **LLM 接口正确**：`generate(system_prompt, user_message, tools=None) -> LLMResult`，优先读 `result.data`。
- **result 变量安全**：`result: Optional[dict] = None` 在 if 块之前初始化。
- **严格 schema 校验**：缺少 `is_revision` 或置信度字段 → 返回 None → 触发规则兜底；`clarification_needed=true` 时允许 `intent_type=null`。
- **fallback 守门**：`is_revision = is_rev and (matched or clarification_needed)`，两次判断取交集。
- **intent 枚举统一**：统一标准名 `return_time_change`，兼容层映射 `change_return_time`。
- **策略边界收敛**：自动执行仅 `lighten_day / remove_segment / return_time_change`，其余追问。

范围控制：
- 没有删除任何旧文件。
- 没有修改 `RevisionAgent`、`apply_change_request_to_plan()`。
- 没有修改前端。

受影响文件：

| 文件 | 操作 | 行数估计 |
|------|------|----------|
| `core/revision_intent_classifier.py` | **新增** | ~160 行 |
| `tests/test_revision_intent_classifier.py` | **新增** | ~120 行 |
| `core/chat_service.py` | 修改 | ~20 行 |
| `core/chat_revision_service.py` | 修改 | ~40 行 |
| `core/plan_revision.py` | 修改 | ~8 行 |

后续清理（不在本期范围）：
- LLM 分类覆盖率达标后删除 `revision_scope_parser.py`。
- 补充 `rainy_day_backup / replace_activity / reduce_budget / append_day` 的执行策略后放行。
- `looks_like_plan_revision()` 移入 `_classify_via_rules` 内部。
