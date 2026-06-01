# 旅行规划助手 Agent 架构设计（分阶段演进版）

版本：`v2.1`
定位：**非交易型旅行规划助手**
目标：帮助用户完成高质量旅行方案的生成、比较、验证、解释、修改和导出。
边界：**不代用户预订、不代用户支付、不代用户退改签**。

---

## 核心设计原则（全阶段适用）

### 1. 规划优先，不做交易
系统只提供规划建议、候选方案、来源链接、风险提示和导出能力。不执行任何预订或支付。

### 2. 证据驱动
所有关键结论必须有来源。动态信息必须标记查询时间和有效性。

### 3. 约束优先
先满足硬约束（日期、预算、人数），再优化软偏好（节奏、风格）。

### 4. 可解释
每个推荐都应说明原因。每次重规划都应展示变化点和触发原因。

### 5. 用户可控
用户可以锁定某些安排，系统不得擅自修改用户锁定项。

### 6. 规则优先于模型判断
能用确定性规则校验的（时间冲突、预算超限、空间不可达），不用 LLM 判断。LLM 仅用于语义理解和生成，不做数值校验。

---

## 总体演进路线

```
Phase 1 (MVP, 2-3周)       Phase 2 (可靠, 3-4周)       Phase 3 (产品, 4-6周)        Phase 4 (企业级, 3-6月)
─────────────────────      ──────────────────────      ──────────────────────        ─────────────────────
能运行                       生成得对                     好用                          可扩展

1 Agent + 规则引擎            4 Agent + SQLite            Web UI + PostgreSQL           6 Agent + 完整设施
CLI → Markdown               + 规则校验器/Plan Diff       + 多会话/偏好                 + Harness/可观测
+ 确定性校验                   + User Pinning              + 方案对比/导出中心            + 分阶段交付(4a/4b)
```

---

## Phase 1：MVP — 能运行的最小闭环

**目标**：用户输入需求 → 输出结构化 Markdown 行程
**Agent 数**：1 个（Orchestrator/Planner 合一）+ 1 个确定性规则引擎
**存储**：文件系统
**前端**：CLI

### 架构

```text
[用户输入] → [Orchestrator] → [Markdown 文件 + JSON state]
                  ↓
           [LLM + 工具调用]
                  ↓
           [规则引擎（确定性校验）]
```

Orchestrator 同时承担：意图识别、信息搜索、行程生成。规则引擎独立于 LLM，用确定性代码校验关键约束。

### 为什么 MVP 就需要规则引擎

LLM 对自己生成内容的校验能力很弱——它往往发现不了自己编造的开放时间、遗漏的交通时间、计算错误的预算总和。这些校验不需要 AI，几十行代码即可实现。MVP 阶段至少覆盖以下硬校验：

```text
1. 时间不重叠     — 同一天内相邻活动时间不得重叠（start_time[n+1] >= end_time[n]）
2. 预算不超限     — 所有 segment 费用之和 <= 预算上限
3. 日期不越界     — 所有行程日期在 trip 起止日期范围内
4. 必填项完整     — 每日至少有一个 activity 类型的 segment
```

规则引擎输出：通过 / 失败 + 失败项列表，触发 REVISE 流程。

### 状态机（MVP 精简版）

```text
INTAKE → PLANNING → RULE_CHECK → OUTPUT → DONE
                ↑         ↓
                └── REVISE ←┘
```

CLARIFYING 合入 INTAKE，RESEARCHING 合入 PLANNING。RULE_CHECK 由确定性规则引擎执行，不消耗 LLM token。

### 存储设计

```text
data/
  trips/{trip_id}/
    trip.md              # 最终行程（Markdown 格式，人类可直接阅读编辑）
    state.json           # 结构化数据：约束、行程片段、证据列表、pins
    evidence/            # 证据独立文件（从 MVP 开始就独立存储）
      ev_001.json        # 单条证据，含 url_reachable 字段
  logs/                  # LLM 调用日志（JSON Lines 格式，追加写入）
```

核心设计思想：**Markdown 是主数据格式，JSON 是辅助索引**。用户可以直接修改 .md 文件，系统下次运行时读取并保持同步。

### 证据链处理

每条证据从 MVP 阶段就包含 URL 可达性标记，避免 LLM 幻觉 URL 而系统无法察觉：

