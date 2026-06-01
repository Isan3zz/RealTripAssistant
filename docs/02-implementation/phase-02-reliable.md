# Phase 2 实现规格书 — 可靠阶段

## 1. 本阶段目标与边界

**目标**：从"能生成"到"生成得对" — 4 Agent 协同，确定性校验 + 语义校验双层保障，支持用户锁定和方案对比

**范围（In Scope）**：
- 4 Agent 架构（Supervisor / Researcher / Planner / Verifier）
- Verifier 双层校验（确定性规则 8 条 + 语义 LLM 3 条）
- Agent 通信协议（结构化输入/输出）
- 失败分级降级策略（L1-L4）
- User Pinning（用户锁定项不可修改）
- Plan Diff（每次重规划输出变化点）
- Assumption Ledger（隐式/显式假设管理）
- SQLite 缓存层（cache.db + cost_log.db）
- 规则引擎从 4 条扩展到 8 条

**不在范围（Out of Scope）**：
- Web UI（Phase 3）
- PostgreSQL / Redis（Phase 3）
- 长期偏好学习（Phase 3）
- Reflection Agent（Phase 3）

---

## 2. 文件目录树

```
travel_planning_agent/
├── main.py                       # 入口（与 Phase 1 兼容，新增 Supervisor 启动）
├── cli.py                        # CLI 交互增强（支持 pin、diff、假设确认）
├── types.py                      # 数据类型扩展（Phase 1 → Phase 2）
├── state.py                      # 状态机 5 → 11 状态扩展
│
├── agent/                        # Agent 层（新增）
│   ├── __init__.py
│   ├── base.py                   # Agent 基类：声明所需上下文层级
│   ├── supervisor.py             # Supervisor Agent：状态机调度 + 路由 + 降级
│   ├── researcher.py             # Researcher Agent：多源信息收集
│   ├── planner.py                # Planner Agent：行程编排 + 重规划
│   └── verifier.py               # Verifier 封装层：调用规则引擎 + 语义 LLM
│
├── engine/                       # 规则引擎（扩展）
│   ├── __init__.py
│   ├── rule_engine.py            # 规则引擎编排（扩展至 8 条）
│   └── rules.py                  # 8 条确定性规则
│
├── semantic/                     # 语义校验层（新增）
│   ├── __init__.py
│   └── semantic_checker.py       # 3 条语义合理性判断（LLM 调用）
│
├── storage/                      # 存储层（扩展）
│   ├── __init__.py
│   ├── file_store.py             # 文件存储（适配多版本：plan_v1.md, plan_v2.md）
│   ├── sqlite_store.py           # SQLite 缓存 + 成本日志（新增）
│   └── diff.py                   # Plan Diff 生成器（新增）
│
├── models/                       # 数据模型（扩展）
│   ├── __init__.py
│   ├── pin.py                    # Pin 模型
│   ├── assumption.py             # Assumption 模型
│   └── plan_diff.py              # Diff 模型
│
├── prompts.py                    # 提示词模板（扩展至 4 Agent）
├── tools.py                      # 工具定义（Phase 1 不变）
│
└── tests/
    ├── test_rules.py             # 规则测试（扩展至 8 条）
    ├── test_supervisor.py        # Supervisor 路由测试
    ├── test_diff.py              # Plan Diff 测试
    ├── test_pin.py               # Pin 规则测试
    └── test_agent_protocol.py    # Agent 通信协议测试
```

---

## 3. 数据类型扩展

