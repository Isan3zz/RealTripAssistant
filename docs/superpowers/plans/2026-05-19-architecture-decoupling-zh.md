# 架构解耦清理：消除伪解耦层，强化真实边界

> **给执行代理的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。所有步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 清理项目中"看起来像解耦、实际不承载抽象价值"的转发层，同时修正跨层依赖方向，让真正有效的协议解耦（Agent 协议、工具门面、API 路由）更突出。

**架构原则：** 解耦靠协议/接口，不靠转发层。每层只依赖其下层，不依赖上层。

**技术栈：** Python 3.11、FastAPI、pytest。

---

## 范围

本期包含：
- 删除 `DailyPipelineRunner` 纯转发层，SupervisorAgent 内部直接调用。
- 移除 SupervisorAgent 对 product 层函数 `normalize_final_day_departure` 的跨层依赖。
- 清理 `PlanRunService` 中不依赖 `self` 的薄包装方法。
- 合并 `tool_runtime.py` 和 `tools/registry.py` 为一个工具系统文件。

本期不包含：
- 修改 Agent 协议本身（BaseAgent / AgentRequest / AgentResponse 保持不动）。
- 修改 PlanState 数据结构。
- 修改 API 路由层。
- 修改修订系统（单独一个 plan）。
- 任何功能行为变更——纯重构，所有现有测试必须通过。

---

## 文件结构

删除：
- `travel_planning_agent/core/daily_pipeline.py`
  逻辑内联回 `SupervisorAgent._run_pipeline_loop`。

修改：
- `travel_planning_agent/agent/supervisor.py`
  移除 `from travel_planning_agent.core.planning_runtime import normalize_final_day_departure`，删除 `DailyPipelineRunner` 导入，`_run_pipeline_loop` 直接调 `_run_pipeline_loop_impl`。

- `travel_planning_agent/core/plan_run_service.py`
  移除不依赖 `self` 的薄包装方法，调用处直接使用模块级函数。

- `travel_planning_agent/tool_runtime.py`
  将 `tools/registry.py` 的 `PARAM_ALIASES`、`_tool_agents`、`register_all_tools`、`execute_tool` 合并进来。

- `travel_planning_agent/tools/registry.py`
  删除，内容合并到 `tool_runtime.py`。

- `travel_planning_agent/tools/__init__.py`
  更新 import 路径，对外 API 不变。

- `travel_planning_agent/core/planning_runtime.py`
  确认 `normalize_final_day_departure` 仅从 `plan_run_service.py` 调用（SupervisorAgent 不再依赖它）。

---

## 任务 1：删除 DailyPipelineRunner，内联到 SupervisorAgent

**文件：**
- 修改：`travel_planning_agent/agent/supervisor.py`
- 修改：`travel_planning_agent/core/plan_run_service.py`（移除 DailyPipelineRunner 导入）
- 删除：`travel_planning_agent/core/daily_pipeline.py`

- [ ] **步骤 1：运行现有测试确认基线**

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
python -m pytest tests/ -q --tb=short
```

记录测试结果作为基线。预期：全部通过（或有已知失败，记录下来）。

- [ ] **步骤 2：修改 SupervisorAgent._run_pipeline_loop**

在 `travel_planning_agent/agent/supervisor.py` 中，将：

```python
def _run_pipeline_loop(self, state: PlanState):
    from travel_planning_agent.core.daily_pipeline import DailyPipelineRunner
    return DailyPipelineRunner(self).run(state)
```

改为：

```python
def _run_pipeline_loop(self, state: PlanState):
    return self._run_pipeline_loop_impl(state)
