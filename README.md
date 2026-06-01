# RealTrip Assistant 🗺️

> 非交易型智能旅行规划助手 — 你的私人旅行规划师，不做预订，只做方案。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Phase](https://img.shields.io/badge/phase-3%20(product)-orange.svg)]()

---

## 🎯 一句话定位

**RealTrip Assistant** 帮你完成旅行中最消耗精力的部分——信息收集、行程编排、方案比较——然后把最终方案交给你去执行。**不代用户预订、不代用户支付、不代用户退改签**。

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🧠 **智能行程生成** | 一句话需求 → 完整每日行程（活动、时间线、费用估算） |
| 🔍 **多维校验保障** | 8 层确定性规则校验 + 语义合理性判断，确保方案真实可用 |
| 📌 **用户锁定** | 一键锁定满意安排，后续修改不动锁定项 |
| ⚖️ **方案对比** | 多方案并排对比，差异高亮，快速决策 |
| 🎭 **偏好学习** | 上下文感知偏好（"带老人慢节奏" ≠ "自己出门深度游"） |
| 📤 **全格式导出** | Markdown / PDF / 日历 ICS 一键导出 |
| 💬 **对话式修订** | Chat 界面自然语言调整行程 |

---

## 🏗️ 架构

```
用户输入 → Intake → Researcher → Planner → Polisher → Supervisor → Verifier → 输出
                ↑                                                         |
                └──────────── 修订循环 ←─────────────────────────────────┘
```

### Agent 角色

| Agent | 职责 |
|-------|------|
| **Intake** | 需求理解、约束提取、澄清提问 |
| **Researcher** | 外部信息收集：POI、天气、交通、酒店 |
| **Supervisor** | 状态机调度、异常降级、Agent 路由 |
| **Planner** | 行程生成、多方案编排 |
| **Polisher** | 行程润色、格式化输出 |
| **Verifier** | 规则校验（确定性代码）+ 语义判断（LLM） |
| **Revision** | 对话式修订、增量更新 |

### 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3.11+ / FastAPI / Uvicorn |
| **Agent 框架** | 自研状态机（无框架锁定） |
| **LLM** | OpenAI 兼容协议（支持通义千问等） |
| **数据库** | SQLite（开发）/ PostgreSQL（生产） |
| **RAG** | Elasticsearch + Sentence Transformers + BM25 + kNN 混合检索 |
| **前端** | Vue 3 + Vite + TypeScript |
| **外部 API** | 高德地图（POI/路线/天气）、途牛（门票/酒店/机票） |

---

## 🚀 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+（前端）
- （可选）Elasticsearch 8.15+（RAG 模块）

### 1. 克隆项目

```bash
git clone https://github.com/Isan3zz/RealTripAssistant.git
cd RealTripAssistant
```

### 2. 安装后端

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key
```

必填配置：

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | LLM API 密钥（支持 OpenAI / 通义千问等兼容协议） |
| `LLM_BASE_URL` | LLM API 端点 |
| `LLM_MODEL` | 模型名称（如 `qwen-max`、`gpt-4o`） |

可选配置：`GAODE_KEY`（高德地图）、`TUNIU_API_KEY`（途牛服务）。

### 4. 启动服务

```bash
# 启动 API 服务
travel-plan

# 或直接运行
python -m travel_planning_agent.main
```

访问：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 5. 启动前端（可选）

```bash
cd frontend
npm install
npm run dev
```

---

## 📂 项目结构

```
RealTripAssistant/
├── travel_planning_agent/       # 后端核心
│   ├── agent/                   # Agent 角色（intake/researcher/planner/...）
│   ├── api/                     # FastAPI 路由（chat/plans/sessions/export/...）
│   ├── core/                    # 核心服务（react_loop/session_resume/revision/...）
│   ├── rag/                     # RAG 模块（ES/embedding/hybrid_retrieval/rerank）
│   ├── tools/                   # 工具层（POI/路线/天气解析）
│   ├── engine/                  # 规则引擎
│   ├── db/                      # 数据库模型 & 迁移
│   ├── models/                  # 领域模型（assumption/pin/plan_diff）
│   └── storage/                 # 文件 & SQLite 存储
├── frontend/                    # Vue 3 前端
│   └── src/
│       ├── views/               # TripList / TripDetail
│       ├── api/                 # 后端 API 封装
│       └── router/              # 前端路由
├── tests/                       # 测试套件（31 个测试文件）
├── docs/                        # 文档中心
│   ├── 01-architecture/         # 架构设计
│   ├── 02-implementation/       # Phase 1-4 实现规格
│   └── 03-product-docs/         # 产品文档
└── data/                        # 运行时数据（自动生成）
```

---

## 📋 API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/plans` | POST | 创建旅行规划 |
| `/plans/{id}` | GET | 获取规划详情 |
| `/chat/{session_id}` | POST | 对话式交互 |
| `/sessions` | GET/POST | 会话管理 |
| `/export/{plan_id}` | GET | 导出方案 |
| `/personal/preferences` | GET/PUT | 用户偏好管理 |

---

## 🧪 测试

```bash
# 运行全部测试
pytest

# 带覆盖率
pytest --cov=travel_planning_agent

# 运行特定模块
pytest tests/test_chat_api.py -v
```

---

## 📐 设计原则

1. **规划优先，不做交易** — 只提供方案，不执行预订/支付
2. **证据驱动** — 所有推荐有来源，URL 可达性自动检查
3. **约束优先** — 先满足硬约束（日期/预算/人数），再优化软偏好
4. **规则优先于模型** — 能用代码校验的不用 LLM，零 token 消耗
5. **用户可控** — 锁定项不被修改，修订过程透明可追溯
6. **分级降级** — 外部 API 失败时自动降级，不因单点故障阻塞流程

---

## 🗺️ 产品路线

| 阶段 | 状态 | 核心交付 |
|------|------|---------|
| **Phase 1** MVP | ✅ 完成 | CLI + 规则引擎 + 基础行程生成 |
| **Phase 2** 可靠 | ✅ 完成 | 4 Agent 协同 + 完整校验体系 + 用户锁定 |
| **Phase 3** 产品 | 🚧 当前 | Web UI + 多会话 + 偏好学习 + 导出中心 + Chat 修订 |
| **Phase 4** 企业 | 📅 规划 | 可观测 + 知识图谱 + Model Router + K8s |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。大改动前建议先开 Issue 讨论。

---

## 📄 许可证

[MIT](LICENSE)

---

<p align="center">
  Made with ❤️ by RealTrip Team
</p>
