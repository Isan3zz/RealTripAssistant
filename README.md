# RealTrip Assistant 🗺️

> 非交易型智能旅行规划助手 — 对话式输入需求，自动生成可校验的完整旅行方案。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/vue-3.x-42b883.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 这是什么

一个 **AI 驱动的旅行规划助手**。你用自然语言描述需求（"杭州4天，带老人，预算2万，慢节奏"），系统通过多轮对话采集约束，调用外部 API 获取真实数据，生成逐天的结构化行程，并通过确定性规则引擎自动校验可行性。**不代你预订机票酒店，只出方案。**

---

## 技术栈（从代码实际引用）

| 层 | 实际使用 |
|---|---|
| **后端框架** | FastAPI + Uvicorn（`main.py:66`） |
| **LLM** | OpenAI 兼容协议，通过 `llm.py:82` 的 `OpenAICompatibleClient` 调用（支持通义千问 / GPT-4o 等） |
| **LLM Tool Calling** | `tool_calling_service.py` 提供通用 ReAct 循环，最大 25 轮（`llm.py:131`） |
| **数据库** | SQLAlchemy + SQLite（`config.py:34` 默认 `sqlite:///data/realtrip.db`），可选 PostgreSQL |
| **RAG** | Elasticsearch 8.x + Sentence Transformers + BM25/kNN 混合检索 + BGE Reranker（`rag/` 目录） |
| **前端** | Vue 3 + Element Plus + Vite + TypeScript（`frontend/package.json`） |
| **外部 API** | 途牛 CLI（门票/酒店/机票/火车票，`tuniu_client.py` 通过 subprocess 调用）、高德地图 API（天气/路线/POI/地理编码，`gaode_client.py`） |

---

## 项目结构

```
travel_planning_agent/
├── agent/                  # 7 个 Agent 角色（见下）
├── api/                    # FastAPI 路由（9 个子路由 + 内联路由）
├── core/                   # 核心编排（规划运行时、ReAct 循环、会话恢复、修订策略等）
├── rag/                    # RAG 管道（ES 索引、embedding、混合检索、rerank、去重）
├── tools/                  # 13 个 LLM 工具定义 + handler + 专用解析器
├── engine/                 # 确定性规则引擎（rule_engine.py + rules.py）
├── db/                     # SQLAlchemy 模型 + session 管理
├── models/                 # 领域模型：Pin、Assumption、PlanDiff
├── storage/                # 文件存储 + SQLite 存储适配器
├── runtime/                # 运行时组合
├── semantic/               # 语义合理性检查器
├── main.py                 # FastAPI 启动入口
├── config.py               # 集中配置（pydantic-settings，从 .env 加载）
├── llm.py                  # LLM 客户端抽象（OpenAI 协议 + Mock）
├── prompts.py              # 所有 LLM Prompt 模板
├── tool_runtime.py         # 工具注册、分发、执行
├── {flight,gaode,train,tuniu}_client.py  # 外部 API 客户端
└── types.py                # 核心类型定义

frontend/
└── src/
    ├── views/              # TripList.vue（主工作台）、TripDetail.vue（详情页）
    ├── api/index.ts        # 后端 API 封装（axios）
    ├── router/index.ts     # 前端路由（/ 和 /trips/:id）
    └── utils/              # 行程解析器 + 视图适配器

tests/                      # 31 个 pytest 测试文件
docs/                       # 架构 + 实现规格 + 产品文档
```

---

## Agent 管道（8 个角色，`agent/` 目录）