```json
{
  "segment": {
    "title": "灵隐寺",
    "evidence": [
      {
        "source": "景区官网",
        "url": "https://...",
        "retrieved_at": "2026-04-30T10:00:00Z",
        "url_reachable": true,
        "url_checked_at": "2026-04-30T10:00:05Z",
        "claim": "开放时间 07:00-18:00"
      }
    ]
  }
}
```

### trip.md 格式

```markdown
---
destination: 杭州
dates: 2026-05-01 ~ 2026-05-04
travelers: 4人（2位老人）
budget: 20000 CNY
pace: 慢节奏
status: draft
---

## Day 1 — 抵达与适应

### 下午
- 抵达杭州，入住酒店

### 晚上
- 酒店附近晚餐，不安排强活动

## Day 2 — 文化景点

09:30-11:30 灵隐寺（文化，适合老人）
12:30-13:30 午餐
15:00-17:00 浙江省博物馆（室内，雨天备选）
```

### Agent 消息协议预留

虽然 MVP 只有 1 个 Agent，但工具调用的输入输出从第一天就使用结构化接口，为 Phase 2 拆分做准备：

```json
// 每个工具调用的标准输入
{
  "tool": "search_poi",
  "request_id": "req_001",
  "params": { "destination": "杭州", "category": "cultural" },
  "context_summary": "为 Day 2 上午寻找文化景点，出行人含2位老人"
}

// 每个工具调用的标准输出
{
  "request_id": "req_001",
  "status": "success",
  "data": [...],
  "error": null,
  "tokens_used": 450
}
```

---

## Phase 2：可靠阶段 — 从能生成到生成得对

**目标**：系统稳定产出经过校验的行程
**Agent 数**：4 个（Supervisor / Researcher / Planner / Verifier）
**存储**：文件系统 + SQLite（索引和缓存）

**重要设计决策**：Verifier 的主体是**规则引擎模块**（确定性代码），不是 LLM Agent。
仅"行程节奏是否合理"这类语义判断才调用 LLM。

### 架构

```text
[Supervisor] → [Researcher] → [Planner] → [Verifier(规则引擎 + 语义LLM)] → [用户]
     ↑                                                           │
     └────────── 失败回退（分级降级策略） ────────────────────────┘
```

| Agent | 职责 |
|-------|------|
| **Supervisor** | 状态机调度、意图识别、异常处理、Agent 路由 |
| **Researcher** | 外部信息收集：POI、天气、地图 ETA、酒店区域 |
| **Planner** | 候选生成 + 行程编排 + 多方案排序 |
| **Verifier** | 确定性规则校验（代码）+ 语义合理性判断（LLM），输出通过/失败 + 修正建议 |

### Verifier 校验规则（分层）

**确定性规则层（代码实现，不消耗 LLM token）：**

```text
1. 时间连续性    — 相邻活动时间不重叠
2. 空间连续性    — 活动间留有充足交通时间（buffer >= ETA × 1.3）
3. 开放时间      — 活动在景点开放时间内
4. 预算          — 总花费不超预算上限
5. 行程密度      — 每日主活动不超过阈值
6. 交通缓冲      — 活动间隔 >= ETA + buffer
7. 用户锁定项    — pinned 项目未被修改
8. 数据新鲜度    — 证据未过期
```

**语义判断层（LLM 调用，仅在确定性规则全部通过后触发）：**

```text
9. 节奏合理性    — 整体行程节奏是否匹配用户偏好（慢/中/快）
10. 多样性       — 多日行程的活动类型是否过于单一
11. 逻辑连贯     — 同一日内的活动动线是否合理（不走回头路）
```

规则引擎输出统一结构：

```json
{
  "rule_check": {
    "overall_pass": false,
    "rules": [
      { "id": "R01", "type": "deterministic", "name": "时间连续性", "result": "PASS" },
      { "id": "R03", "type": "deterministic", "name": "开放时间", "result": "FAIL",
        "detail": "Day 2 灵隐寺结束时间 18:30 超出景区关闭时间 18:00",
        "affected_segments": ["seg_001"] }
    ],
    "semantic_check": null
  }
}
```

### Agent 通信失败分级策略

每个 Agent 调用失败时，Supervisor 按以下层级回退：

