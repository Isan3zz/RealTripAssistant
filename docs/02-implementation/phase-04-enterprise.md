# Phase 4 实现规格书 — 企业级

## 1. 本阶段目标与边界

**目标**：全链路可观测、多模型路由、知识图谱增强、A/B 评测体系

**范围（In Scope）**：
- **Phase 4a（优先交付，4-8 周）**：Trace Recorder、Replay Engine、OpenTelemetry、Prometheus + Grafana、Golden Set CI 自动化
- **Phase 4b（后续交付，2-4 月）**：Model Router、知识图谱、A/B Diff、Kubernetes 部署、6 Agent（Candidate Generator 独立）

**不在范围**：
- 移动端原生应用（架构上预留 API 兼容性即可）
- 跨境支付/预订集成（保持非交易型定位）
- 多语言 UI 全面铺开（API 层已预留 language 字段）

---

## 2. 文件目录树

```
travel_planning_agent/
├── backend/
│   ├── main.py
│   ├── api/                              # Phase 3 API 保留 + 新增
│   ├── agent/
│   │   ├── supervisor.py                 # 升级：集成 Model Router
│   │   ├── candidate_generator.py        # Phase 4b 新增：独立候选生成
│   │   ├── researcher.py
│   │   ├── planner.py
│   │   ├── verifier.py
│   │   └── reflection.py
│   │
│   ├── inference/                        # Phase 4b 新增：Model Router
│   │   ├── __init__.py
│   │   ├── model_router.py               # 按任务复杂度路由
│   │   ├── cost_tracker.py               # 全模型成本追踪
│   │   └── fallback_chain.py             # 降级链配置
│   │
│   ├── knowledge/                        # Phase 4b 新增：知识图谱
│   │   ├── __init__.py
│   │   ├── knowledge_graph.py            # 图谱构建与查询
│   │   ├── graph_schema.py               # 节点/边类型定义
│   │   └── vector_store.py               # 向量检索封装
│   │
│   ├── telemetry/                        # Phase 4a 新增：可观测
│   │   ├── __init__.py
│   │   ├── trace_recorder.py             # 全链路事件记录
│   │   ├── replay_engine.py              # 会话回放
│   │   ├── otel_setup.py                 # OpenTelemetry 配置
│   │   └── metrics.py                    # Prometheus 指标定义
│   │
│   ├── evaluation/                       # Phase 4a 新增：评测
│   │   ├── __init__.py
│   │   ├── golden_set.py                 # Golden Set 加载/运行
│   │   ├── ab_diff.py                    # A/B Diff 引擎
│   │   └── metrics_calc.py               # 指标计算
│   │
│   ├── db/
│   │   ├── models.py                     # 扩展：traces, evaluations 表
│   │   └── migrations/
│   │
│   └── cache/                            # Phase 3 保留
│
├── frontend/                             # Phase 3 保留 + 新增管理面板
│   ├── pages/
│   │   └── admin/                        # 管理面板
│   │       ├── traces.tsx                # Trace 查看
│   │       ├── metrics.tsx               # 监控大屏
│   │       └── evaluations.tsx           # 评测结果
│   └── components/admin/
│
├── scripts/
│   ├── run_golden_set.sh                 # CI 集成脚本
│   └── replay_session.sh                 # 回放工具
│
├── docker-compose.yml                    # 扩展：+ Prometheus + Grafana + Vector DB
├── k8s/                                  # Phase 4b：K8s 部署配置
│   ├── deployment.yaml
│   └── hpa.yaml
│
└── grafana/
    └── dashboards/                       # 预置 Dashboard JSON
```

---

## 3. Trace Recorder（Phase 4a）