```python
"""
types.py — 在 Phase 1 基础上新增/修改的类型
注意：Phase 1 的旧类型保持兼容，只做字段追加
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ── 新增枚举 ──────────────────────────────────────────

class PlanPhase(Enum):
    # Phase 1 状态（保留）
    INIT = "init"
    INTAKE = "intake"
    PLANNING = "planning"
    RULE_CHECK = "rule_check"
    REVISE = "revise"
    OUTPUT = "output"
    DONE = "done"
    FAILED = "failed"
    # Phase 2 新增状态
    CLARIFYING = "clarifying"
    RESEARCHING = "researching"
    SEMANTIC_CHECK = "semantic_check"
    RISK_CHECKING = "risk_checking"
    AWAITING_USER = "awaiting_user"
    FINALIZING = "finalizing"

class EvidenceSource(Enum):
    API = "api"
    MODEL_KNOWLEDGE = "model_knowledge"
    USER_PROVIDED = "user_provided"

class CheckType(Enum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    RISK = "risk"


# ── Agent 通信协议 ────────────────────────────────────

@dataclass
class AgentRequest:
    """所有 Agent 的标准输入格式"""
    request_id: str
    agent: str                      # "researcher" / "planner" / "verifier"
    context: dict                   # 上下文（按声明的层级拼接）
    params: dict                    # 业务参数
    context_summary: str = ""       # 简短的上下文摘要，用于 LLM 节省 token
    timeout_ms: int = 30000

@dataclass
class AgentResponse:
    """所有 Agent 的标准输出格式"""
    request_id: str
    status: str                     # "success" / "failed" / "degraded"
    data: dict
    error: Optional[str] = None
    tokens_used: int = 0
    source_note: str = ""           # "api_result" / "model_knowledge" / "user_input"


# ── 上下文声明 ────────────────────────────────────────

@dataclass
class ContextRequirement:
    """Agent 声明所需上下文层级"""
    levels: list[int]               # [L0, L2, L4] 表示需要系统规则+静态约束+短期对话


# ── Pin ────────────────────────────────────────────────

@dataclass
class Pin:
    pin_id: str
    target_type: str                # "segment" / "constraint"
    target_id: str                  # segment_id 或 "budget" / "start_date"
    scope: str                      # "entire_trip" / "specific_day"
    day_number: Optional[int] = None  # scope 为 specific_day 时使用
    mutable: bool = False
    reason: str = "user_selected"
    created_at: str = ""


# ── Assumption ─────────────────────────────────────────

class AssumptionLevel(Enum):
    IMPLICIT = "implicit"           # 系统默认，不主动打扰
    EXPLICIT = "explicit"           # 必须用户确认或拒绝

class AssumptionStatus(Enum):
    PENDING = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REPLACED = "replaced"

@dataclass
class Assumption:
    assumption_id: str
    level: AssumptionLevel
    content: str
    status: AssumptionStatus = AssumptionStatus.PENDING
    impact: str = "high"            # "high" / "medium" / "low"
    affected_rules: list[str] = field(default_factory=list)


# ── PlanDiff ───────────────────────────────────────────

@dataclass
class ChangeItem:
    segment_id: str
    change_type: str                # "modified" / "added" / "removed" / "unchanged"
    field_changes: dict             # {"title": {"old": "A", "new": "B"}}
    reason: str = ""                # 变化原因
    impact: dict = field(default_factory=dict)  # {"budget": -120, "walking_km": -1.2}

@dataclass
class PlanDiff:
    diff_id: str
    old_plan_version: int
    new_plan_version: int
    changes: list[ChangeItem]
    pin_integrity: dict             # {"pin_001": {"preserved": true}}


# ── 校验结果扩展 ──────────────────────────────────────

@dataclass
class SemanticCheckResult:
    check_id: str
    result: str                     # "PASS" / "FAIL" / "WARN"
    detail: str
    affected_days: list[int] = field(default_factory=list)

@dataclass
class RiskCheck:
    risk_id: str
    risk_type: str                  # "weather" / "crowd" / "timing"
    severity: str                   # "high" / "medium" / "low"
    probability: str                # "high" / "medium" / "low"
    detail: str
    mitigation: str = ""

@dataclass
class VerificationReport:
    verification_id: str
    overall_pass: bool
    rule_checks: list[RuleResult]          # 复用 Phase 1 RuleResult
    semantic_checks: list[SemanticCheckResult]
    risk_checks: list[RiskCheck]
    correction_requests: list[dict] = field(default_factory=list)


# ── PlanState 扩展 ────────────────────────────────────

# 在 Phase 1 PlanState 基础上新增字段：
@dataclass
class PlanStateV2:
    """Phase 2 PlanState"""
    trip_id: str
    status: str = "draft"
    constraints: Optional[Constraints] = None
    days: list[ItineraryDay] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    validation: Optional[VerificationReport] = None  # ← 从 ValidationResult 升级
    revision_count: int = 0
    max_revisions: int = 3
    phase: PlanPhase = PlanPhase.INIT
    error: Optional[str] = None
    
    # Phase 2 新增
    pins: list[Pin] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    plan_version: int = 1
    diff_history: list[PlanDiff] = field(default_factory=list)
    assmption_ledger: dict[str, AssumptionStatus] = field(default_factory=dict)
```

