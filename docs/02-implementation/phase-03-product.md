# Phase 3 实现规格书 — 产品阶段

## 1. 本阶段目标与边界

**目标**：从 CLI 工具变成可用的 Web 产品，支持多会话、多方案对比、偏好学习、导出中心

**范围（In Scope）**：
- Web UI（FastAPI + 前端框架）
- PostgreSQL 主数据库（替换文件系统 + SQLite）
- Redis 缓存层
- 5 Agent（新增 Reflection Agent 异步偏好提取）
- 多会话管理（用户同时规划多个旅行）
- 方案对比（差异高亮 + 指标并排对比）
- 长期偏好学习（带上下文特征）
- 导出中心（Markdown / PDF / 日历 ICS）
- 目的地知识库（RAG 检索）
- 用户登录和多用户隔离

**不在范围（Out of Scope）**：
- OpenTelemetry 全链路追踪（Phase 4a）
- Model Router（Phase 4b）
- 知识图谱（Phase 4b）
- Kubernetes 部署（Phase 4b）

---

## 2. 文件目录树

```
travel_planning_agent/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理（环境变量）
│   ├── api/                       # API 路由层
│   │   ├── __init__.py
│   │   ├── trips.py               # 行程 CRUD API
│   │   ├── plans.py               # 方案对比 API
│   │   ├── sessions.py            # 会话管理 API
│   │   ├── export.py              # 导出 API
│   │   └── preferences.py         # 偏好 API
│   │
│   ├── agent/                     # Phase 2 Agent 层迁移（不变）
│   ├── engine/                    # Phase 2 规则引擎迁移（不变）
│   ├── semantic/                  # Phase 2 语义检查迁移（不变）
│   │
│   ├── core/                      # 新增核心模块
│   │   ├── user_preferences.py    # 长期偏好模型
│   │   ├── reflection.py          # Reflection Agent
│   │   ├── plan_comparison.py     # 方案对比引擎
│   │   └── export_service.py      # 导出服务
│   │
│   ├── db/                        # 数据库层
│   │   ├── __init__.py
│   │   ├── session.py             # SQLAlchemy session
│   │   ├── models.py              # SQLAlchemy ORM 模型
│   │   └── migrations/            # Alembic 迁移脚本
│   │
│   ├── knowledge/                 # 知识库
│   │   ├── __init__.py
│   │   ├── knowledge_base.py      # 知识库管理器
│   │   └── markdown_sources/      # Markdown 源文件
│   │
│   └── cache/                     # 缓存层
│       ├── __init__.py
│       └── redis_cache.py         # Redis 缓存封装
│
├── frontend/                      # Web UI（Next.js 或 Vue）
│   ├── pages/                     # 页面
│   │   ├── index.tsx              # 首页/登录
│   │   ├── trips/                 # 行程列表/详情
│   │   ├── plan/                  # 行程编辑/对比
│   │   └── preferences/           # 偏好设置
│   ├── components/                # 组件
│   │   ├── timeline/              # 时间线组件
│   │   ├── map/                   # 地图视图
│   │   ├── comparison/            # 方案对比
│   │   └── export/                # 导出面板
│   └── styles/
│
├── data/                          # 保留（文件导出 + 知识库源文件）
│   ├── exports/
│   └── knowledge/
│
└── docker-compose.yml             # 编排（FastAPI + PostgreSQL + Redis + Frontend）
```

---

## 3. 数据库 Schema