| 层级 | 策略 | 适用场景 | 对用户可见 |
|------|------|---------|-----------|
| **L1 重试** | 延迟重试 1 次（间隔 2s） | 网络超时、API 限流 | 否 |
| **L2 降级** | 使用 LLM 内置知识兜底 | Researcher 返回空结果 | 是（标记来源为"模型知识"） |
| **L3 请求用户** | 暂停流程，向用户提问 | 关键信息缺失且无法推断 | 是（等待用户输入） |
| **L4 失败** | 标记当前阶段为 FAILED，保留已完成工作 | 多次降级后仍不可用 | 是（提供已完成部分的导出） |

```text
Researcher 返回空结果时：
  L1 重试 → L2 用 LLM 知识兜底（标记 source="model_knowledge", confidence="medium"）
  → 行程生成后 Verifier 加强对此类 segment 的校验 → 提示用户"以下项目的开放时间来自模型知识，建议出行前确认"

Planner 生成失败时：
  L1 重试 → L2 降低约束严格度重新生成（如 pace 从 "strict_slow" 降为 "moderate_slow"）
  → L3 请求用户简化需求 → L4 输出已生成的部分行程 + 失败原因
```

### 新增能力

#### User Pinning

用户可锁定：酒店、航班、景点、餐厅、日期、预算、每日出发时间。

```json
{
  "pin_id": "pin_001",
  "target_type": "segment",
  "target_id": "hotel_001",
  "scope": "entire_trip",
  "mutable": false,
  "reason": "user_selected"
}
```

规则：Planner 不得修改 locked pin，Verifier 规则 R07 自动检查 pin 是否被破坏，Diff 必须说明 pin 是否保持不变。

#### Plan Diff

每次重规划后输出结构化变化：

```text
本次调整：
1. Day 2 上午"西湖游船"→"浙江省博物馆"
   原因：天气预报中雨
   影响：预算减少 120 元，步行减少 1.2km
2. Day 3 酒店未变（用户已锁定）
```

#### Assumption Ledger（分级）

区分隐式假设和显式假设，避免一次性弹出过多确认项导致用户放弃：

**隐式假设（implicit）**：系统默认值，不主动打扰用户，但可在"假设清单"页面查看和修改：
- 默认午餐时间 12:00-13:00
- 默认酒店入住时间 14:00
- 默认景点游玩时长（按类型估算）

**显式假设（explicit）**：必须用户确认或拒绝，否则系统可能做出错误决策：
- 老人每日步行上限 6000 步（影响行程密度和交通方式选择）
- 用户偏好"不需要租车"（影响远距离景点可达性）
- 预算是否包含餐饮（影响预算计算口径）

```json
{
  "assumption_id": "asm_001",
  "level": "explicit",
  "content": "默认老人每日步行不超过 6000 步",
  "status": "pending_confirmation",
  "impact": "high",
  "affected_rules": ["R05 行程密度"]
}
```

假设状态：pending_confirmation → confirmed / rejected / expired / replaced。系统默认最多同时展示 3 条显式假设等待确认。

### 存储升级

```text
data/
  trips/{trip_id}/
    plan_v1.md              # 每个版本独立文件
    plan_v2.md
    state.json              # 约束 + pins + assumptions
    evidence/               # 证据独立文件
      ev_weather.json
      ev_poi_hours.json
  golden_set/               # 回归测试用例（5-10 个典型场景）
    case_001.json           # 输入：约束条件
    case_001_expected.json  # 期望：关键字段通过校验
  knowledge/                # 知识库扩充（Markdown 格式）

新增 SQLite：
  cache.db                  # 工具结果缓存（带 TTL）
                             仅做缓存用，主数据仍在文件系统
  cost_log.db               # LLM 调用成本记录（从 Phase 2 开始为 Phase 3 方案对比做预算评估）
```

---

## Phase 3：产品阶段 — 从工具到产品

**目标**：从 CLI 变成可用的 Web 产品
**Agent 数**：5 个（新增 Reflection Agent）
**新增**：Web UI、多会话、偏好学习、导出中心、知识库、方案对比

### 架构

```text
[Web UI] → [API] → [Phase 2 Agent Runtime + Reflection Agent(异步)]
                      ↓
             [PostgreSQL + Redis]
```

### 新增能力