---

## 4. Agent 通信协议

### 4.1 Agent 基类

```python
"""
agent/base.py — Agent 基类
"""

class BaseAgent:
    """
    所有 Agent 的基类。
    
    Agent 声明其需要的上下文层级，Supervisor 按需拼接后传入。
    """
    agent_name: str = ""
    context_required: ContextRequirement = ContextRequirement(levels=[0, 2])
    
    def __init__(self, llm_client, context_builder):
        self.llm_client = llm_client
        self.context_builder = context_builder  # 负责按层级拼接上下文
    
    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        处理 Agent 请求。
        
        子类覆盖此方法，实现具体逻辑。
        """
        raise NotImplementedError
```

### 4.2 Supervisor 路由逻辑

```python
"""
agent/supervisor.py — Supervisor Agent
"""

class SupervisorAgent(BaseAgent):
    """
    Supervisor 是唯一的调度中心。
    
    职责：
      1. 状态机调度 — 确定性代码实现状态跳转
      2. Agent 路由 — 将请求分发到正确的下游 Agent
      3. 异常降级 — 实现 L1-L4 分级策略
      4. 上下文拼接 — 按下游声明的 context_required 拼接
    
    设计原则：
      - 路由用确定性逻辑（if/elif/状态表），LLM 仅做意图识别
      - 不持有业务状态，状态全部在 PlanState 中
      - 每个 Agent 调用设置 timeout
    """
    
    def __init__(self, llm_client, context_builder, agents: dict):
        super().__init__(llm_client, context_builder)
        self.agents = agents  # {"researcher": ResearcherAgent, ...}
    
    def route(self, state: PlanStateV2, event: str) -> str:
        """
        确定性路由逻辑。
        
        逻辑：
          if state.phase == RULE_CHECK and event == "VALIDATION_FAILED":
              return "planner"           # 规则失败 → 重规划
          if state.phase == PLANNING and event == "PLAN_GENERATED":
              return "verifier"          # 规划完成 → 校验
          if event == "USER_REQUESTED_REVISION":
              return "planner"           # 用户修改 → 重规划
          # 以上都不匹配 → 调用 LLM 意图识别
          return llm_classify_intent(state, event)
        """
    
    def dispatch(self, agent_name: str, request: AgentRequest) -> AgentResponse:
        """
        分发请求到指定 Agent，含降级策略。
        
        逻辑：
          try:
              response = agents[agent_name].handle(request)
              return response
          except TimeoutError:
              return self.degrade(agent_name, request, level=1)
          except EmptyResult:
              return self.degrade(agent_name, request, level=2)
          except Exception:
              return self.degrade(agent_name, request, level=3)
        """
    
    def degrade(self, agent_name: str, request: AgentRequest, level: int) -> AgentResponse:
        """
        分级降级策略。
        
        L1 重试:
          等待 2s 后重试 1 次
          → 成功则返回，失败则抛给上层
        
        L2 降级 (Researcher 空结果):
          source_note = "model_knowledge"
          使用 LLM 内置知识生成结果
          → 标记 confidence="medium"
        
        L3 请求用户:
          暂停流程，切换到 AWAITING_USER 状态
          保存待决策项到 state
          → 等待用户输入
        
        L4 失败:
          标记当前阶段 FAILED
          保留已完成的工作
          → 返回部分结果 + 错误说明
        """
```

### 4.3 Researcher

