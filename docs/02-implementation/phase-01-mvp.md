# Phase 1 (MVP) 实现规格书

## 1. 本阶段目标与边界

**目标**：用户通过 CLI 输入旅行需求 → 系统输出经过 4 条确定性规则校验的结构化 Markdown 行程

**范围（In Scope）**：
- CLI 交互式信息收集（目的地、日期、人数、预算、节奏偏好）
- 单 LLM Agent 规划生成（Orchestrator 合一）
- 4 条确定性规则校验（时间不重叠 / 预算不超限 / 日期不越界 / 必填项完整）
- 校验失败后自动触发重规划（最多 3 轮）
- 输出 Markdown 行程到文件系统
- 结构化 state 持久化到 JSON

**不在范围（Out of Scope）**：
- 多 Agent 拆分（Phase 2）
- SQLite / 数据库（Phase 2）
- Web UI（Phase 3）
- 语义合理性判断（Phase 2）
- 外部 API 查询（依赖 LLM 内置知识）

---

## 2. 文件目录树

```
travel_planning_agent/
├── main.py                      # 入口：初始化 → 启动 CLI
├── cli.py                       # CLI 交互：信息收集 + 结果展示
├── types.py                     # 所有数据类型定义
├── state.py                     # 状态机定义 + 状态流转
├── orchestrator.py              # Agent 主循环：LLM 调用 + 工具
├── prompts.py                   # 系统提示词模板
├── tools.py                     # LLM tool 定义（search_poi 等）
├── engine/
│   ├── __init__.py
│   ├── rule_engine.py           # 规则引擎入口：编排所有规则
│   └── rules.py                 # 4 条确定性规则实现
├── storage/
│   ├── __init__.py
│   └── file_store.py            # 文件读写：state.json / trip.md / evidence
└── tests/
    ├── test_rules.py            # 规则单元测试
    ├── test_state.py            # 状态机测试
    └── test_end_to_end.py       # 端到端验收测试
```

---

## 3. 核心数据结构

```python
"""
types.py — 所有数据类型定义
"""
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from typing import Optional


# ── 枚举 ──────────────────────────────────────────────

class TripStatus(Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    COMPLETED = "completed"
    FAILED = "failed"

class SegmentType(Enum):
    ACTIVITY = "activity"
    TRANSPORT = "transport"
    MEAL = "meal"
    ACCOMMODATION = "accommodation"

class PlanPhase(Enum):
    INIT = "init"
    INTAKE = "intake"
    PLANNING = "planning"
    RULE_CHECK = "rule_check"
    REVISE = "revise"
    OUTPUT = "output"
    DONE = "done"
    FAILED = "failed"


# ── 游客 ──────────────────────────────────────────────

@dataclass
class Traveler:
    age_group: str              # "adult" / "elderly" / "child"
    note: str = ""


# ── 约束 ──────────────────────────────────────────────

@dataclass
class Constraints:
    destination: str
    start_date: date
    end_date: int               # 天数（如 4 表示 4 天）
    travelers: list[Traveler]
    budget: float               # 总预算上限（CNY）
    pace: str                   # "slow" / "moderate" / "fast"
    interests: list[str] = field(default_factory=list)  # ["文化", "美食", "自然"]


# ── 报价/费用 ─────────────────────────────────────────

@dataclass
class Cost:
    amount: float
    currency: str = "CNY"


# ── 位置 ──────────────────────────────────────────────

@dataclass
class Location:
    name: str
    city: str
    lat: Optional[float] = None
    lng: Optional[float] = None


# ── 证据 ──────────────────────────────────────────────

@dataclass
class Evidence:
    evidence_id: str
    source: str                  # "景区官网" / "模型知识"
    url: Optional[str] = None
    retrieved_at: str = ""       # ISO 格式字符串
    url_reachable: Optional[bool] = None
    url_checked_at: Optional[str] = None
    claim: str = ""              # "开放时间 07:00-18:00"


# ── 行程片段 ──────────────────────────────────────────

@dataclass
class Segment:
    segment_id: str
    type: SegmentType = SegmentType.ACTIVITY
    title: str = ""
    start_time: Optional[str] = None   # "09:30"
    end_time: Optional[str] = None     # "11:30"
    location: Optional[Location] = None
    estimated_cost: Optional[Cost] = None
    tags: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    note: str = ""


# ── 某一天的行程 ──────────────────────────────────────

@dataclass
class ItineraryDay:
    day_id: str
    day_number: int              # 第几天（1-based）
    theme: str = ""              # "抵达与适应"
    segments: list[Segment] = field(default_factory=list)


# ── 校验结果 ──────────────────────────────────────────

@dataclass
class RuleResult:
    rule_id: str                 # "R01" / "R02" / ...
    name: str
    result: str                  # "PASS" / "FAIL"
    severity: str = "high"       # "high" / "medium" / "low"
    detail: str = ""
    affected_segments: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    overall_pass: bool
    rules: list[RuleResult] = field(default_factory=list)


# ── 规划状态（持久化核心） ────────────────────────────

@dataclass
class PlanState:
    trip_id: str
    status: TripStatus = TripStatus.DRAFT
    constraints: Optional[Constraints] = None
    days: list[ItineraryDay] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)  # evidence_id → Evidence
    validation: Optional[ValidationResult] = None
    revision_count: int = 0
    max_revisions: int = 3
    phase: PlanPhase = PlanPhase.INIT
    error: Optional[str] = None
```