```

- [ ] **步骤 3：清理 PlanRunService 中的 DailyPipelineRunner 导入**

在 `travel_planning_agent/core/plan_run_service.py` 中，确认没有 `from travel_planning_agent.core.daily_pipeline import DailyPipelineRunner`。

- [ ] **步骤 4：检查 daily_pipeline.py 的所有引用**

```powershell
python -m ripgrep "daily_pipeline" --glob "*.py" travel_planning_agent/
```

确认只剩 `planning_state_service.py` 的引用（PlanningStateService 是独立使用的）。

- [ ] **步骤 5：删除 daily_pipeline.py**

删除 `travel_planning_agent/core/daily_pipeline.py`。

- [ ] **步骤 6：运行测试确认无回归**

```powershell
python -m pytest tests/ -q --tb=short
```

预期：与基线一致。

---

## 任务 2：移除 SupervisorAgent 对 product 层函数的跨层依赖

**文件：**
- 修改：`travel_planning_agent/agent/supervisor.py`
- 修改：`travel_planning_agent/core/plan_run_service.py`

**问题分析：** `SupervisorAgent._run_pipeline_loop_impl` 在流水线末尾调用了 `normalize_final_day_departure(state)`。但此函数属于 product 层（定义在 `plan_run_service.py`），且 `PlanRunService.run()` 之后又调了一次 `self._normalize_final_day_departure(state)`。职责归属不清。

**方案：** `normalize_final_day_departure` 统一由 `PlanRunService` 在 pipeline 完成后调用。SupervisorAgent 不再知道此函数。

- [ ] **步骤 1：从 SupervisorAgent 移除 normalize_final_day_departure**

在 `travel_planning_agent/agent/supervisor.py` 中：

移除导入：
```python
from travel_planning_agent.core.planning_runtime import normalize_final_day_departure
```

在 `_run_pipeline_loop_impl` 中，将：
```python
# Polish
self._run_polish(state)
normalize_final_day_departure(state)
```

改为：
```python
# Polish
self._run_polish(state)
```

- [ ] **步骤 2：确认 PlanRunService 已覆盖此调用**

在 `travel_planning_agent/core/plan_run_service.py` 的 `run()` 方法中，确认：
```python
self._normalize_final_day_departure(state)
```
已经存在。此调用在 supervisor 返回之后执行，覆盖了原来的双重调用。

- [ ] **步骤 3：检查 normalize_final_day_departure 的导入来源**

```powershell
python -m ripgrep "normalize_final_day_departure" --glob "*.py" travel_planning_agent/
```

确认 `planning_runtime.py` 中的 re-export 是否仍然需要。如果 `planning_runtime.py` 只是 re-export，可以从那里移除，`plan_run_service.py` 直接定义和使用。

- [ ] **步骤 4：运行测试确认无回归**

```powershell
python -m pytest tests/ -q --tb=short
```

预期：与基线一致。如果与"最后一天返程交通"相关的测试失败，检查 normalize 调用顺序是否正确（PlanRunService 在 pipeline 之后调用）。

---

## 任务 3：清理 PlanRunService 的薄包装方法

**文件：**
- 修改：`travel_planning_agent/core/plan_run_service.py`

**问题分析：** `PlanRunService` 中有多个实例方法体只做了一件事——调用同文件的模块级函数，且不使用 `self`：

```python
def _ensure_required_plan_content(self, state, spec):
    ensure_required_plan_content(state, spec)

def _normalize_final_day_departure(self, state):
    normalize_final_day_departure(state)

def _normalize_intercity_departure(self, state):
    normalize_intercity_departure(state)  # 注意：模块级函数名是 normalize_intercity_departure

def _verify_whole_plan(self, state):
    return verify_whole_plan(state)

def _apply_profile(self, spec, profile):
    return apply_profile(spec, profile)
```

**方案：** 调用处直接使用模块级函数，删除薄包装方法。保留 `_build_global_execution_plan` 和 `_execute_execution_plan`（它们用了 keyword arguments 的默认值转发，有实际意义）。

- [ ] **步骤 1：替换调用处——_ensure_required_plan_content**

在 `run()` 方法中，将：
```python
self._ensure_required_plan_content(state, spec)
```
改为：
```python
ensure_required_plan_content(state, spec)
```

然后删除 `_ensure_required_plan_content` 方法。

- [ ] **步骤 2：替换调用处——_normalize_intercity_departure**

在 `run()` 方法中，将：
```python
self._normalize_intercity_departure(state)
```
改为：
```python
normalize_intercity_departure(state)
```

然后删除 `_normalize_intercity_departure` 方法。

- [ ] **步骤 3：替换调用处——_normalize_final_day_departure**

在 `run()` 方法中，将：
```python
self._normalize_final_day_departure(state)
```
改为：
```python
normalize_final_day_departure(state)
```

然后删除 `_normalize_final_day_departure` 方法。

- [ ] **步骤 4：替换调用处——_verify_whole_plan**

在 `run()` 方法中，将：
```python
state.validation = self._verify_whole_plan(state)
```
改为：
```python
state.validation = verify_whole_plan(state)
```

然后删除 `_verify_whole_plan` 方法。

- [ ] **步骤 5：替换调用处——_apply_profile**

在 `run()` 方法中，将：
```python
constraints = self._apply_profile(spec, profile).to_constraints()
```
改为：
```python
constraints = apply_profile(spec, profile).to_constraints()
```

然后删除 `_apply_profile` 方法。

- [ ] **步骤 6：保留有实际意义的方法**

确认以下方法保留（它们有实际逻辑或转发参数）：
- `_build_global_execution_plan` — 有默认参数转发
- `_execute_execution_plan` — 有默认参数转发
- `_record_event` — 有默认参数转发
- `_plan_data_from_state` — 有默认参数转发
- `_verification_to_dict` — 有默认参数转发
- `_final_status_for_state` — 有实际逻辑

- [ ] **步骤 7：运行测试确认无回归**

```powershell
python -m pytest tests/ -q --tb=short
```

预期：与基线一致。

---

## 任务 4：合并 tool_runtime.py 和 tools/registry.py

**文件：**
- 修改：`travel_planning_agent/tool_runtime.py`
- 修改：`travel_planning_agent/tools/__init__.py`
- 删除：`travel_planning_agent/tools/registry.py`

**问题分析：** 工具注册分散在两个文件中——`tool_runtime.py`（ToolRegistry 基础设施）和 `tools/registry.py`（参数别名、agent 映射、注册装配）。两者都是"注册"这一件事，合并后减少依赖跳数，对外 API 不变。

- [ ] **步骤 1：将 registry.py 的内容合并到 tool_runtime.py**

在 `tool_runtime.py` 末尾追加：

```python
# ═══════════════════════════════════════════════════
#  工具注册装配（原 tools/registry.py）
# ═══════════════════════════════════════════════════