| 能力 | 说明 |
|------|------|
| **Plan Canvas** | 可视化时间线，每日行程卡片 |
| **方案对比** | 并排对比 2-3 个候选方案（差异高亮 + 指标对比） |
| **多会话管理** | 同时规划多个旅行 |
| **用户系统** | 登录、多用户隔离 |
| **长期偏好学习** | 跨行程提取用户偏好，带上下文特征，结构化存储 |
| **地图视图** | 行程点在地图上标注 |
| **导出中心** | Markdown / PDF / 日历 ICS / 外部 OTA 链接 |
| **目的地知识库** | 手工维护的结构化知识（RAG 检索） |
| **Reflection Agent** | 异步偏好提取 + 模式沉淀，不阻塞主流程 |

### 方案对比成本控制

方案对比是 Phase 3 的核心功能，但也是成本最高的功能。每个候选方案都需要完整规划 + 校验，LLM token 消耗成倍增长。应对策略：

```text
1. 差异化生成 — 3 个方案共享 Researcher 阶段的结果，仅 Planner 阶段执行 3 次
2. 成本预估 — 生成前预估 token 消耗，用户确认后再执行
3. 方案数量限制 — 免费用户 2 个方案，付费用户最多 5 个
4. 渐进对比 — 先生成方案 A，用户对 A 不满意再生成 B
```

### 长期偏好模型（带上下文特征）

偏好不是全局平均，而是与出行上下文绑定。用户在一次旅行中选择"慢节奏"可能是因为带了老人，不代表所有旅行都要慢节奏：

```json
{
  "user_id": "user_001",
  "preferences": [
    {
      "key": "pace",
      "base_value": "moderate",
      "confidence": 0.78,
      "conditional_values": [
        {
          "context": { "has_elderly": true },
          "value": "slow",
          "confidence": 0.91,
          "occurrence_count": 4
        },
        {
          "context": { "trip_type": "solo", "destination_type": "city" },
          "value": "fast",
          "confidence": 0.72,
          "occurrence_count": 2
        }
      ],
      "last_updated": "2026-04-30T10:00:00Z"
    }
  ]
}
```

写入规则：用户明确表达 / 同一上下文下 ≥ 2 次行为一致 / Reflection 确认 / 用户授权保存。

### 存储架构升级

```text
PostgreSQL（主数据，替换 JSON 文件）
  users               — 用户账号
  sessions            — 会话管理
  trips               — 行程主表
  plan_versions       — 版本管理
  user_preferences    — 长期偏好（含上下文特征）
  user_assumptions    — 用户确认过的假设历史

Redis（新增）
  session_cache       — 短期对话历史
  tool_cache          — 工具结果缓存（带 TTL）
  cost_quota          — 用户 token 消耗配额追踪

文件系统（保留）
  exports/            — 导出的文件
  knowledge/          — 知识库源文件（Markdown）
  logs/               — 审计日志

Vector DB（可选）
  知识库向量索引
  相似行程检索
```

### 推荐技术栈

| 组件 | 选型 |
|------|------|
| 后端 | FastAPI |
| 前端 | Next.js 或 Vue |
| 数据库 | PostgreSQL + Redis |
| 部署 | Docker Compose |

---

## Phase 4：企业级 — 可扩展、可观测、可迭代

**目标**：多团队协作、全链路可观测、持续迭代
**Agent 数**：6 个（Phase 3 的 5 个 + Candidate Generator 独立拆分）
**分阶段交付**：Phase 4a（可观测性 + Harness）、Phase 4b（知识图谱 + Model Router + 高级评测）

### Phase 4a（优先交付，4-8 周）：可观测 + 基础设施

目标：让系统可调试、可复现、可评估。

| 交付项 | 说明 |
|--------|------|
| **Trace Recorder** | 全链路事件记录（用户输入→Agent调用→工具调用→输出） |
| **Replay Engine** | 会话回放、故障复现 |
| **OpenTelemetry** | 全链路追踪 |
| **Prometheus + Grafana** | 监控 Dashboard |
| **Golden Set 自动化** | CI 集成，每次变更自动跑回归测试 |

### Phase 4b（后续交付，2-4 月）：高级能力

| 交付项 | 说明 |
|--------|------|
| **Model Router** | 按任务复杂度路由到不同模型（简单意图用小模型，规划用大模型，降低成本） |
| **知识图谱** | 目的地结构化关系（景点相邻关系、交通方式可达性、季节适配） |
| **A/B Diff** | Prompt 变更时自动对比新旧方案质量 |
| **Kubernetes 部署** | 多副本、自动扩缩容 |

### 完整 Agent 列表（6 个）