```python
"""
backend/telemetry/trace_recorder.py — 全链路事件记录
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class EventType(Enum):
    USER_INPUT = "user_input"
    AGENT_INVOKE = "agent_invoke"
    AGENT_RESPONSE = "agent_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    RULE_CHECK = "rule_check"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    ERROR = "error"
    STATE_TRANSITION = "state_transition"

@dataclass
class TraceEvent:
    event_id: str
    trace_id: str               # 追踪根 ID
    parent_id: Optional[str]    # 父事件 ID（支持嵌套）
    event_type: EventType
    timestamp: str              # ISO 格式
    agent_name: Optional[str]
    duration_ms: Optional[int]
    payload: dict               # 事件具体数据
    tags: list[str] = field(default_factory=list)

class TraceRecorder:
    """
    全链路事件记录器。
    
    记录所有 Agent 调用、工具调用、LLM 调用、规则校验、
    状态跳转等事件，支持嵌套追踪。
    
    存储后端：
      - PostgreSQL（结构化事件数据，短时间查询）
      - 对象存储（大对象，长时间存储）
    """
    
    def __init__(self, db_session, object_storage=None):
        self.db = db_session
        self.object_storage = object_storage
        self.active_trace_id: Optional[str] = None
    
    def start_trace(self, session_id: str, user_id: str) -> str:
        """创建新的 Trace，返回 trace_id"""
    
    def record(self, event: TraceEvent):
        """记录事件到数据库"""
    
    def start_span(self, event_type: EventType, agent_name: str = None) -> str:
        """开始一段 span（如一次 Agent 调用），返回 event_id"""
    
    def end_span(self, event_id: str, payload: dict = None):
        """结束一段 span，记录耗时"""
    
    def get_trace(self, trace_id: str) -> list[TraceEvent]:
        """获取完整 Trace 链"""
    
    def get_traces_by_session(self, session_id: str, limit: int = 20) -> list[str]:
        """获取会话的所有 trace_id"""
```

---

## 4. Replay Engine（Phase 4a）

```python
"""
backend/telemetry/replay_engine.py — 会话回放
"""

class ReplayEngine:
    """
    会话回放引擎。
    
    用途：
      - 复现线上故障
      - A/B 对比同一输入在不同 Prompt 版本下的输出
      - 回归测试
    
    回放模式：
      - Fast-forward：快速执行 Trace 中的所有事件
      - Step-by-step：逐步执行，每步暂停检查状态
      - Mock LLM：用录制的 LLM 响应替代真实调用（不消耗 token）
    """
    
    def replay(self, trace_id: str, mode: str = "fast") -> ReplayResult:
        """
        回放指定 Trace。
        
        模式：
          "fast" — 快速回放，验证 replay 结果与原结果一致
          "step" — 逐步回放，每步输出当前状态
          "mock" — 使用录制的 LLM 响应替代真实调用
        """
    
    def replay_with_diff(self, trace_id: str, new_prompt: str) -> ReplayResult:
        """
        使用新 Prompt 回放，对比输出差异。
        
        用于：
          - Prompt 变更时的 A/B 测试
          - 模型升级时的回归验证
        """
```

---

## 5. Model Router（Phase 4b）

```python
"""
backend/inference/model_router.py
"""

class ModelRouter:
    """
    按任务复杂度路由到不同模型。
    
    路由策略：
      - 简单意图识别 → Claude Haiku（低延迟，低成本）
      - POI 信息提取 → Claude Sonnet（中等）
      - 行程规划编排 → Claude Opus（高精度）
      - 语义校验 → Claude Sonnet（中等）
    
    配置示例：
      ROUTES = {
          "intent_classification": {"model": "haiku", "max_tokens": 500},
          "poi_search":            {"model": "sonnet", "max_tokens": 2000},
          "plan_generation":       {"model": "opus", "max_tokens": 4000},
          "semantic_check":        {"model": "sonnet", "max_tokens": 1000},
          "preference_extract":    {"model": "haiku", "max_tokens": 800},
      }
    """
    
    def __init__(self):
        self.routes = self.load_routes()
        self.fallback_chain = FallbackChain()
    
    def get_model(self, task_type: str, context: dict) -> str:
        """
        根据任务类型和上下文选择模型。
        
        影响因素：
          - 任务复杂度（task_type + context 中的 complexity 字段）
          - 当前模型可用性（fallback_chain）
          - 用户配额（cost_tracker）
          - 响应时间要求
        """
    
    def estimate_cost(self, task_type: str, input_tokens: int) -> float:
        """预估本次调用的成本"""
```

