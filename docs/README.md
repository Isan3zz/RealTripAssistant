# RealTrip Assistant 文档中心

> 非交易型智能旅行规划助手

---

## 文档结构

```
docs/
├── README.md                                    ← 本文档：目录索引
├── 01-architecture/                             ← 架构设计
│   └── architecture-overview.md                 ← 核心架构总纲（状态机、演进路线、ADR）
├── 02-implementation/                           ← 实现规格
│   ├── phase-01-mvp.md                          ← Phase 1：能运行（CLI + 规则引擎）
│   ├── phase-02-reliable.md                     ← Phase 2：生成得对（4 Agent + 完整校验）
│   ├── phase-03-product.md                      ← Phase 3：好用（Web UI + 方案对比）
│   └── phase-04-enterprise.md                   ← Phase 4：可扩展（可观测 + 知识图谱）
└── 03-product-docs/                             ← 产品文档
    ├── introduction.md                           ← 产品介绍（面向用户/客户）
    └── features.md                               ← 功能文档（全功能总览）
```

---

## 阅读指南

| 角色 | 建议阅读顺序 |
|------|-------------|
| **架构师 / 技术评审** | `01-architecture/` |
| **开发实现** | `02-implementation/` → 从 Phase 1 开始 |
| **产品 / 运营** | `03-product-docs/` |
| **首次了解项目** | `03-product-docs/introduction.md` → `01-architecture/` |

---

## 快速导航

- [架构总纲](01-architecture/architecture-overview.md) — 设计原则、演进路线、完整数据模型、设计决策记录
- [Phase 1 实现规格](02-implementation/phase-01-mvp.md) — MVP 最小闭环，含完整伪代码和验收用例
- [Phase 2 实现规格](02-implementation/phase-02-reliable.md) — 4 Agent 协同、规则引擎扩展、降级策略
- [Phase 3 实现规格](02-implementation/phase-03-product.md) — Web API、DB Schema、前端组件、偏好学习
- [Phase 4 实现规格](02-implementation/phase-04-enterprise.md) — Trace、Model Router、知识图谱、A/B Diff
- [产品介绍](03-product-docs/introduction.md) — 定位、核心能力、适用人群
- [功能文档](03-product-docs/features.md) — 分阶段功能详解、完整功能总览表

---

## 文件对应关系

```
01-architecture/architecture-overview.md
    ↑ 顶层设计总纲
    ├──→ 02-implementation/phase-01-mvp.md       Phase 1 详细规格
    ├──→ 02-implementation/phase-02-reliable.md   Phase 2 详细规格
    ├──→ 02-implementation/phase-03-product.md    Phase 3 详细规格
    └──→ 02-implementation/phase-04-enterprise.md Phase 4 详细规格

03-product-docs/
    ├── introduction.md                           产品介绍（对外）
    └── features.md                               功能说明（对内）
```