```python
"""
agent/researcher.py — Researcher Agent
"""

class ResearcherAgent(BaseAgent):
    """
    多源信息收集。
    
    Phase 2 抽象出独立的信息收集 Agent，支持：
      - POI 搜索（外部 API 或 LLM 知识）
      - 天气预报
      - 酒店区域推荐
      - 地图 ETA 估算
    
    所有结果以 Evidence 格式输出，带来源标记。
    """
    
    context_required = ContextRequirement(levels=[0, 2])  # 系统规则 + 静态约束
    
    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        处理研究请求。
        
        逻辑：
          params = request.params
          category = params.get("category")  # "poi" / "weather" / "hotel" / "eta"
          
          if category == "poi":
              results = self.search_poi(params)
          elif category == "weather":
              results = self.get_weather(params)
          elif category == "hotel":
              results = self.recommend_hotel_area(params)
          
          # 所有结果转 Evidence 格式
          evidence_list = [self.to_evidence(r) for r in results]
          
          return AgentResponse(
              request_id=request.request_id,
              status="success",
              data={"evidence": evidence_list},
              tokens_used=...
          )
        """
    
    def search_poi(self, params: dict) -> list[dict]:
        """
        POI 搜索。
        
        策略：
          1. 尝试调用外部 API（Google Places / 高德）
          2. 失败时回退到 LLM 内置知识（L2 降级）
          3. 结果标注来源
        """
    
    def to_evidence(self, raw: dict) -> dict:
        """原始结果 → Evidence 格式"""
```

### 4.4 Planner

```python
"""
agent/planner.py — Planner Agent
"""

class PlannerAgent(BaseAgent):
    """
    行程生成 + 重规划。
    
    职责：
      - 将约束 + Researcher 结果编排为完整行程
      - 支持多方案候选生成
      - 响应 Verifier 的修正请求
      - 遵守 User Pinning（不得修改 locked pin）
    """
    
    context_required = ContextRequirement(levels=[0, 2, 3, 5])  # 规则+约束+状态+证据
    
    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        逻辑：
          mode = request.params.get("mode", "generate")  # "generate" / "revise"
          
          if mode == "generate":
              plan = self.generate_plan(request.params)
          elif mode == "revise":
              plan = self.revise_plan(request.params)
          
          # 验证 pin 完整性
          pin_violations = self.check_pins(plan, request.params.get("pins", []))
          
          return AgentResponse(
              data={
                  "days": plan,
                  "pin_violations": pin_violations,
                  "evidence_ids": [...]
              }
          )
        """
    
    def generate_plan(self, params: dict) -> list[dict]:
        """
        调用 LLM 生成行程。
        
        系统提示词包含：
          - 约束条件
          - Researcher 提供的证据
          - 当前 Pins（标记不可修改项）
          - Assumptions（已确认的）
        
        输出格式与 Phase 1 相同的 JSON 结构。
        """
    
    def revise_plan(self, params: dict) -> list[dict]:
        """
        根据 Verifier 的修正请求重规划。
        
        额外提示词：
          - 上一版本的行程（让 LLM 看到上下文）
          - Verifier 的 correction_requests
          - 已修订次数/最大修订次数
        """
    
    def check_pins(self, plan: list[dict], pins: list[Pin]) -> list[dict]:
        """
        检查 pin 是否被违反。
        
        对每个 locked pin，验证对应 segment 是否被修改。
        """
```

### 4.5 Verifier

```python
"""
agent/verifier.py — Verifier 封装层
"""

class VerifierAgent(BaseAgent):
    """
    Verifier：确定性规则引擎 + 语义 LLM 判断。
    
    注意：
      - 规则引擎（代码实现）是主体，不消耗 token
      - 语义检查仅在规则全部通过后触发
      - Risk Check 也合并在此 Agent
    
    数据流：
      输入 PlanState → 规则引擎（8 条）→ 全部 PASS → 语义检查（3 条）→ Risk Check
                                     ↓ FAIL                     ↓ FAIL
                               correction_requests          semantic_feedback
    """
    
    context_required = ContextRequirement(levels=[0, 2, 3, 5])
    
    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        逻辑：
          state = request.params["state"]
          
          # Step 1: 确定性规则（代码）
          rule_results = run_rule_engine_v2(state)
          has_deterministic_fail = any(r.result == "FAIL" for r in rule_results)
          
          # Step 2: 语义检查（仅确定性规则全部通过）
          semantic_results = []
          if not has_deterministic_fail:
              semantic_results = run_semantic_checks(self.llm_client, state)
          
          # Step 3: 风险检查（始终执行）
          risk_results = run_risk_checks(state)
          
          # Step 4: 生成修正请求
          corrections = self.build_corrections(rule_results, semantic_results)
          
          report = VerificationReport(
              verification_id=generate_id(),
              overall_pass=not has_deterministic_fail,
              rule_checks=rule_results,
              semantic_checks=semantic_results,
              risk_checks=risk_results,
              correction_requests=corrections
          )
          
          return AgentResponse(
              status="success",
              data={"verification_report": asdict(report)}
          )
        """
    
    def build_corrections(self, rule_results, semantic_results) -> list[dict]:
        """
        将 FAIL 规则转化为可执行的修正请求。
        
        示例：
          R03 FAIL "开放时间超限" → 
            correction = {
              "target_segments": ["seg_001"],
              "required_change": "delay_next_activity_or_replace",
              "suggestion": "将灵隐寺调整到 07:00-09:00 或替换为开放时间更长的景点"
            }
        """
```