```sql
-- PostgreSQL 主数据库（替换文件系统 + SQLite）

CREATE TABLE users (
    user_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          VARCHAR(255) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    display_name   VARCHAR(100),
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE sessions (
    session_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(user_id),
    title          VARCHAR(255),                     -- 用户可自定义会话标题
    status         VARCHAR(20) DEFAULT 'active',     -- active / archived / deleted
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE trips (
    trip_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID REFERENCES sessions(session_id),
    user_id        UUID REFERENCES users(user_id),
    destination    VARCHAR(255) NOT NULL,
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    traveler_count INTEGER DEFAULT 1,
    elderly_count  INTEGER DEFAULT 0,
    child_count    INTEGER DEFAULT 0,
    budget         DECIMAL(12,2),
    pace           VARCHAR(20) DEFAULT 'moderate',   -- slow / moderate / fast
    interests      TEXT[],                            -- PostgreSQL array
    status         VARCHAR(20) DEFAULT 'planning',   -- planning / completed / failed
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE plan_versions (
    plan_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id        UUID REFERENCES trips(trip_id),
    version        INTEGER NOT NULL,
    plan_data      JSONB NOT NULL,                    -- 完整行程 JSON
    verification   JSONB,                             -- VerificationReport
    diff_previous  JSONB,                             -- 与上一版本的 Diff
    is_active      BOOLEAN DEFAULT false,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_preferences (
    pref_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(user_id),
    pref_key       VARCHAR(100) NOT NULL,             -- "pace" / "interests" / "budget_level"
    base_value     JSONB NOT NULL,
    conditional_values JSONB,                         -- 上下文条件值 [{context, value, confidence}]
    confidence     DECIMAL(5,4) DEFAULT 0.5,
    last_updated   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, pref_key)
);

CREATE TABLE user_assumptions (
    assumption_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id        UUID REFERENCES trips(trip_id),
    level          VARCHAR(20) NOT NULL,              -- implicit / explicit
    content        TEXT NOT NULL,
    status         VARCHAR(30) DEFAULT 'pending_confirmation',
    impact         VARCHAR(20) DEFAULT 'high',
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE cost_logs (
    log_id         BIGSERIAL PRIMARY KEY,
    trip_id        UUID REFERENCES trips(trip_id),
    session_id     UUID REFERENCES sessions(session_id),
    agent_name     VARCHAR(50) NOT NULL,
    model_name     VARCHAR(50) NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    estimated_cost DECIMAL(10,6) NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_trips_user ON trips(user_id);
CREATE INDEX idx_trips_session ON trips(session_id);
CREATE INDEX idx_plan_versions_trip ON plan_versions(trip_id);
CREATE INDEX idx_cost_logs_trip ON cost_logs(trip_id);
CREATE INDEX idx_cost_logs_created ON cost_logs(created_at);
CREATE INDEX idx_user_prefs ON user_preferences(user_id, pref_key);
```

---

## 4. API 接口定义

```python
"""
backend/api/trips.py — 行程 API
"""

# POST /api/trips
# 创建新行程
Request: {
    "session_id": "uuid",
    "destination": "杭州",
    "start_date": "2026-05-01",
    "end_date": "2026-05-04",
    "travelers": {"adults": 2, "elderly": 2, "children": 0},
    "budget": 20000,
    "pace": "slow",
    "interests": ["文化", "自然"]
}
Response: {
    "trip_id": "uuid",
    "status": "planning",
    "created_at": "..."
}

# GET /api/trips
# 获取用户所有行程
Query: ?status=active&page=1&limit=20
Response: {
    "trips": [...],
    "total": 10,
    "page": 1
}

# GET /api/trips/{trip_id}
# 获取行程详情（含最新版本的计划）
Response: {
    "trip": {...},
    "active_plan": {...},           # plan_versions where is_active=true
    "verification": {...},
    "assumptions": [...],
    "pins": [...]
}

# POST /api/trips/{trip_id}/plan
# 触发规划
Request: {
    "mode": "generate" / "revise",
    "revision_reason": "..."
}
Response: {
    "plan_id": "uuid",
    "status": "planning",
    "eta_seconds": 30
}

# POST /api/trips/{trip_id}/pin
# 添加锁定
Request: {
    "target_type": "segment",
    "target_id": "seg_001",
    "scope": "entire_trip"
}
Response: {"pin_id": "uuid", "status": "active"}
```