import logging
from travel_planning_agent.tools.handlers import HANDLERS
from travel_planning_agent.tools.schemas import get_all_tool_schemas

logger = logging.getLogger(__name__)

PARAM_ALIASES = {
    "query_ticket_price": {"destination": "scenic_name", "name": "scenic_name", "spot": "scenic_name"},
    "search_poi": {"keyword": "context", "name": "context", "query": "context"},
    "get_poi_detail": {"poi_id": "id"},
    "search_hotel": {
        "name": "keyword",
        "hotel": "keyword",
        "near": "nearby",
        "landmark": "nearby",
        "scenic_name": "nearby",
        "spot": "nearby",
        "area": "nearby",
    },
    "search_train": {"start": "from_station", "end": "to_station", "from": "from_station", "to": "to_station"},
    "search_flight": {"start": "from_city", "end": "to_city", "from_city": "from_city", "to_city": "to_city"},
}


def _tool_agents(name: str) -> list[str]:
    if name == "get_current_date":
        return ["intake"]
    if name in {
        "search_poi", "query_ticket_price", "search_hotel", "get_hotel_detail",
        "search_flight", "search_train", "search_around", "geo_encode",
    }:
        return ["researcher"]
    if name == "get_weather_forecast":
        return ["researcher", "planner"]
    if name in {"get_driving_eta", "get_walking_route", "get_transit_route"}:
        return ["planner"]
    return ["__not_exposed_to_agents__"]


def _execute_handler(tool_name: str, tool_input: dict) -> str:
    handler = HANDLERS.get(tool_name)
    if not handler:
        try:
            from travel_planning_agent.gaode_client import _call_tool, resolve_mcp_tool_name
            result = _call_tool(resolve_mcp_tool_name(tool_name), tool_input)
            return str(result) if result else f"错误：未知工具 '{tool_name}'"
        except Exception:
            return f"错误：未知工具 '{tool_name}'"

    try:
        result = handler(**tool_input)
        logger.info("工具 %s 调用成功", tool_name)
        return result
    except TypeError as e:
        return f"错误：工具 '{tool_name}' 参数不匹配 - {e}"
    except Exception as e:
        logger.warning("工具 %s 异常: %s", tool_name, e)
        return f"{tool_name}: 查询失败，请稍后重试"


def register_all_tools() -> None:
    for schema in get_all_tool_schemas():
        name = schema.get("function", {}).get("name", "")
        register_openai_tool(
            schema,
            agents=_tool_agents(name),
            handler=lambda args, _name=name: _execute_handler(_name, args),
            param_aliases=PARAM_ALIASES.get(name, {}),
        )


register_all_tools()

TOOLS_DEFINITION: list = openai_tools_for_agent("*")
EXTRACTION_TOOLS: list = openai_tools_for_agent("intake")
RESEARCHER_TOOLS: list = openai_tools_for_agent("researcher")
PLANNER_TOOLS: list = openai_tools_for_agent("planner")


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """工具执行入口，保持字符串 API 供 Agent 使用。"""
    result = execute_registered_tool(tool_name, tool_input)
    return result.data or result.error or ""