---

## 6. 知识图谱（Phase 4b）

```python
"""
backend/knowledge/knowledge_graph.py
"""

# 节点类型
NODE_TYPES = {
    "CITY": {"properties": ["name", "country", "language", "timezone"]},
    "POI": {"properties": ["name", "category", "hours", "price", "rating"]},
    "HOTEL_AREA": {"properties": ["name", "city", "avg_price", "transport_access"]},
    "SEASON": {"properties": ["name", "months", "weather", "crowd_level"]},
}

# 边类型
EDGE_TYPES = {
    "LOCATED_IN": {"from": "POI", "to": "CITY", "properties": []},
    "NEARBY": {"from": "POI", "to": "POI", "properties": ["distance_km", "transit_time_min"]},
    "BEST_SEASON": {"from": "CITY", "to": "SEASON", "properties": ["score"]},
    "REACHABLE_BY": {"from": "CITY", "to": "CITY", "properties": ["transport_type", "duration", "cost"]},
}

class KnowledgeGraph:
    """
    目的地结构化关系图谱。
    
    查询场景：
      - "西湖附近有什么适合带老人去的景点？"
        → NEARBY(西湖) ∩ POI.category="cultural" ∩ POI.elderly_friendly=true
      
      - "5 月去杭州合适吗？"
        → BEST_SEASON(杭州, 5月).score > 0.7
      
      - "从杭州怎么去乌镇？"
        → REACHABLE_BY(杭州, 乌镇)
    """
    
    def query(self, cypher: str) -> list[dict]:
        """执行图谱查询"""
    
    def find_nearby(self, poi_name: str, max_distance_km: float, filters: dict) -> list[dict]:
        """查找附近的 POI"""
    
    def best_season(self, city: str, month: int) -> dict:
        """查询最佳季节"""
```

---

## 7. Prometheus 指标定义

```python
"""
backend/telemetry/metrics.py
"""

from prometheus_client import Counter, Histogram, Gauge

# ── 调用量 ──
agent_calls_total = Counter(
    "agent_calls_total", "Agent 调用次数",
    ["agent_name", "status"]  # status: success / failed / degraded
)

llm_calls_total = Counter(
    "llm_calls_total", "LLM 调用次数",
    ["model_name", "task_type"]
)

tool_calls_total = Counter(
    "tool_calls_total", "工具调用次数",
    ["tool_name", "status"]
)

# ── 延迟 ──
agent_call_duration = Histogram(
    "agent_call_duration_seconds", "Agent 调用耗时",
    ["agent_name"],
    buckets=(1, 2, 5, 10, 30, 60)
)

llm_call_duration = Histogram(
    "llm_call_duration_seconds", "LLM 调用耗时",
    ["model_name"],
    buckets=(0.5, 1, 2, 5, 10, 20)
)

end_to_end_duration = Histogram(
    "planning_duration_seconds", "完整规划流程耗时",
    buckets=(10, 30, 60, 120, 300)
)

# ── 成本 ──
cost_total = Counter(
    "cost_total_usd", "累计 LLM 成本（USD）",
    ["model_name"]
)

cost_per_plan = Histogram(
    "cost_per_plan_usd", "单次规划成本",
    buckets=(0.05, 0.1, 0.2, 0.5, 1.0, 2.0)
)

# ── 校验 ──
rule_check_results = Counter(
    "rule_check_results", "规则校验结果",
    ["rule_id", "result"]  # result: pass / fail
)

verifier_rejection_rate = Gauge(
    "verifier_rejection_rate", "Verifier 驳回率"
)

# ── 用户 ──
active_sessions = Gauge("active_sessions", "当前活跃会话数")
plans_generated = Counter("plans_generated_total", "已生成方案数")
```