| Agent | 职责 | 引入阶段 |
|-------|------|---------|
| **Supervisor** | 状态机调度 + 意图识别 + 异常降级 | Phase 2 |
| **Researcher** | 多源检索 + 知识库查询 | Phase 2 |
| **Candidate Generator** | 过滤 + 候选集生成（Phase 3 合入 Planner） | Phase 4 |
| **Planner** | 行程生成 + 重规划 + 多方案编排 | Phase 2 |
| **Verifier** | 确定性规则校验（代码引擎）+ 语义判断（LLM）+ 风险检查 | Phase 2 |
| **Reflection Agent** | 异步偏好提取 + 模式沉淀 | Phase 3 |

**Agent 合并决策说明：**

| 被合并项 | 合并到 | 理由 |
|---------|--------|------|
| Risk Checker | Verifier | 风险检查与校验规则高度重叠（天气→空间连续性，人流→行程密度），合并后统一输出 VerificationReport + RiskReport |
| Summarizer | 工具函数 | 上下文压缩是纯工程问题，不应是 Agent；由 Supervisor 调用 `summarize_context()` 工具函数完成 |

### 上下文分层（L0-L6）

```text
L0  系统规则             — 不变的原则和约束
L1  用户长期记忆         — 偏好画像（带上下文特征）
L2  当前任务静态约束     — 日期/预算/人数
L3  动态工作状态         — 当前阶段/待决策项
L4  短期对话历史         — 最近 N 轮对话（N 可配置，默认 10）
L5  证据与工具结果       — API 查询结果
L6  Agent 专用上下文     — 各 Agent 定制
```

每个 Agent 声明所需上下文层级，Supervisor 按需拼接，避免每次调用都传入全部上下文。

### Supervisor 轻量化设计

Supervisor 是唯一的调度中心，其可靠性直接影响全系统。设计原则：

```text
1. 路由用确定性逻辑 — 状态机跳转规则用代码实现，LLM 仅做意图识别和异常判断
2. 上下文最小化 — Supervisor 只传递下游 Agent 声明需要的上下文层级
3. 无状态 — Supervisor 不持有业务状态，状态全部在 state.json / PostgreSQL 中
4. 超时保护 — 每个 Agent 调用设置 timeout，超时自动触发 L2 降级
```

```python
# Supervisor 路由逻辑示例（确定性部分）
def route(state: TripState, event: Event) -> AgentName:
    if state.phase == Phase.RULE_CHECK_FAILED:
        return AgentName.PLANNER       # 规则失败 → 重规划
    if state.phase == Phase.PLANNING_DONE:
        return AgentName.VERIFIER       # 规划完成 → 校验
    if event.type == EventType.USER_REQUESTED_REVISION:
        return AgentName.PLANNER       # 用户修改 → 重规划
    # 仅当无法确定路由时，调用 LLM 做意图识别
    return llm_classify_intent(state, event)
```

### 完整状态机

```text
INIT → INTAKE → CLARIFYING → RESEARCHING → CANDIDATE_GENERATING
→ PLANNING → RULE_CHECK → SEMANTIC_CHECK → RISK_CHECKING → AWAITING_USER
→ REVISING / FINALIZING → EXPORTING → FINISHED

异常状态：FAILED（任何阶段可跳转，保留已完成工作）
中断处理：AWAITING_USER 可接收任意用户指令中断当前流程
```

### 完整事件类型

```text
USER_MESSAGE / CONSTRAINTS_EXTRACTED / CLARIFICATION_REQUIRED
RESEARCH_STARTED / RESEARCH_COMPLETE / CANDIDATES_GENERATED
PLAN_GENERATED / RULE_CHECK_PASSED / RULE_CHECK_FAILED
SEMANTIC_CHECK_PASSED / SEMANTIC_CHECK_FAILED
RISK_REPORT_GENERATED
USER_PIN_ADDED / USER_PIN_REMOVED / USER_REQUESTED_REVISION
PLAN_REVISED / PLAN_FINALIZED
EXPORT_REQUESTED / EXPORT_COMPLETE
TOOL_ERROR / AGENT_ERROR / SYSTEM_ERROR / TIMEOUT
```

### Evaluation Metrics

#### 约束满足指标
- hard_constraint_satisfaction_rate
- budget_violation_rate / pin_violation_rate

#### 行程可行性指标
- time_window_violation_rate / route_eta_violation_rate
- closed_poi_violation_rate / overpacked_day_rate / insufficient_buffer_rate