---

## 5. 规则引擎扩展（8 条确定性规则）

```python
"""
engine/rules.py — 在 Phase 1 的 4 条基础上新增 4 条
"""

# Phase 1 保留的 4 条：
# R01: 时间连续性     — start_time[n+1] >= end_time[n]
# R02: 预算           — 总花费 <= 上限
# R03: 日期边界       — day_number in [1, end_date]
# R04: 必填完整性     — 每天至少 1 个 ACTIVITY

# Phase 2 新增的 4 条：

def check_spatial_continuity(state: PlanStateV2) -> RuleResult:
    """
    R05: 空间连续性 — 活动间留有充足交通时间
    
    逻辑：
      遍历每天的相邻 segment：
        如果 seg[i].location 和 seg[i+1].location 在不同地点：
          eta = estimate_eta(seg[i].location, seg[i+1].location)
          buffer = seg[i+1].start_time - seg[i].end_time
          如果 buffer < eta * 1.3 → FAIL
    
    Phase 2 中 ETA 用距离估算（直线距离 × 系数），
    不走外部 API（Phase 3 才接入地图 API）。
    """

def check_opening_hours(state: PlanStateV2) -> RuleResult:
    """
    R06: 开放时间 — 活动时间在景点开放时间内
    
    逻辑：
      对有 evidence 标记开放时间的 segment：
        segment.start_time >= evidence.opening_time
        segment.end_time <= evidence.closing_time
      如果没有证据 → PASS（LLM 知识可能不精确，不因未知信息报错）
    """

def check_density(state: PlanStateV2) -> RuleResult:
    """
    R07: 行程密度 — 每日主活动不超过阈值
    
    逻辑：
      统计每天 type == ACTIVITY 的 segment 数量：
        慢节奏 ≤ 2 个
        中节奏 ≤ 4 个
        快节奏 ≤ 6 个
    """

def check_pin_integrity(state: PlanStateV2) -> RuleResult:
    """
    R08: 用户锁定项 — pinned 项目未被修改
    
    逻辑：
      遍历 state.pins：
        找到 pin.target_id 对应的 segment
        如果 segment 内容相比锁定时的记录有变化 → FAIL
    
    锁定记录存储在 state 的 pin_snapshots 中。
    """
```

---

## 6. 语义检查

```python
"""
semantic/semantic_checker.py — 3 条语义合理性判断
"""

def check_rhythm(llm_client, state: PlanStateV2) -> SemanticCheckResult:
    """
    S01: 节奏合理性 — 整体行程节奏是否匹配用户偏好
    
    调用 LLM 判断：
      prompt = f"以下是一天的行程安排。请判断节奏是'慢/中/快'，是否匹配用户偏好'{state.constraints.pace}'：..."
    """

def check_diversity(llm_client, state: PlanStateV2) -> SemanticCheckResult:
    """
    S02: 多样性 — 多日行程的活动类型是否过于单一
    
    调用 LLM 判断：
      prompt = f"以下是一个{state.constraints.end_date}天的行程。活动类型是否过于单一？..."
    """

def check_flow(llm_client, state: PlanStateV2) -> SemanticCheckResult:
    """
    S03: 逻辑连贯 — 同一日内的活动动线是否合理
    
    调用 LLM 判断：
      prompt = f"以下是一天的活动路线。是否走了回头路？动线是否合理？..."
    """
```

---

## 7. SQLite 存储设计