---

## 8. Golden Set + CI

```python
"""
scripts/run_golden_set.sh — CI 集成脚本（伪代码）
"""

# 流程：
# 1. 加载 Golden Set（典型场景 JSON）
# 2. 对每个 case：
#    a. 构造输入
#    b. 运行 Agent 流程
#    c. 校验输出（关键指标 vs expected）
#    d. 记录 pass/fail
# 3. 输摘要：
#    PASS: 8/10
#    FAIL: case_003 (时间连续性校验未通过)
#           case_007 (预算超限未检测到)
# 4. 退出码：全部 PASS → 0，有 FAIL → 1

"""
Golden Set 格式示例：
case_001.json:
{
    "name": "杭州4日家庭游",
    "input": {
        "destination": "杭州",
        "start_date": "2026-05-01",
        "end_date": 4,
        "travelers": [{"age_group": "adult"}, {"age_group": "adult"}, {"age_group": "elderly"}, {"age_group": "elderly"}],
        "budget": 20000,
        "pace": "slow",
        "interests": ["文化", "自然"]
    },
    "expected": {
        "constraints_satisfied": {
            "budget_violation": false,
            "date_violation": false,
            "time_overlap": false
        },
        "minimum_activities": 4,
        "elderly_friendly": true
    }
}
"""
```

---

## 9. A/B Diff 引擎

```python
"""
backend/evaluation/ab_diff.py
"""

class ABDiffEngine:
    """
    A/B Diff：比较新旧 Prompt 或模型版本的输出质量。
    
    流程：
      1. 从 Golden Set 取一个 case
      2. 用旧版 Prompt + 旧模型运行 → 结果 A
      3. 用新版 Prompt + 新模型运行 → 结果 B
      4. 比较所有指标维度
      5. 输出 A/B Diff 报告
    
    比较维度：
      - 约束满足率（硬约束通过率）
      - 行程密度（每日活动数分布）
      - 成本差异（token 消耗变化）
      - 语义评分（LLM 对两个方案的评分）
    """
    
    def compare(self, golden_case: dict, config_a: dict, config_b: dict) -> ABDiffReport:
        """
        执行 A/B 比较。
        
        config_a / config_b 包含：
          - prompt_version: str
          - model_name: str
          - model_params: dict
        """
    
    def generate_report(self, diff: ABDiffReport) -> str:
        """输出人类可读的 A/B 对比报告"""
```

---

## 10. 完整 Agent 列表（6 个）

| Agent | 职责 | 模型 | 上下文层级 | 引入阶段 |
|-------|------|------|-----------|---------|
| **Supervisor** | 状态机调度 + 意图识别 + 异常降级 | Haiku | L0, L1 | Phase 2 |
| **Researcher** | 多源检索 + 知识库查询 | Sonnet | L0, L2, L5 | Phase 2 |
| **Candidate Generator** | 过滤 + 候选集生成 | Sonnet | L0, L2, L5 | Phase 4 |
| **Planner** | 行程生成 + 重规划 | Opus | L0, L1, L2, L3, L5 | Phase 2 |
| **Verifier** | 规则引擎（代码）+ 语义（Sonnet）+ 风险 | Sonnet(语义) | L0, L2, L3, L5 | Phase 2 |
| **Reflection** | 异步偏好提取 + 模式沉淀 | Haiku | L1, L3 | Phase 3 |

---

## 11. 基础设施架构