```python
"""
backend/api/plans.py — 方案对比 API
"""

# POST /api/trips/{trip_id}/compare
# 生成多个候选方案进行比较
Request: {
    "count": 3,
    "dimensions": ["budget", "pace", "diversity"]
}
Response: {
    "comparison_id": "uuid",
    "plans": [
        {"plan_id": "uuid", "label": "经济型", "highlights": {...}},
        {"plan_id": "uuid", "label": "舒适型", "highlights": {...}},
        {"plan_id": "uuid", "label": "深度型", "highlights": {...}}
    ],
    "cost_estimate": {
        "tokens": 45000,
        "estimated_usd": 0.35
    }
}

# GET /api/trips/{trip_id}/compare/{comparison_id}
# 获取方案对比结果（轮询）
Response: {
    "status": "ready",            # "generating" / "ready" / "failed"
    "dimensions": [...],
    "plans": [...],
    "diff_matrix": {
        "dimensions": [
            {"name": "总预算", "values": [8500, 12000, 15000]},
            {"name": "每日活动数", "values": [2, 3, 4]},
            {"name": "步行距离", "values": ["5km/天", "8km/天", "10km/天"]}
        ]
    }
}

# POST /api/trips/{trip_id}/select-plan
# 选择最终方案
Request: {"plan_id": "uuid"}
Response: {"status": "selected"}
```

```python
"""
backend/api/export.py — 导出 API
"""

# POST /api/trips/{trip_id}/export
Request: {
    "format": "markdown" / "pdf" / "ics",
    "plan_id": "uuid"         # 可选，默认 active
}
Response: {
    "export_id": "uuid",
    "download_url": "/exports/{export_id}/download",
    "format": "pdf",
    "expires_at": "..."
}

# GET /api/exports/{export_id}/download
# 返回文件流
```

```python
"""
backend/api/preferences.py — 偏好 API
"""

# GET /api/users/{user_id}/preferences
Response: {
    "preferences": [
        {
            "key": "pace",
            "base_value": "moderate",
            "confidence": 0.78,
            "conditions": [
                {"context": {"has_elderly": true}, "value": "slow", "confidence": 0.91}
            ]
        }
    ]
}

# POST /api/users/{user_id}/preferences
# 手动声明偏好
Request: {
    "key": "pace",
    "value": "slow",
    "context": {"has_elderly": true}
}

# DELETE /api/users/{user_id}/preferences/{pref_key}
# 删除特定偏好
```

---

## 5. 前端组件结构

```
frontend/
├── pages/
│   ├── _app.tsx               # 应用壳（登录态、布局）
│   ├── index.tsx              # 首页：最近的行程列表
│   ├── login.tsx              # 登录页
│   ├── trips/
│   │   ├── index.tsx          # 行程列表页
│   │   └── [trip_id].tsx      # 行程详情页（主页面）
│   ├── plan/
│   │   ├── [plan_id].tsx      # 方案详情页
│   │   └── compare.tsx        # 方案对比页
│   └── preferences.tsx        # 偏好管理页
│
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx       # 侧边栏 + 顶栏布局
│   │   └── Sidebar.tsx        # 会话/行程列表
│   │
│   ├── trip/
│   │   ├── TripForm.tsx       # 新建/编辑行程表单
│   │   ├── TripTimeline.tsx   # 每日行程时间线
│   │   ├── DayCard.tsx        # 单日行程卡片
│   │   ├── SegmentCard.tsx    # 单个活动卡片
│   │   └── MapView.tsx        # 地图视图（Leaflet）
│   │
│   ├── comparison/
│   │   ├── ComparisonView.tsx # 并排对比容器
│   │   ├── DiffHighlight.tsx  # 差异高亮组件
│   │   └── DimensionChart.tsx # 维度对比图
│   │
│   ├── export/
│   │   └── ExportPanel.tsx    # 导出面板（格式选择）
│   │
│   └── common/
│       ├── EvidenceBadge.tsx  # 证据来源标签
│       ├── PinIndicator.tsx   # 锁定指示器
│       └── ValidationBadge.tsx # 校验状态标签
│
│── styles/globals.css
```