---

## 4. 核心接口定义

### 4.1 规则引擎

```python
"""
engine/rules.py — 4 条确定性规则
每条规则是一个函数：接受 PlanState，返回 RuleResult
"""

def check_time_non_overlap(state: PlanState) -> RuleResult:
    """
    R01: 同一天内相邻活动时间不得重叠
    start_time[n+1] >= end_time[n]
    
    逻辑：
      遍历 state.days 中的每一天
        按 start_time 排序 segments
        相邻两条比较：
          如果 seg[i+1].start_time < seg[i].end_time → FAIL
          如果 seg[i].end_time 或 seg[i+1].start_time 为空 → 跳过该对
    返回：RuleResult(rule_id="R01", name="时间连续性", ...)
    """

def check_budget_not_exceeded(state: PlanState) -> RuleResult:
    """
    R02: 所有 segment 费用之和 <= 预算上限
    
    逻辑：
      遍历所有 days[*].segments
        累加 segment.estimated_cost.amount
      如果 total > state.constraints.budget → FAIL
    注意：无费用的 segment（如步行）不算入
    返回：RuleResult(rule_id="R02", name="预算", ...)
    """

def check_date_in_bounds(state: PlanState) -> RuleResult:
    """
    R03: 所有行程日期在旅行起止日期范围内
    
    逻辑：
      day_number 必须 >= 1 且 <= constraints.end_date
      如果任何 day_number 超出范围 → FAIL
    返回：RuleResult(rule_id="R03", name="日期边界", ...)
    """

def check_required_fields_complete(state: PlanState) -> RuleResult:
    """
    R04: 每天至少有一个 ACTIVITY 类型的 segment
    
    逻辑：
      遍历每一天
        检查 segments 中是否存在 type == ACTIVITY 的项
        如果某天没有 → FAIL
      同时检查：每个 segment 必须有关键字段（title 非空）
    返回：RuleResult(rule_id="R04", name="必填完整性", ...)
    """
```

```python
"""
engine/rule_engine.py — 规则引擎编排
"""

from .rules import (
    check_time_non_overlap,
    check_budget_not_exceeded,
    check_date_in_bounds,
    check_required_fields_complete,
)

# 规则注册表：所有规则在此注册，引擎自动遍历
RULES_REGISTRY = [
    ("R01", "时间连续性", check_time_non_overlap),
    ("R02", "预算", check_budget_not_exceeded),
    ("R03", "日期边界", check_date_in_bounds),
    ("R04", "必填完整性", check_required_fields_complete),
]

def run_rule_engine(state: PlanState) -> ValidationResult:
    """
    执行所有注册规则，聚合结果。
    
    逻辑：
      results = []
      for rule_id, name, check_fn in RULES_REGISTRY:
          result = check_fn(state)
          results.append(result)
      
      overall_pass = all(r.result == "PASS" for r in results)
      
      返回 ValidationResult(overall_pass=overall_pass, rules=results)
    """
```

### 4.2 存储接口