```

- [ ] **步骤 2：更新 tools/__init__.py 的导入路径**

将 `travel_planning_agent/tools/__init__.py` 中对 `registry` 的导入改为从 `tool_runtime` 导入：

```python
from travel_planning_agent.tool_runtime import (
    TOOLS_DEFINITION,
    EXTRACTION_TOOLS,
    RESEARCHER_TOOLS,
    PLANNER_TOOLS,
    execute_tool,
    register_all_tools,
)
```

确认对外 API 完全不变——下游 `from travel_planning_agent.tools import execute_tool` 仍然正常工作。

- [ ] **步骤 3：检查所有对 registry 的引用**

```powershell
python -m ripgrep "from travel_planning_agent.tools.registry" --glob "*.py" travel_planning_agent/
python -m ripgrep "from travel_planning_agent.tools import.*registry" --glob "*.py" travel_planning_agent/
```

更新所有引用为从 `tool_runtime` 或 `tools` 导入。

- [ ] **步骤 4：删除 tools/registry.py**

删除 `travel_planning_agent/tools/registry.py`。

- [ ] **步骤 5：运行测试确认无回归**

```powershell
python -m pytest tests/ -q --tb=short
```

预期：与基线一致。

---

## 任务 5：最终验证

- [ ] **步骤 1：确认所有导入链干净**

```powershell
python -c "from travel_planning_agent.tools import execute_tool, TOOLS_DEFINITION; print('tools OK')"
python -c "from travel_planning_agent.agent.supervisor import SupervisorAgent; print('supervisor OK')"
python -c "from travel_planning_agent.core.plan_run_service import PlanRunService; print('plan_run_service OK')"
python -c "from travel_planning_agent.tool_runtime import execute_tool, register_all_tools; print('tool_runtime OK')"
```

- [ ] **步骤 2：运行完整测试套件**

```powershell
$env:TMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
$env:TEMP='D:\Python_Project\RealTripAssistant\.tmp_pytest'
python -m pytest tests/ -q --tb=short
```

预期：全部通过，与重构前基线一致。

- [ ] **步骤 3：确认已删除文件不存在**

```powershell
test -f travel_planning_agent/core/daily_pipeline.py && echo "FAIL: daily_pipeline 未删除" || echo "OK"
test -f travel_planning_agent/tools/registry.py && echo "FAIL: registry 未删除" || echo "OK"
```

---

## 验证方式

重构前后对比：

```powershell
# 重构前记录
python -m pytest tests/ -q --tb=short > before.txt 2>&1

# 执行重构...

# 重构后对比
python -m pytest tests/ -q --tb=short > after.txt 2>&1
diff before.txt after.txt
```

预期：无差异（或只有测试运行时间差异）。

---

## 自检结果

架构原则：
- 解耦靠协议/接口，不靠转发层。删除了 `DailyPipelineRunner` 这个不承载抽象价值的中间层。
- 每层只依赖其下层。移除了 SupervisorAgent（agent 层）→ `normalize_final_day_departure`（product 层）的跨层依赖。
- 薄包装方法不增加解耦价值。清理了 PlanRunService 中 5 个"只转发不做事"的方法。
- 一件事一个地方。合并了工具注册的 `tool_runtime.py` + `registry.py`。

范围控制：
- 没有修改 Agent 协议。
- 没有修改 PlanState 数据结构。
- 没有修改 API 路由。
- 没有修改功能行为——纯重构，所有测试必须通过。
- 没有引入新的依赖或框架。

风险：
- 低风险重构。所有修改都是"删除转发层 + 内联调用"，逻辑不变。
- 如果任务 2 中 normalize 调用顺序变更导致"最后一天返程交通"相关测试失败，检查 PlanRunService.run() 中的调用位置即可。

受影响文件（4 删 + 4 改）：

| 文件 | 操作 |
|------|------|
| `core/daily_pipeline.py` | 删除 |
| `tools/registry.py` | 删除 |
| `agent/supervisor.py` | 修改（移除 DailyPipelineRunner + normalize_final_day_departure 导入） |
| `core/plan_run_service.py` | 修改（移除薄包装方法） |
| `tool_runtime.py` | 修改（合并 registry 内容） |
| `tools/__init__.py` | 修改（更新导入路径） |

文件净减少：2 个。代码行净减少：约 40 行。