#### 证据质量指标
- source_coverage_rate / unsupported_claim_rate
- stale_data_rate / evidence_consistency_rate / url_unreachable_rate

#### Agent 运行指标
- tool_call_success_rate / verifier_rejection_rate
- replanning_success_rate / average_latency / average_token_cost

#### 成本指标（全阶段追踪）
- cost_per_plan（单次规划成本）
- cost_per_comparison（方案对比场景成本）
- model_distribution（各模型调用占比）

### 完整基础设施

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

### 推荐技术栈

| 组件 | 选型 |
|------|------|
| Agent 框架 | LangGraph / 自研状态机（推荐自研，避免框架锁定） |
| 后端 | FastAPI + Celery |
| 数据库 | PostgreSQL + Redis + Vector DB |
| LLM 网关 | LiteLLM + 自研 Model Router |
| 前端 | Next.js |
| 可观测 | OpenTelemetry + Prometheus + Grafana |
| 部署 | Docker Compose（Phase 4a）→ Kubernetes（Phase 4b） |

---

## 各阶段技术选型对比

| 组件 | MVP | Phase 2 | Phase 3 | Phase 4 |
|------|-----|---------|---------|---------|
| **Agent 数** | 1（+规则引擎） | 4 | 5（+Reflection） | 6 |
| **LLM** | 单模型 | 单模型 | 单模型 + fallback | Model Router |
| **框架** | 无依赖 | 无依赖 | FastAPI | FastAPI + Celery |
| **存储** | 文件系统 | 文件系统 + SQLite | PostgreSQL + Redis | + Vector DB |
| **前端** | CLI | CLI / 简单界面 | Web UI | Web + 可选 Mobile |
| **校验** | 确定性规则引擎 | 规则引擎 + 语义LLM | 同 Phase 2 | 同 Phase 2 |
| **缓存** | 无 | 内存 LRU | Redis | Redis Cluster |
| **监测** | 文件日志 | 文件日志 + 成本日志 | + Sentry | OpenTelemetry |
| **评测** | 无 | Golden Set | + Trace | + Replay + A/B |
| **知识库** | 硬编码 / LLM 知识 | Markdown 文件 | + RAG | + 知识图谱 |
| **部署** | 本地 | 本地 / 简单部署 | Docker Compose | Docker → K8s |

---

## 各阶段单次规划成本估算

| 阶段 | 模型调用次数 | 预估 Token 消耗 | 预估费用（Claude Sonnet 定价） | 说明 |
|------|------------|---------------|------------------------------|------|
| **Phase 1** | 2-3 次 | ~8K-15K tokens | ~$0.05-0.10 | 意图识别 + 规划生成 + 可能的修订 |
| **Phase 2** | 8-12 次 | ~30K-50K tokens | ~$0.20-0.35 | 4 Agent 各 2-3 次调用 + 语义校验 |
| **Phase 3** | 15-25 次 | ~60K-120K tokens | ~$0.40-0.80 | 含方案对比（2-3 候选方案）、偏好查询 |
| **Phase 4** | 20-30 次 | ~80K-150K tokens | ~$0.50-1.00 | 含 Model Router（小模型处理简单意图可降低 20-30%） |

> 费用按 Claude Sonnet $3/$15 per 1M input/output tokens 估算，实际费用以官方定价为准。Phase 3 方案对比场景成本最高，建议从 Phase 2 开始追踪成本数据，为 Phase 3 做预算评估。

---

## 跨阶段关键风险与应对

| 过渡 | 风险等级 | 关键挑战 | 应对措施 |
|------|---------|---------|---------|
| **Phase 1 → 2** | **中高** | 单 Agent 拆多 Agent 的通信协议、数据迁移（纯文件 → 文件+SQLite） | Phase 1 预留结构化消息接口；迁移脚本单向不可逆 |
| **Phase 2 → 3** | **低** | 主要是加 Web 层和换数据库 | Agent 核心逻辑不变，PostgreSQL 与文件系统可并行运行过渡期 |
| **Phase 3 → 4a** | **中** | 新增可观测基础设施 | 与核心业务解耦，可渐进式添加 |
| **Phase 4a → 4b** | **中** | Model Router 可能引入路由错误 | A/B Diff 先建，确保模型切换不劣化方案质量 |

---

## 缺失的关键讨论（已纳入设计）