```python
"""
storage/sqlite_store.py
"""

CREATE TABLE tool_cache (
    cache_key TEXT PRIMARY KEY,        # hash(destination + category + date)
    result TEXT NOT NULL,              # JSON 序列化结果
    created_at TEXT NOT NULL,          # ISO 时间戳
    ttl_seconds INTEGER DEFAULT 3600, # 默认 1 小时
    -- 过期查询：SELECT * FROM tool_cache WHERE datetime(created_at, '+' || ttl_seconds || ' seconds') > datetime('now')
);

CREATE TABLE cost_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,           # "supervisor" / "researcher" / ...
    model_name TEXT NOT NULL,           # "claude-sonnet-4" / ...
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    estimated_cost REAL NOT NULL,       # USD
    created_at TEXT NOT NULL
);

CREATE INDEX idx_cost_log_trip ON cost_log(trip_id);
CREATE INDEX idx_cost_log_created ON cost_log(created_at);
```

---

## 8. Plan Diff

```python
"""
storage/diff.py — Plan Diff 生成器
"""

def generate_diff(old_state: PlanStateV2, new_state: PlanStateV2, reasons: list[str]) -> PlanDiff:
    """
    比较两个版本的行程，输出结构化变化。
    
    逻辑：
      changes = []
      
      for old_day, new_day in zip(old_state.days, new_state.days):
          for old_seg, new_seg in zip(old_day.segments, new_day.segments):
              if old_seg != new_seg:
                  diff_fields = {}
                  for field in old_seg.__dataclass_fields__:
                      if getattr(old_seg, field) != getattr(new_seg, field):
                          diff_fields[field] = {
                              "old": getattr(old_seg, field),
                              "new": getattr(new_seg, field)
                          }
                  
                  changes.append(ChangeItem(
                      segment_id=new_seg.segment_id,
                      change_type="modified",
                      field_changes=diff_fields,
                      reason=reasons.pop(0) if reasons else ""
                  ))
      
      # 检查 pin integrity
      pin_integrity = {}
      for pin in new_state.pins:
          if not pin.mutable:
              pin_integrity[pin.pin_id] = {"preserved": True}
      
      return PlanDiff(
          diff_id=generate_id(),
          old_plan_version=old_state.plan_version,
          new_plan_version=new_state.plan_version,
          changes=changes,
          pin_integrity=pin_integrity
      )
    """

def format_diff_for_user(diff: PlanDiff) -> str:
    """
    输出人类可读的 Diff 文本。
    
    示例输出：
      本次调整：
      1. Day 2 上午"西湖游船"→"浙江省博物馆"
         原因：天气预报中雨
         影响：预算减少 120 元
      2. Day 3 酒店未变（用户已锁定）
    """
```

---

## 9. 状态机扩展

```python
"""
state.py — Phase 2 状态机（11 状态）
"""

class StateMachineV2:
    """
    Phase 2 状态机：
    
    INIT → INTAKE → CLARIFYING → RESEARCHING → PLANNING
    → RULE_CHECK → SEMANTIC_CHECK → RISK_CHECKING → AWAITING_USER
    → FINALIZING → DONE
    
    异常状态：FAILED（任何阶段可跳转）
    中断处理：AWAITING_USER 可接收任意用户指令
    
    Phase 2 新增状态说明：
      CLARIFYING   — 约束不明确时向用户提问
      RESEARCHING  — Researcher Agent 收集信息
      SEMANTIC_CHECK — 语义合理性判断
      RISK_CHECKING   — 风险检查
      AWAITING_USER   — 等待用户输入（中断流程）
      FINALIZING      — 生成最终输出 + Diff
    """
    
    TRANSITIONS = {
        PlanPhase.INIT:     [PlanPhase.INTAKE, PlanPhase.FAILED],
        PlanPhase.INTAKE:   [PlanPhase.CLARIFYING, PlanPhase.RESEARCHING, PlanPhase.FAILED],
        PlanPhase.CLARIFYING: [PlanPhase.RESEARCHING, PlanPhase.AWAITING_USER, PlanPhase.FAILED],
        PlanPhase.RESEARCHING: [PlanPhase.PLANNING, PlanPhase.FAILED],
        PlanPhase.PLANNING: [PlanPhase.RULE_CHECK, PlanPhase.FAILED],
        PlanPhase.RULE_CHECK: [PlanPhase.SEMANTIC_CHECK, PlanPhase.REVISE, PlanPhase.FAILED],
        PlanPhase.SEMANTIC_CHECK: [PlanPhase.RISK_CHECKING, PlanPhase.REVISE, PlanPhase.FAILED],
        PlanPhase.RISK_CHECKING: [PlanPhase.AWAITING_USER, PlanPhase.FINALIZING, PlanPhase.FAILED],
        PlanPhase.REVISE: [PlanPhase.RESEARCHING, PlanPhase.PLANNING, PlanPhase.FAILED],
        PlanPhase.AWAITING_USER: [PlanPhase.CLARIFYING, PlanPhase.RESEARCHING, PlanPhase.PLANNING, PlanPhase.FAILED],
        PlanPhase.FINALIZING: [PlanPhase.DONE, PlanPhase.FAILED],
        PlanPhase.DONE: [],
        PlanPhase.FAILED: [],
    }
```