| Agent | 文件 | 实际职责 |
|---|---|---|
| **IntakeAgent** | `agent/intake.py:31` | 多轮对话采集旅行约束（目的地、日期、预算、人员、节奏等），输出 `complete` 或 `question` |
| **ResearcherAgent** | `agent/researcher.py:73` | 多源信息搜索：ReAct 模式（LLM+工具）、途牛直调（查价格）、并行 ResearchPlan 执行、模型知识兜底 |
| **PlannerAgent** | `agent/planner.py:33` | 行程编排：`day_draft`（按天生成三段式：早/中/晚）、`module_refine`（用证据精修单段）、`module_revise`（按校验错误修正） |
| **PolishAgent** | `agent/polisher.py:39` | 后处理：添加天气备注、为 segment 标题生成自然语言描述 |
| **VerifierAgent** | `agent/verifier.py:32` | 校验：`deterministic`（规则引擎，9 条硬规则）、`semantic`（LLM 判断节奏/多样性/动线）、`risk`（风险检查） |
| **SupervisorAgent** | `agent/supervisor.py:55` | 调度中枢：运行完整规划循环（prefetch → Day1 Draft → 并行 [Research + Draft] → Refine/Verify → Polish → Finalize），L1 重试/L2 降级 |
| **RevisionAgent** | `agent/revision.py:23` | 对话式局部修订：接收意图分类结果，生成单天 patch（替换活动/调整时间/修改预算等） |
| **ContextAssembler** | `agent/context.py` | 按 L0-L6 上下文层级为每个 Agent 组装快照 |

**实际流水线**（`supervisor.py` + `plan_run_service.py`）：

```
PlanRunService.run()
  → build_global_execution_plan()   # 结构化 Plan-and-Execute
  → execute_execution_plan()        # 并行执行任务，去重
  → SupervisorAgent.run_planning_loop()
      → prefetch（天气）
      → for each day:
          Planner.day_draft      # 生成全天草案
          Researcher 并行搜索     # 查 POI/酒店/交通
          Planner.module_refine  # 用证据精修
          Verifier（确定性规则）   # 校验修正
      → PolishAgent              # 天气 + 自然语言
      → 持久化到 DB
```

---

## LLM 工具清单（13 个，`tools/schemas.py`）

### 基础工具（7 个，途牛 CLI 提供）

| 工具名 | 来源 | 说明 |
|---|---|---|
| `get_current_date` | 本地 | 获取当前日期 |
| `search_poi` | 本地 | 搜索目的地 POI（景点/餐厅/购物/住宿） |
| `query_ticket_price` | 途牛 | 查景点门票类型和价格 |
| `search_hotel` | 途牛 | 搜索目的地酒店 |
| `get_hotel_detail` | 途牛 | 查看指定酒店详情 |
| `search_flight` | 途牛 | 搜索国内航班 |
| `search_train` | 途牛 | 查询火车车次 |

### 高德地图工具（6 个，`gaode_client.py`）

| 工具名 | 说明 |
|---|---|
| `get_weather_forecast` | 目的地天气预报 |
| `get_driving_eta` | 驾车路线和预计时间 |
| `get_walking_route` | 步行路线 |
| `get_transit_route` | 公交/地铁路线 |
| `geo_encode` | 地址转经纬度 |
| `search_around` | 周边 POI 搜索 |

途牛工具通过 `subprocess` 调用 `tuniu` CLI（`tuniu_client.py:58`），高德工具通过 HTTP API 调用（`gaode_client.py`）。

---

## API 路由（全部以 `/api` 为前缀）

### 会话（`api/sessions.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions?user_id=` | 列出用户会话 |
| GET | `/api/sessions/recent?limit=` | 最近会话摘要 |
| GET | `/api/sessions/{id}/resume` | 完整恢复载荷（消息 + 规划 + 上下文） |
| DELETE | `/api/sessions/{id}` | 软删除会话 |

### 行程（`api/trips.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/trips` | 创建行程 |
| GET | `/api/trips` | 列出行程（按 session_id / status 过滤） |
| GET | `/api/trips/{id}` | 行程详情（含活跃规划、版本列表、假设） |
| DELETE | `/api/trips/{id}` | 删除行程 |

### 规划（`api/plans.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/trips/{id}/plan` | 触发生成（调用 `PlanningRuntime.run()`） |
| POST | `/api/trips/{id}/compare/cost-estimate` | 预估对比 token 消耗 |
| POST | `/api/trips/{id}/compare` | 生成 N 个候选方案对比 |
| GET | `/api/trips/{id}/plans` | 列出所有规划版本 |
| GET | `/api/trips/{id}/plans/{plan_id}` | 单版本详情 |
| POST | `/api/trips/{id}/select-plan` | 选择活跃规划 |

### Chat（`api/chat.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 主对话入口（IntakeAgent → 规划触发） |