```python
"""
storage/file_store.py
"""

def init_trip_dir(trip_id: str) -> str:
    """创建 data/trips/{trip_id}/ 目录，返回路径"""

def save_state(state: PlanState):
    """将 PlanState 序列化为 JSON，写入 data/trips/{trip_id}/state.json"""

def load_state(trip_id: str) -> PlanState:
    """从 data/trips/{trip_id}/state.json 读取并反序列化"""

def save_trip_md(state: PlanState):
    """将行程渲染为 Markdown，写入 data/trips/{trip_id}/trip.md"""

def save_evidence(state: PlanState):
    """将 evidence 字典逐条写入 data/trips/{trip_id}/evidence/ev_{id}.json"""

def list_trips() -> list[str]:
    """列出 data/trips/ 下所有 trip_id"""
```

### 4.3 CLI 交互

```python
"""
cli.py — 命令行交互
"""

def run_cli() -> Constraints:
    """
    交互式收集旅行需求。
    
    流程：
      1. 输出欢迎信息
      2. 逐个提问：
         - 目的地: input("目的地是哪里？")
         - 开始日期: input("出发日期？(YYYY-MM-DD)")
         - 天数: input("旅行几天？")
         - 人数: input("几个人？是否有老人/小孩？")
         - 总预算: input("总预算是多少？(CNY)")
         - 节奏偏好: input("节奏偏好？(慢/中/快)")
         - 兴趣: input("感兴趣的类型？(文化/美食/自然/购物…)")
      3. 汇总确认后返回 Constraints 对象
    """

def print_trip(state: PlanState):
    """
    输出行程到终端（彩色 Markdown 预览）。
    
    格式：
      ────────────────────────────────
      Day 1 — 抵达与适应
      ────────────────────────────────
      上午: 09:30-11:30  灵隐寺  [文化]
      中午: 12:00-13:00  午餐
      下午: 14:00-17:00  西湖游船 [自然]
      
      校验状态: ✅ 通过 (0 失败)
    """

def print_validation(validation: ValidationResult):
    """
    输出校验结果。
    
    通过：
      ✅ R01 时间连续性: PASS
      ✅ R02 预算: PASS
      ...
    
    失败：
      ❌ R01 时间连续性: FAIL — Day 2 灵隐寺(09:30-11:30)与...
      ❌ R02 预算: FAIL — 总花费 22,500 > 预算 20,000
    """
```

### 4.4 LLM 工具

```python
"""
tools.py — LLM 可调用的工具定义
"""

def search_poi(destination: str, category: str, context: str) -> str:
    """
    搜索 POI。Phase 1 依赖 LLM 内置知识，直接返回知识文本。
    
    参数：
      destination: 目的地城市
      category: "cultural" / "natural" / "food" / "shopping"
      context: 搜索背景（如"适合老人的文化景点"）
    
    返回：
      结构化文本描述 POI（名称、简介、预估开放时间、预估费用）
    """

def get_weather_forecast(city: str, date: str) -> str:
    """
    获取天气预报。Phase 1 依赖 LLM 内置知识。
    
    返回：
      文本描述（如"预计 5 月杭州气温 18-25°C，可能有小雨"）
    """

TOOLS_DEFINITION = [
    {
        "name": "search_poi",
        "description": "搜索目的地的景点/餐厅/活动信息",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "目的地城市"},
                "category": {"type": "string", "enum": ["cultural", "natural", "food", "shopping", "accommodation"]},
                "context": {"type": "string", "description": "搜索背景和约束"}
            },
            "required": ["destination", "category"]
        }
    },
    {
        "name": "get_weather_forecast",
        "description": "获取目的地在指定日期的天气预报",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "date": {"type": "string"}
            },
            "required": ["city", "date"]
        }
    }
]
```

### 4.5 提示词

```python
"""
prompts.py — 系统提示词模板
"""

SYSTEM_PROMPT = """你是一个旅行规划助手。你的职责是根据用户的旅行需求，生成一份完整的行程计划。

## 核心规则

1. 用户提供：目的地、日期、人数、预算、节奏偏好
2. 你需要安排每日的活动、餐饮，确保行程合理
3. 使用 search_poi 工具获取景点信息
4. 使用 get_weather_forecast 工具获取天气信息

## 输出要求

你必须严格按照以下 JSON 格式输出行程结果（不要 markdow 包裹，纯 JSON）： 

```json
{
  "days": [
    {
      "day_number": 1,
      "theme": "主题描述",
      "segments": [
        {
          "type": "activity",
          "title": "景点名称",
          "start_time": "09:00",
          "end_time": "11:00",
          "location": {"name": "名称", "city": "城市"},
          "estimated_cost": {"amount": 50, "currency": "CNY"},
          "tags": ["cultural"],
          "evidence": [{"source": "模型知识", "claim": "开放时间..."}]
        }
      ]
    }
  ]
}
```

## 约束提醒

- 每天的活动时间不要排太满
- 相邻活动之间预留合理的交通时间
- 总花费不要超过用户预算
- 如果用户带了老人，减少步行量，安排休息
- 所有时间使用 24 小时格式 HH:MM"""

REVISE_PROMPT = """用户上一次生成的行程有以下问题：

{validation_errors}

请针对这些问题修改行程。注意：
- 不要改变已经满足的约束
- 只修改有问题的部分
- 输出格式与之前相同（纯 JSON）
- 已修订次数：{revision_count}/{max_revisions}"""
```