---

## 10. 主循环（Supervisor 驱动）

```python
"""
agent/supervisor.py — 主循环
"""

def run_supervisor_loop(llm_client, constraints: Constraints) -> PlanStateV2:
    """
    Supervisor 主循环。
    
    逻辑：
      state = PlanStateV2(trip_id=generate_id(), constraints=constraints)
      sm = StateMachineV2()
      
      while sm.current not in [PlanPhase.DONE, PlanPhase.FAILED]:
          
          if sm.current == PlanPhase.INIT:
              sm.transition(PlanPhase.INTAKE)
          
          elif sm.current == PlanPhase.INTAKE:
              # 检查约束是否完整，是否需要澄清
              missing = check_missing_constraints(constraints)
              if missing:
                  sm.transition(PlanPhase.CLARIFYING)
              else:
                  sm.transition(PlanPhase.RESEARCHING)
          
          elif sm.current == PlanPhase.CLARIFYING:
              # 向用户提问缺失的信息
              question = build_clarifying_question(missing)
              save_state(state)  # 保存进度
              sm.transition(PlanPhase.AWAITING_USER)
          
          elif sm.current == PlanPhase.AWAITING_USER:
              # 等待用户输入（外部触发）
              # 用户输入后继续流转
              ...
          
          elif sm.current == PlanPhase.RESEARCHING:
              # 调用 Researcher
              request = AgentRequest(
                  agent="researcher",
                  params=build_research_params(constraints)
              )
              response = self.dispatch("researcher", request)
              if response.status == "success":
                  state.evidence.update(response.data["evidence"])
                  save_state(state)
                  sm.transition(PlanPhase.PLANNING)
              elif response.status == "degraded":
                  state.evidence.update(response.data["evidence"])
                  state.assumptions.append(...)  # 标记为低置信度
                  sm.transition(PlanPhase.PLANNING)
              else:
                  sm.transition(PlanPhase.FAILED)
          
          elif sm.current == PlanPhase.PLANNING:
              # 调用 Planner
              request = AgentRequest(
                  agent="planner",
                  params={
                      "mode": "revise" if state.revision_count > 0 else "generate",
                      "constraints": asdict(constraints),
                      "evidence": state.evidence,
                      "pins": state.pins,
                      "assumptions": [a for a in state.assumptions if a.status == AssumptionStatus.CONFIRMED]
                  }
              )
              response = self.dispatch("planner", request)
              if response.status == "success":
                  old_days = state.days
                  state.days = response.data["days"]
                  state.plan_version += 1
                  
                  # 生成 Diff
                  diff = generate_diff(
                      PlanStateV2(days=old_days, plan_version=state.plan_version-1),
                      state
                  )
                  state.diff_history.append(diff)
                  
                  save_state(state)
                  sm.transition(PlanPhase.RULE_CHECK)
              else:
                  sm.transition(PlanPhase.FAILED)
          
          elif sm.current == PlanPhase.RULE_CHECK:
              # 调用 Verifier（规则引擎部分）
              request = AgentRequest(
                  agent="verifier",
                  params={"state": state, "check_type": "deterministic"}
              )
              response = self.dispatch("verifier", request)
              report = VerificationReport(**response.data["verification_report"])
              state.validation = report
              
              # 检查是否有确定性规则失败
              deterministic_fails = [r for r in report.rule_checks if r.result == "FAIL"]
              
              if not deterministic_fails:
                  sm.transition(PlanPhase.SEMANTIC_CHECK)
              else:
                  if state.revision_count >= state.max_revisions:
                      sm.transition(PlanPhase.RISK_CHECKING)  # 超限，继续
                  else:
                      sm.transition(PlanPhase.REVISE)
          
          elif sm.current == PlanPhase.SEMANTIC_CHECK:
              # 调用 Verifier（语义 LLM 部分）
              request = AgentRequest(
                  agent="verifier",
                  params={"state": state, "check_type": "semantic"}
              )
              response = self.dispatch("verifier", request)
              state.validation.semantic_checks = response.data["semantic_checks"]
              
              semantic_fails = [s for s in response.data["semantic_checks"] if s.result == "FAIL"]
              if not semantic_fails:
                  sm.transition(PlanPhase.RISK_CHECKING)
              else:
                  sm.transition(PlanPhase.REVISE)
          
          elif sm.current == PlanPhase.RISK_CHECKING:
              # 调用 Verifier（风险检查部分）
              ...
              sm.transition(PlanPhase.FINALIZING)
          
          elif sm.current == PlanPhase.REVISE:
              state.revision_count += 1
              sm.transition(PlanPhase.PLANNING)
          
          elif sm.current == PlanPhase.FINALIZING:
              # 输出最终结果
              save_trip_md_v2(state)  # 支持多版本
              save_state(state)
              sm.transition(PlanPhase.DONE)
      
      return state
```