```
┌─────────────────────────────────────────────────────┐
│                     用户层                           │
│  Web UI / CLI / API                                 │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌──────────────────────┴──────────────────────────────┐
│                    API Layer                         │
│  FastAPI + Celery (异步任务)                         │
└──────┬──────────────────────────────────┬───────────┘
       ↓                                  ↓
┌──────────────┐              ┌───────────────────────┐
│  Agent Layer  │              │   Model Router        │
│  6 Agents     │─────────────→│  Haiku / Sonnet / Opus │
│  Supervisor   │              │  Fallback Chain       │
└──────┬────────┘              └───────────────────────┘
       ↓
┌─────────────────────────────────────────────────────┐
│                   Engine Layer                        │
│  规则引擎 (R01-R08)  │  语义检查 (S01-S03)           │
│  知识图谱查询       │  向量检索                      │
└──────┬──────────────────────────────────┬───────────┘
       ↓                                  ↓
┌──────────────┐              ┌───────────────────────┐
│   PostgreSQL  │              │   Redis + Vector DB   │
│  用户/行程/版本│              │  缓存/会话/向量       │
│  评测结果     │              │                       │
└──────┬────────┘              └───────────────────────┘
       ↓
┌─────────────────────────────────────────────────────┐
│                 Observability                        │
│  Trace Recorder │ OpenTelemetry │ Prometheus/Grafana │
│  Replay Engine  │ Golden Set CI │ A/B Diff          │
└─────────────────────────────────────────────────────┘
```

---

## 12. 基础设施组件

| 组件 | 用途 | 引入阶段 |
|------|------|---------|
| **PostgreSQL** | 用户、行程、版本、评测结果 | Phase 3 |
| **Redis** | 会话缓存、工具缓存、限流 | Phase 3 |
| **Vector DB** | 知识库向量检索、相似行程 | Phase 4b |
| **Object Storage** | 导出文件、Trace 大对象 | Phase 4a |
| **LLM Gateway** | 模型路由、成本统计、fallback | Phase 4b |
| **Trace Recorder** | 全链路事件记录 | Phase 4a |
| **Replay Engine** | 会话回放、故障复现、A/B 对比 | Phase 4a |
| **Golden Set** | 典型场景回归测试（CI 集成） | Phase 2 开始建设 |
| **A/B Diff** | 结构化方案对比 + 指标对比 | Phase 4b |
| **OpenTelemetry** | 全链路追踪 | Phase 4a |
| **Prometheus + Grafana** | 监控 Dashboard | Phase 4a |

---

## 13. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| Agent 框架 | 自研状态机 | 避免框架锁定，状态机逻辑简单可控 |
| 后端框架 | FastAPI + Celery | Celery 处理异步 Agent 调用和长任务 |
| 数据库 | PostgreSQL + Redis + Vector DB (pgvector) | pgvector 避免引入额外向量数据库 |
| LLM 网关 | LiteLLM + 自研 Model Router | LiteLLM 提供统一接口，自研路由逻辑 |
| 可观测 | OpenTelemetry + Prometheus + Grafana | 标准生态，社区支持好 |
| 部署 | Docker Compose → Kubernetes | Phase 4a Compose，Phase 4b K8s |

---

## 14. 各阶段技术选型对比

| 组件 | MVP | Phase 2 | Phase 3 | Phase 4 |
|------|-----|---------|---------|---------|
| **Agent 数** | 1（+规则引擎） | 4 | 5（+Reflection） | 6 |
| **LLM** | 单模型 | 单模型 | 单模型 + fallback | Model Router |
| **框架** | 无依赖 | 无依赖 | FastAPI | FastAPI + Celery |
| **存储** | 文件系统 | 文件系统 + SQLite | PostgreSQL + Redis | + Vector DB |
| **前端** | CLI | CLI | Web UI | Web + 管理面板 |
| **校验** | 4 条确定性规则 | 8 条规则 + 3 语义 | 同 Phase 2 | 同 Phase 2 |
| **缓存** | 无 | 内存 LRU | Redis | Redis Cluster |
| **监测** | 文件日志 | 文件 + 成本日志 | + Sentry | OpenTelemetry |
| **评测** | 无 | Golden Set 建设 | + Trace | + Replay + A/B |
| **知识库** | LLM 知识 | Markdown 文件 | + RAG | + 知识图谱 |
| **部署** | 本地 | 本地 | Docker Compose | Docker → K8s |