---

## 5. 主循环 / 状态机

```python
"""
state.py — 状态机定义
"""

class StateMachine:
    """
    5 状态状态机：
    INIT → INTAKE → PLANNING → RULE_CHECK → OUTPUT → DONE
                       ↑            ↓
                       └── REVISE ←─┘
    
    每个阶段的 enter/exit 逻辑由 orchestrator 实现，
    状态机本身只管理状态合法性。
    """
    
    TRANSITIONS = {
        PlanPhase.INIT:     [PlanPhase.INTAKE, PlanPhase.FAILED],
        PlanPhase.INTAKE:   [PlanPhase.PLANNING, PlanPhase.FAILED],
        PlanPhase.PLANNING: [PlanPhase.RULE_CHECK, PlanPhase.REVISE, PlanPhase.FAILED],
        PlanPhase.RULE_CHECK: [PlanPhase.OUTPUT, PlanPhase.REVISE, PlanPhase.FAILED],
        PlanPhase.REVISE:   [PlanPhase.PLANNING, PlanPhase.FAILED],
        PlanPhase.OUTPUT:   [PlanPhase.DONE, PlanPhase.FAILED],
        PlanPhase.DONE:     [],
        PlanPhase.FAILED:   [],
    }
    
    def __init__(self):
        self.current = PlanPhase.INIT
    
    def transition(self, target: PlanPhase) -> bool:
        if target in self.TRANSITIONS[self.current]:
            old = self.current
            self.current = target
            return True
        return False
```

```python
"""
orchestrator.py — Agent 主循环
"""

def initialize_trip() -> str:
    """生成 trip_id，初始化存储目录，返回 trip_id"""

def run_planning_loop(llm_client, constraints: Constraints) -> PlanState:
    """
    主规划循环。
    
    逻辑：
      state = PlanState(trip_id=generate_id(), constraints=constraints)
      sm = StateMachine()
      
      while sm.current != PlanPhase.DONE and sm.current != PlanPhase.FAILED:
          
          if sm.current == PlanPhase.INIT:
              sm.transition(PlanPhase.INTAKE)
          
          elif sm.current == PlanPhase.INTAKE:
              save_state(state)
              sm.transition(PlanPhase.PLANNING)
          
          elif sm.current == PlanPhase.PLANNING:
              # 调用 LLM 生成行程
              result = call_llm(llm_client, SYSTEM_PROMPT, constraints)
              if result.success:
                  state.days = parse_llm_output(result.data)
                  state.evidence = extract_evidence(result.data)
                  save_state(state)
                  sm.transition(PlanPhase.RULE_CHECK)
              else:
                  state.error = str(result.error)
                  sm.transition(PlanPhase.FAILED)
          
          elif sm.current == PlanPhase.RULE_CHECK:
              # 执行规则引擎
              validation = run_rule_engine(state)
              state.validation = validation
              save_state(state)
              
              if validation.overall_pass:
                  sm.transition(PlanPhase.OUTPUT)
              else:
                  sm.transition(PlanPhase.REVISE)
          
          elif sm.current == PlanPhase.REVISE:
              if state.revision_count >= state.max_revisions:
                  sm.transition(PlanPhase.OUTPUT)   # 超限，输出当前结果
              else:
                  state.revision_count += 1
                  # 调用 LLM 修订
                  errors = format_validation_errors(state.validation)
                  result = call_llm_revise(llm_client, state, errors)
                  if result.success:
                      state.days = parse_llm_output(result.data)
                      save_state(state)
                      sm.transition(PlanPhase.PLANNING)  # 回到 PLANNING 重新生成
                  else:
                      sm.transition(PlanPhase.FAILED)
          
          elif sm.current == PlanPhase.OUTPUT:
              save_trip_md(state)
              sm.transition(PlanPhase.DONE)
      
      return state
    """

def call_llm(client, system_prompt: str, constraints: Constraints) -> LLMResult:
    """
    调用 LLM，传入工具定义，处理 tool calling。
    
    逻辑：
      1. 构造 messages:
         - system: system_prompt
         - user: f"请为 {constraints.destination} 规划 {constraints.end_date} 天行程，\
                  预算 {constraints.budget} 元，{constraints.pace} 节奏。"
      2. 调用 client.messages.create()，传入 tools=TOOLS_DEFINITION
      3. 处理 tool_use 响应:
         - search_poi → 返回 LLM 内置知识文本
         - get_weather_forecast → 返回 LLM 内置知识文本
      4. 持续 tool calling 循环直到模型返回 text 内容
      5. 解析 text 内容为 JSON
      6. 返回 LLMResult(success=True, data=json)
    """

def call_llm_revise(client, state: PlanState, errors: str) -> LLMResult:
    """
    调用 LLM 修订行程。
    
    逻辑：
      1. 构造 messages:
         - system: SYSTEM_PROMPT
         - user: REVISE_PROMPT.format(validation_errors=errors, ...)
         - assistant: 上次生成的 JSON（可选，帮助 LLM 理解上下文）
      2. 其余同 call_llm
    """
```