### 1. 多语言 / 国际化策略

从 Phase 1 开始，所有数据模型预留 `language` 字段。中文示例是因为目标用户是中文用户，但目的地可能涉及海外：

```json
{
  "segment": {
    "title": "Eiffel Tower / 埃菲尔铁塔",
    "title_local": "La Tour Eiffel",
    "language": "zh-CN",
    "destination_language": "fr"
  }
}
```

POI 名称存储策略：同时保存用户语言名称和目的地本地语言名称，方便地图检索和问路。

### 2. 外部工具 / API 绑定清单

| 工具 | MVP | Phase 2+ | 数据源 | 费用 |
|------|-----|----------|--------|------|
| **POI 搜索** | LLM 内置知识 | Google Places / 高德 POI API | 外部 API | 按调用付费 |
| **天气** | LLM 搜索摘要 | OpenWeatherMap / 和风天气 | 外部 API | 免费额度可用 |
| **地图 ETA** | 无（手动标注距离） | 高德地图 / Google Maps Directions | 外部 API | 按调用付费 |
| **酒店区域** | LLM 内置知识 | Booking.com / 携程 API（仅搜索，不预订） | 外部 API | 按调用付费 |
| **汇率** | 无 | exchangerate-api | 外部 API | 免费 |
| **图片** | 无 | Unsplash API（城市/景点图片） | 外部 API | 免费额度可用 |

> 每个外部 API 调用前需检查可用性和余量，失败时走 L2 降级策略。

### 3. PII 保护声明

| 数据类型 | 是否收集 | 说明 |
|---------|---------|------|
| 姓名 / 手机号 / 身份证号 | **否** | 系统不收集任何证件类信息 |
| 邮箱 | Phase 3（可选） | 仅用于账号注册和导出文件发送 |
| 出行偏好 | 是 | 脱敏存储，用户可随时删除 |
| 对话历史 | 是 | 用于改进规划质量，不计入长期偏好前需用户确认 |
| 位置信息 | 仅目的地城市级别 | 不追踪用户实时位置 |

---

## 附录：完整数据模型

### Trip

```json
{
  "trip_id": "trip_001",
  "user_id": "user_001",
  "title": "杭州 4 日家庭游",
  "destination": "杭州",
  "destination_language": "zh-CN",
  "language": "zh-CN",
  "start_date": "2026-05-01",
  "end_date": "2026-05-04",
  "travelers": [],
  "constraints": [],
  "active_plan_id": "plan_001",
  "status": "planning",
  "created_at": "2026-04-30T10:00:00Z"
}
```

### TripPlan

```json
{
  "plan_id": "plan_001",
  "trip_id": "trip_001",
  "version": 3,
  "status": "proposed",
  "days": [],
  "budget_summary": {},
  "risk_report_id": "risk_001",
  "verification_report_id": "verify_001"
}
```

### ItineraryDay

```json
{
  "day_id": "day_001",
  "date": "2026-05-01",
  "city": "杭州",
  "theme": "抵达与适应",
  "segments": ["seg_001", "seg_002"]
}
```

### Segment

```json
{
  "segment_id": "seg_001",
  "type": "activity",
  "status": "proposed",
  "title": "灵隐寺",
  "title_local": null,
  "start_time": "09:30",
  "end_time": "11:30",
  "location": {
    "name": "灵隐寺",
    "name_local": null,
    "city": "杭州",
    "lat": 30.2401,
    "lng": 120.1023
  },
  "estimated_cost": {
    "amount": 45,
    "currency": "CNY"
  },
  "tags": ["cultural", "senior_friendly"],
  "evidence_ids": ["ev_001"],
  "risk_ids": ["risk_001"],
  "assumption_ids": ["asm_001"],
  "mutable": true
}
```

### Evidence

```json
{
  "evidence_id": "ev_001",
  "source_type": "official_api",
  "source_url": "https://example.com",
  "retrieved_at": "2026-04-30T10:00:00Z",
  "valid_until": "2026-05-01T00:00:00Z",
  "url_reachable": true,
  "url_checked_at": "2026-04-30T10:00:05Z",
  "confidence": "high",
  "claim": "灵隐寺开放时间为 07:00-18:00"
}
```

### VerificationReport（含规则校验和风险检查）