---

## 6. 方案对比成本控制

```python
"""
backend/core/plan_comparison.py
"""

class PlanComparisonService:
    """
    方案对比引擎。
    
    核心策略：共享 Researcher 结果，仅 Planner 阶段执行 N 次
    
    流程：
      1. 执行一次 Researcher（获取 POI、天气、酒店等证据）
      2. 对每个候选方案执行一次 Planner（共享证据 + 不同约束权重）
         - 方案 A: 经济型（budget 权重 0.7, comfort 权重 0.3）
         - 方案 B: 舒适型（budget 权重 0.5, comfort 权重 0.5）
         - 方案 C: 深度型（budget 权重 0.3, comfort 权重 0.3, depth 权重 0.4）
      3. 每个方案独立执行 Verifier
      4. 聚合对比结果
      5. 输出差异矩阵
    
    成本预估 API：
      POST /api/trips/{trip_id}/compare/cost-estimate
      → {"plans": 3, "estimated_tokens": 45000, "estimated_usd": 0.35}
    """
    
    def estimate_cost(self, plan_count: int) -> dict:
        """
        预估方案对比的 token 消耗。
        
        公式：
          shared_research = 8K tokens
          per_plan = 12K tokens (planning + verification)
          total = shared_research + per_plan * plan_count
        """
```

---

## 7. 长期偏好模型

```python
"""
backend/core/user_preferences.py
"""

from dataclasses import dataclass, field

@dataclass
class PreferenceCondition:
    context: dict           # {"has_elderly": true, "trip_type": "family"}
    value: str
    confidence: float
    occurrence_count: int

@dataclass
class UserPreference:
    key: str                # "pace" / "interests" / "budget_level" / "travel_style"
    base_value: str
    confidence: float
    conditions: list[PreferenceCondition] = field(default_factory=list)
    last_updated: str = ""

class PreferenceExtractor:
    """
    从行程历史中提取长期偏好。
    
    写入规则（必须同时满足）：
      1. 用户明确表达了偏好
      2. 同一上下文下 ≥ 2 次行为一致
      3. Reflection Agent 确认该偏好有效
      4. 用户授权保存
    """
    
    def extract_from_trip(self, trip_data: dict, user_id: str) -> list[UserPreference]:
        """
        从单次行程中提取偏好信号。
        
        提取维度：
          - pace: 从行程密度和用户反馈推断
          - interests: 从实际选择的景点类型推断
          - budget_level: 从预算和实际花费推断
        """
    
    def merge_preference(self, existing: list[UserPreference], new: UserPreference) -> list[UserPreference]:
        """
        将新偏好合并到现有偏好中。
        
        合并策略：
          - 相同 key + 相同 context → 更新 confidence + occurrence_count
          - 相同 key + 不同 context → 新增条件值
          - 新 key → 新增偏好
        """
```

---

## 8. Reflection Agent

```python
"""
backend/core/reflection.py — 异步偏好提取
"""

class ReflectionAgent:
    """
    Reflection Agent 是唯一异步的 Agent，不阻塞主流程。
    
    职责：
      - 行程完成后异步执行
      - 分析已完成的行程，提取用户偏好模式
      - 将偏好写入 user_preferences
      - 将沉淀的"模式"（如"该用户喜欢下午安排轻松活动"）写入知识库
    
    触发时机：
      - 行程状态变为 completed
      - 用户确认了某个假设
      - 用户主动修改了行程中的某项安排
    """
    
    def reflect(self, state: PlanStateV2, user_id: str):
        """
        异步执行偏好提取。
        
        逻辑：
          1. 分析最终行程的节奏、活动类型分布、预算使用
          2. 分析用户修改项（如手动调整了时间 → 偏好信号）
          3. 分析用户确认/拒绝的假设
          4. 提取偏好信号
          5. 合并到 user_preferences
          6. 如果置信度 > 0.8，推送给用户确认
        """
    
    def analyze_modifications(self, diff_history: list[PlanDiff]) -> list[dict]:
        """
        分析用户修改模式。
        
        示例：
          "用户连续 3 次将午餐时间推迟到 13:00" →
          {"key": "lunch_time", "value": "13:00", "confidence": 0.85}
        """
```