---

## 6. CLI 入口

```python
"""
main.py — 程序入口
"""

def main():
    """
    主入口逻辑：
    
      1. print 欢迎信息
      2. constraints = run_cli()    ← 交互收集需求
      3. initialize LLM client
      4. state = run_planning_loop(llm_client, constraints)
      5. print 最终结果
         if state.status == COMPLETED:
             print_trip(state)
             print(f"行程已保存到 data/trips/{state.trip_id}/")
         else:
             print(f"规划失败: {state.error}")
             print("已有部分结果保存在: data/trips/{state.trip_id}/")
    """

if __name__ == "__main__":
    main()
```

**CLI 交互示例**：

```
========================================
  旅行规划助手 v1.0 (MVP)
  输入旅行需求，获取结构化行程方案
========================================

目的地是哪里？ 杭州
出发日期？(YYYY-MM-DD) 2026-05-01
旅行几天？ 4
几个人？是否有老人/小孩？ 4人，其中2位老人
总预算是多少？(CNY) 20000
节奏偏好？(慢/中/快) 慢
感兴趣的类型？(文化/美食/自然/购物…) 文化,自然

───── 请确认 ─────
杭州 4 天, 2026-05-01 出发
4 人 (2位老人), 预算 20000 CNY, 慢节奏
────────────────

确认开始规划？(y/n): y

⏳ 正在规划...

── 第 1 轮校验 ──
❌ R01 时间连续性: FAIL — Day 2 西湖游船结束时间冲突
❌ R02 预算: FAIL — 总花费 21,500 超出预算

⏳ 正在修订 (第 1 次)...

── 第 2 轮校验 ──
✅ R01 时间连续性: PASS
✅ R02 预算: PASS
✅ R03 日期边界: PASS
✅ R04 必填完整性: PASS

✅ 所有校验通过！

────────────────────────────────
Day 1 — 抵达与适应
────────────────────────────────
 下午    抵达杭州，入住酒店
 晚上    酒店附近晚餐

────────────────────────────────
Day 2 — 文化探索
────────────────────────────────
 09:30-11:30  灵隐寺 (文化)
 12:00-13:00  午餐
 14:00-17:00  浙江省博物馆 (室内)

...

行程已保存到 data/trips/trip_001/
```

---

## 7. 逐文件实现顺序

| 步骤 | 文件 | 依赖 | 估算工时 |
|------|------|------|---------|
| 1 | `types.py` | 无 | 0.5h |
| 2 | `engine/rules.py` | types.py | 1h |
| 3 | `engine/rule_engine.py` | rules.py | 0.5h |
| 4 | `engine/__init__.py` | rule_engine.py | 5min |
| 5 | `tests/test_rules.py` | rules.py, rule_engine.py | 1h |
| 6 | `state.py` | types.py | 0.5h |
| 7 | `tests/test_state.py` | state.py | 0.5h |
| 8 | `storage/file_store.py` | types.py, state.py | 1h |
| 9 | `prompts.py` | 无 | 0.5h |
| 10 | `tools.py` | 无 | 0.5h |
| 11 | `orchestrator.py` | 以上所有 | 2h |
| 12 | `cli.py` | types.py, state.py | 1h |
| 13 | `main.py` | 以上所有 | 0.5h |
| 14 | `tests/test_end_to_end.py` | 全部 | 1.5h |