```json
{
  "verification_id": "verify_001",
  "overall_pass": false,
  "rule_checks": [
    {
      "check_id": "check_001",
      "type": "deterministic",
      "rule_id": "R03",
      "result": "FAIL",
      "severity": "high",
      "detail": "灵隐寺到西湖游船预计车程 45 分钟，当前只预留 30 分钟",
      "affected_segments": ["seg_201", "seg_202"]
    }
  ],
  "semantic_checks": [
    {
      "check_id": "check_010",
      "type": "semantic",
      "result": "PASS",
      "detail": "Day 2 活动节奏与用户偏好'慢节奏'一致"
    }
  ],
  "risk_checks": [
    {
      "risk_id": "risk_001",
      "type": "weather",
      "severity": "medium",
      "probability": "high",
      "detail": "当天上午中雨概率较高",
      "mitigation": "准备室内备选方案"
    }
  ],
  "correction_requests": [
    {
      "target_segments": ["seg_201"],
      "required_change": "delay_next_activity_or_replace"
    }
  ]
}
```

### Pin

```json
{
  "pin_id": "pin_001",
  "target_type": "segment",
  "target_id": "seg_001",
  "scope": "entire_trip",
  "mutable": false,
  "reason": "user_selected"
}
```

---

## 附录：架构设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 是否用数据库 | MVP 用文件系统，逐步过渡到 PG | 数据量小，Markdown 可读可编辑，零运维 |
| Agent 数量 | 从 1 逐步增加到 6 | 避免过早拆分增加通信复杂度；按需引入，每个 Agent 有明确独立职责 |
| Risk Checker 合并到 Verifier | 合并 | 风险检查与校验规则高度重叠，合并后统一输出，减少一次 Agent 调用 |
| Summarizer 不作为 Agent | 工具函数 | 上下文压缩是工程问题，LLM 调用即可，无需独立 Agent |
| Reflection Agent | Phase 3 引入 | 与偏好学习需求同步，不必等到 Phase 4 |
| 校验策略 | 确定性规则（代码）优先，LLM 语义判断兜底 | LLM 自检不可靠；规则引擎零 token 消耗、零延迟、100% 准确 |
| Agent 通信 | 统一通过 Supervisor | 避免 Agent 间直接依赖，简化路由和错误处理 |
| 状态机 | 从 7 状态扩展到 14 状态 | MVP 不需要 CLARIFYING、EXPORTING 等 |
| Verifier 主体 | 规则引擎模块，不是 Agent | 8 条规则中 8 条是确定性的，用代码校验更可靠更便宜 |
| Vector DB | Phase 4b | 知识库向量检索，前期不需要 |
| Harness 层 | Phase 4a | 等需要回归测试和线上问题复现时再建 |
| PII 保护 | 全阶段不收集证件号、手机号 | 定位非交易型，无需实名信息 |
| 失败策略 | L1 重试 → L2 降级 → L3 请求用户 → L4 失败 | 分级降级，避免用户无感知的错误静默 |
| 假设的分级 | implicit / explicit | 避免一次性弹出过多确认项，仅高影响假设要求用户确认 |
| Phase 4 拆分 | 4a（可观测）+ 4b（高级能力） | 单一 Phase 4 体量过大，拆分后 4a 可先行交付 |
| 成本追踪 | 从 Phase 2 开始 | 为 Phase 3 方案对比功能提供预算评估数据 |

---

## 附录：各阶段实现规格书索引

本文档为顶层架构总纲。各阶段的代码级实现规格（目录树、接口定义、伪代码、实现顺序、验收用例）见独立文档：

| 阶段 | 文档 | 详细程度 | 状态 |
|------|------|---------|------|
| **Phase 1 (MVP)** — 能运行 | [../02-implementation/phase-01-mvp.md](../02-implementation/phase-01-mvp.md) | 代码级：数据结构、伪代码、CLI 设计 | 已发布 |
| **Phase 2** — 可靠 | [../02-implementation/phase-02-reliable.md](../02-implementation/phase-02-reliable.md) | 代码级：Agent 协议、Verifier 接口、SQLite 设计 | 已发布 |
| **Phase 3** — 产品 | [../02-implementation/phase-03-product.md](../02-implementation/phase-03-product.md) | 接口级：API、DB Schema、前端结构 | 已发布 |
| **Phase 4** — 企业级 | [../02-implementation/phase-04-enterprise.md](../02-implementation/phase-04-enterprise.md) | 架构级：可观测、Model Router、知识图谱 | 已发布 |