---

## 9. Redis 缓存设计

```python
"""
backend/cache/redis_cache.py
"""

# Session Cache（短期对话历史）
# Key: session:{session_id}:context
# Value: JSON — 最近 N 轮对话
# TTL: 24 小时

# Tool Cache（工具结果缓存）
# Key: tool:{destination}:{category}:{date}
# Value: JSON — 工具调用结果
# TTL: 按数据类型：
#   - 天气: 6 小时
#   - POI: 24 小时
#   - ETA: 12 小时
#   - 酒店: 24 小时

# Cost Quota（用户 token 消耗配额追踪）
# Key: quota:{user_id}:{date}
# Value: INTEGER — 当日已消耗 token
# TTL: 到次日 0 点
```

---

## 10. 逐文件实现顺序

| 步骤 | 文件 | 估算工时 |
|------|------|---------|
| **后端基础设施** | | |
| 1 | `docker-compose.yml` | 0.5h |
| 2 | `backend/config.py` | 0.5h |
| 3 | `backend/db/session.py` + `backend/db/models.py` | 2h |
| 4 | `backend/main.py` | 0.5h |
| **API 层** | | |
| 5 | `backend/api/sessions.py` | 1h |
| 6 | `backend/api/trips.py` | 2h |
| 7 | `backend/api/plans.py` | 1.5h |
| 8 | `backend/api/export.py` | 1h |
| 9 | `backend/api/preferences.py` | 1h |
| **核心模块** | | |
| 10 | `backend/core/plan_comparison.py` | 2h |
| 11 | `backend/core/user_preferences.py` | 1.5h |
| 12 | `backend/core/reflection.py` | 1.5h |
| 13 | `backend/core/export_service.py` | 1.5h |
| 14 | `backend/cache/redis_cache.py` | 1h |
| 15 | `backend/knowledge/knowledge_base.py` | 1.5h |
| **前端** | | |
| 16 | 前端项目初始化（Next.js） | 1h |
| 17 | `TripForm.tsx` + `pages/index.tsx` | 2h |
| 18 | `TripTimeline.tsx` + `DayCard.tsx` | 2h |
| 19 | `ComparisonView.tsx` | 2h |
| 20 | `ExportPanel.tsx` | 1h |
| 21 | `MapView.tsx` | 1.5h |
| 22 | 登录/偏好页面 | 1.5h |
| **集成** | | |
| 23 | Agent 层适配 PostgreSQL 存储 | 1h |
| 24 | 端到端集成测试 | 2h |

总估算工时约 **30 小时**

---

## 11. 验收用例

### Case 1：完整 Web 流程
1. 用户注册/登录
2. 创建新行程（填写表单）
3. 触发规划 → 等待完成 → 查看时间线
4. 修改约束 → 查看 Diff
5. 添加 Pin → 验证重规划后 Pin 保留

### Case 2：方案对比
1. 同一个 trip 触发 2 个候选方案
2. 并排对比：预算差异、活动数量差异、节奏差异
3. 用户选择其中一个作为 active plan

### Case 3：偏好学习
1. 用户完成 2 次"带老人出游"行程后
2. 第 3 次创建带老人行程时，系统自动建议 slow pace
3. 用户确认/拒绝该建议

### Case 4：导出
1. 导出 Markdown — 格式完整
2. 导出 PDF — 排版整洁
3. 导出 ICS — 可导入日历

### Case 5：多会话管理
1. 同时规划"杭州"和"三亚"两个旅行
2. 切换会话查看各自的进度
3. 会话隔离：数据不串