### 导出（`api/export.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/trips/{id}/export` | 导出（支持 markdown / ics；**PDF 暂未实现**，返回 400） |
| GET | `/api/exports/{id}/download` | 下载导出文件 |

### 个性化（`api/personal.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/trips/{id}/personal` | 个人视图（决策卡片、解释、清单、修订建议） |

### 偏好（`api/preferences.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users/{id}/preferences` | 列出偏好 |
| POST | `/api/users/{id}/preferences` | 设置/更新偏好（可带上下文） |
| DELETE | `/api/users/{id}/preferences/{key}` | 删除偏好 |

### 内联路由（`api/app.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（返回 status / version / llm_configured / db_configured） |
| GET | `/api/pins/{trip_id}` | 列出锁定项 |
| POST | `/api/pins/{trip_id}` | 锁定一个 segment |
| POST | `/api/assumptions/{trip_id}` | 确认/拒绝假设 |

---

## 前端（Vue 3 + Element Plus）

两个页面路由：

| 路由 | 组件 | 说明 |
|---|---|---|
| `/` | `TripList.vue` | 主工作台：会话抽屉 + 偏好面板 + Chat 问答面板 + 行程摘要 + 路线概览画布 + 行程抽屉 |
| `/trips/:id` | `TripDetail.vue` | 详情页：行程摘要卡片 + 方案判断卡片 + 时间线 + 出发前清单 + 快捷修改 + 历史方案列表 + 方案对比弹窗 |

核心交互流程（`TripList.vue` 的 `handleSend()` 函数）：
1. 用户输入 → `POST /api/chat`
2. 返回 `type=question` → 显示追问
3. 返回 `type=plan_result` → 展示行程卡片 + 完整行程抽屉
4. 会话自动保存到 localStorage，支持刷新后恢复

---

## 配置项（`config.py`）

所有配置通过环境变量 / `.env` 文件加载（pydantic-settings）：

```python
# LLM
llm_base_url: str = "https://api.openai.com/v1"
llm_api_key: str = ""
llm_model: str = "gpt-4o"

# Server
host: str = "0.0.0.0"
port: int = 8000

# Storage
data_dir: str = "data"
db_url: str = "sqlite:///data/realtrip.db"

# 外部 API
tuniu_api_key: str = ""
gaode_key: str = ""

# RAG（可选）
es_host: str = "http://localhost:9200"
es_index_name: str = "realtrip_knowledge"
embedding_model: str = "text-embedding-3-small"
rerank_model_name: str = "BAAI/bge-reranker-v2-m3"
# ... 更多 RAG 参数
```

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/Isan3zz/RealTripAssistant.git
cd RealTripAssistant
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

### 2. 配置

```bash
# 创建 .env，至少配置 LLM
cat > .env << 'EOF'
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o
EOF
```

### 3. 启动后端

```bash
travel-plan
# 或 python -m travel_planning_agent.main
```

访问 http://localhost:8000/docs 查看 API 文档。

### 4. 启动前端（可选）

```bash
cd frontend && npm install && npm run dev
```

### 5. 可选：安装途牛 CLI（门票/酒店/机票查询）

```bash
npm install -g tuniu-cli
export TUNIU_API_KEY=your_tuniu_key
```

### 6. 可选：启动 Elasticsearch（RAG 模块）

```bash
docker run -d -p 9200:9200 -e "discovery.type=single-node" elasticsearch:8.15.0
```

---

## 测试

```bash
pytest                          # 全部 31 个测试
pytest --cov=travel_planning_agent
pytest tests/test_chat_api.py -v
```

---

## 设计原则

1. **规则优先于模型** — 时间冲突、预算超限、空间可达性等用确定性代码校验（`engine/rules.py`），不消耗 LLM token
2. **分级降级** — 外部 API 失败时自动 L1 重试 → L2 模型知识兜底 → L3 请求用户 → L4 标记失败保留已完成工作（`agent/supervisor.py`）
3. **证据驱动** — 每个推荐标注来源（途牛/高德/模型知识），URL 可达性检查
4. **用户可控** — 锁定项不被自动修改，修订过程可追溯
5. **规划优先，不做交易** — 只出方案，不代预订/支付/退改签

---

## 许可证

MIT