---

## 11. 逐文件实现顺序

| 步骤 | 文件 | 依赖 | 估算工时 |
|------|------|------|---------|
| 1 | `types.py` 扩展 | 无 | 0.5h |
| 2 | `engine/rules.py` 扩展（R05-R08） | types.py | 1.5h |
| 3 | `engine/rule_engine.py` 更新 | rules.py | 0.5h |
| 4 | `models/pin.py` | types.py | 0.5h |
| 5 | `models/assumption.py` | types.py | 0.5h |
| 6 | `models/plan_diff.py` | types.py | 0.5h |
| 7 | `storage/diff.py` | plan_diff.py | 1h |
| 8 | `storage/sqlite_store.py` | 无 | 1h |
| 9 | `agent/base.py` | types.py | 1h |
| 10 | `agent/researcher.py` | base.py, tools.py | 1.5h |
| 11 | `agent/planner.py` | base.py, types.py | 1.5h |
| 12 | `semantic/semantic_checker.py` | types.py | 1h |
| 13 | `agent/verifier.py` | base.py, rule_engine.py, semantic_checker.py | 2h |
| 14 | `state.py` 状态机扩展 | types.py | 1h |
| 15 | `agent/supervisor.py` | base.py, 所有 Agent | 3h |
| 16 | `cli.py` 增强 | 以上 | 1.5h |
| 17 | `main.py` 更新 | 以上 | 0.5h |

总估算工时约 **18.5 小时**

---

## 12. 验收用例

### Case 1：标准 4 Agent 流程

**输入**：正常旅行需求

**预期**：
- INTAKE → RESEARCHING → PLANNING → RULE_CHECK → SEMANTIC_CHECK → RISK_CHECKING → FINALIZING → DONE
- Researcher 输出含来源标记的证据
- Planner 生成的行程遵守 constraints
- Verifier 所有规则通过
- 最终 trip.md 含证据来源标注

### Case 2：User Pin 保护

**输入**：用户锁定酒店 → 重规划时尝试修改酒店

**预期**：
- R08 检测到 pin 违规 → FAIL
- correction_requests 说明"酒店已被用户锁定，不可修改"
- CLI 提示用户"酒店不变（已锁定）"

### Case 3：L2 降级（Researcher 空结果）

**输入**：Researcher 调用外部 API 超时

**预期**：
- L1 重试 1 次
- L2 降级：使用 LLM 内置知识生成结果
- 输出标记 source="model_knowledge", confidence="medium"
- 最终行程中该 segment 带说明"开放时间来自模型知识，建议出行前确认"

### Case 4：Plan Diff 输出

**输入**：用户要求修改后重规划

**预期**：
- Diff 输出包含：修改的 segment、变化原因、预算影响
- 已锁定的 pin 标记为 unchanged

### Case 5：语义校验拦截不合理行程

**输入**：5天行程全部安排博物馆参观

**预期**：
- R01-R08 全部 PASS（时间、预算均合规）
- S02 多样性检查 → FAIL
- 触发 REVISE 重规划