**说明**：
- 步骤 1-4 完全不需要 LLM，可纯 TDD 开发
- 步骤 5 的单元测试覆盖 4 条规则的各种边界（正常 / 异常 / 边界值）
- 步骤 8 的文件读写建议先写内存版本用于测试，再实现文件版本
- 步骤 11 需要 LLM API key，可用 mock 客户端编写和测试主循环逻辑
- 总估算工时约 **10.5 小时**（单人）

---

## 8. 验收用例

### Case 1：标准输入 → 有效行程

**输入**：
```
目的地: 杭州
出发日期: 2026-05-01
天数: 3
人数: 2 位成人，无老人小孩
预算: 10000 CNY
节奏: 中
兴趣: 文化, 美食
```

**预期输出**：
- 生成 3 天行程，每天至少 1 个 ACTIVITY
- 总花费 ≤ 10000
- 日期范围 1-3
- 时间无重叠
- trip.md 格式正确，可读性良好

### Case 2：预算超限 → 触发 REVISE

**输入**：
```
目的地: 三亚
天数: 5
预算: 5000 CNY  ← 极低预算
人数: 2 位成人
```

**预期输出**：
- 第一轮生成大概率超预算（R02 FAIL）
- 触发 REVISE，重新规划
- 第二轮结果 ≤ 5000 或 revision_count 用尽后输出带警告的行程

### Case 3：时间重叠 → 规则引擎拦截

**输入**：
生成一个故意制造时间重叠的行程（Days 中相邻 segment 时间重叠）

**预期输出**：
- R01 返回 FAIL
- detail 指明具体哪两段冲突
- affected_segments 包含冲突的 segment_id

### Case 4：空数据 → R04 FAIL

**输入**：
某天的 segments 列表为空

**预期输出**：
- R04 返回 FAIL
- detail 指明哪一天缺少活动

### Case 5：修订超限 → 输出最终结果

**输入**：
生成一个连续 3 轮都无法通过校验的行程

**预期输出**：
- revision_count 达到 3
- 状态流转：REVISE → PLANNING → RULE_CHECK → (未通过) → REVISE → ... → 第 4 次进入 REVISE 时 → OUTPUT
- 输出最终的行程（即使有校验失败项）
- 在 CLI 输出中标明"部分校验未通过"

### Case 6：LLM 调用失败 → FAILED

**输入**：
LLM client 返回错误（模拟 API 不可用）

**预期输出**：
- 状态流转到 FAILED
- state.error 记录错误信息
- CLI 输出错误提示
- 已保存的部分结果可恢复

---

## 9. 数据流全景

```
用户输入                  系统内部                    持久化
─────────           ────────────────           ──────────────
                      ┌──────────┐
 CLI 交互收集约束 ──→ │Constraints│ ──→ state.json
                      └────┬─────┘
                           ↓
                    ┌──────────────┐
                    │ Orchestrator │ ←→ LLM + Tools
                    │ (主循环)     │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ 规则引擎      │ ← 4 条确定性规则
                    │ R01-R04      │
                    └──────┬───────┘
                      PASS │  FAIL
                           ↓      ↓
                    ┌──────────┐  REVISE 循环
                    │ OUTPUT   │  (最多 3 次)
                    └────┬─────┘
                         ↓
                    trip.md ← 用户可读可编辑
                    evidence/ ← 证据独立存储
                    state.json ← 结构化数据
```

---

## 10. 与架构总纲的对应关系

| 架构总纲概念 | Phase 1 实现 |
|-------------|-------------|
| 1 Agent (Orchestrator) | `orchestrator.py` — 含主循环、LLM 调用、工具处理 |
| 规则引擎 (R01-R04) | `engine/rules.py` + `engine/rule_engine.py` |
| 状态机 (5 状态) | `state.py` — StateMachine, PlanPhase |
| 文件系统存储 | `storage/file_store.py` |
| CLI → Markdown | `cli.py` + `main.py` |
| 证据链 | `types.py` Evidence 类 + 存储到 evidence/ |
| 结构化消息预留 | `types.py` 全部 dataclass + tools.py 结构化工具定义 |
| trip.md 主数据 | `storage/file_store.py` save_trip_md() |
