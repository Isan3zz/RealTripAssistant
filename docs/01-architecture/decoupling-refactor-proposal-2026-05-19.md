# RealTrip Assistant 解耦重构方案

版本：`v1`
日期：`2026-05-19`
定位：在不明显改变现有用户行为的前提下，降低 `api / core / agent / llm / tools / storage` 之间的耦合度，提升可维护性、可测试性与后续扩展能力。

---

## 1. 背景与问题判断

当前项目已经具备明确的目录分层意识：

- `api/`：FastAPI 路由与接口层
- `core/`：规划流程、对话流程、运行时能力
- `agent/`：多 Agent 决策与调度
- `tools/`：工具注册与执行门面
- `llm.py`：模型调用与 tool calling 循环
- `storage/`、`db/`：文件存储与数据库持久化

但从依赖关系看，核心问题不是“没有分层”，而是“分层边界被打穿”。

典型表现：

1. `core` 直接实例化具体 Agent，导致 `core -> agent` 强耦合。
2. `agent` 又反过来依赖 `core` 中的运行时和流程函数，形成双向依赖感。
3. `ChatService`、`SupervisorAgent`、`PlanRunService` 都承担了过多职责，成为中心节点。
4. `llm.py` 直接感知工具执行细节，导致模型客户端与工具系统绑定过深。
5. 部分 `api` 路由直接操作数据库实体并拼业务响应，应用服务边界偏薄。

因此，当前项目的判断是：

**整体处于“中高耦合、中心类过重、边界不够硬”的状态。**

这不是失控状态，但如果继续叠加需求，后续会越来越容易出现：

- 改一处影响多处
- 单元测试越来越难写
- 同一类文件持续膨胀
- 替换模型、工具、存储策略时牵一发动全身

---

## 2. 重构目标

本次解耦重构不追求“一步到位重写架构”，而追求以下四个结果：

1. 拉直依赖方向，消除最明显的跨层反向依赖。
2. 缩小中心类职责，让关键流程变成“编排 + 服务协作”而不是“上帝类”。
3. 为 LLM、工具执行、持久化建立稳定边界，便于替换实现。
4. 在每一阶段都保持当前产品行为基本稳定，避免大爆炸式重构。

非目标：

- 不在第一阶段调整产品交互。
- 不在第一阶段重写所有目录结构。
- 不为了“形式上的干净”而大规模搬迁代码。
- 不同时引入新的复杂抽象层和插件机制。

---

## 3. 当前主要耦合点

### 3.1 `core` 与 `agent` 双向感明显

问题核心：

- `PlanRunService` 直接创建 `PlannerAgent`、`ResearcherAgent`、`SupervisorAgent`、`VerifierAgent`
- `SupervisorAgent` 又依赖 `core` 中的流程辅助逻辑

后果：

- `core` 无法被视为稳定应用层
- `agent` 无法被替换或单独测试
- 任何运行时改动都容易侵入多个层

### 3.2 `SupervisorAgent` 既调度又执行业务细节

它当前承担了过多职责：

- Agent 调度
- 降级策略
- 日级流水线
- 状态写回
- 规则校验接入
- 文件落盘协作

后果：

- 文件持续膨胀
- 调度逻辑和具体业务逻辑难以分别测试
- 新增一个规划阶段时容易继续堆代码

### 3.3 `ChatService` 职责混合

它同时处理：

- session 上下文
- intake 路由
- revision 判断
- tracing
- runtime 调用
- 响应内容组装

后果：

- 聊天入口变成另一个中心节点
- 对话流程稍有变化就要改一大片
- session、trace、revision 难以复用

### 3.4 `llm.py` 与工具系统绑定偏深

`llm.py` 不只负责模型通信，还负责：

- tool calling 循环
- 工具执行
- 工具结果回填

后果：

- 模型客户端与工具执行策略紧耦合
- 替换 tool loop、mock LLM、做纯模型测试都不够顺手

### 3.5 `api` 层仍偏“半控制器半服务”

例如部分路由：

- 直接查询多个 ORM 模型
- 直接处理默认 Session/User 创建
- 直接拼接业务响应结构

后果：

- API 层偏厚
- 业务规则散落在路由
- 后续接 CLI、异步任务、内部调用时复用性差

---

## 4. 目标架构方向

建议逐步收敛到如下职责划分：

```text
api -> application -> domain
                 -> infrastructure

agent -> application ports / domain
infrastructure -> domain
```

更贴合本项目的落地形式：

- `api/`
  - 只负责 HTTP 请求、参数校验、响应映射
- `application/` 或继续使用 `core/`
  - 只负责用例编排，不直接依赖具体实现细节
- `agent/`
  - 只负责决策与调度，不承担存储和大段业务落盘逻辑
- `domain/`
  - 放稳定的业务模型、规则、计划对象、差异对象
- `infrastructure/`
  - 放 db、file store、llm client、tool adapters、第三方客户端
- `composition/` 或 `runtime/`
  - 统一负责依赖装配与对象创建

这里不强制要求你立刻新建 `application/`、`domain/`、`infrastructure/` 三层目录。

更现实的做法是：

1. 先在现有目录中收紧职责。
2. 等边界稳定后，再考虑目录层面的重命名或归并。

---

## 5. 核心解耦原则

### 原则一：依赖方向单向

优先保证：

- `api -> core`
- `agent -> core contracts / types`
- `core -> interfaces`
- `infrastructure -> concrete implementations`

避免：

- `core -> concrete agent`
- `llm -> tools concrete facade`
- `api -> scattered domain logic`

### 原则二：先提取装配层，再抽接口

不要一上来就为每个类建一堆抽象基类。

优先顺序应是：

1. 先把“谁负责创建对象”集中出去
2. 再识别哪些边界真的需要接口
3. 最后才考虑是否拆目录

### 原则三：按职责拆，不按技术名词拆

不要为了看起来“标准分层”而拆出很多空壳模块。

应按实际职责拆：

- 调度
- 流程编排
- 持久化
- tool loop
- session 管理
- tracing
- plan 后处理

### 原则四：每次重构都保留可验证的稳定面

每一阶段都要有明确“完成标准”，例如：

- 行为不变
- 测试仍通过
- 依赖方向减少
- 文件体积下降

---

## 6. 分阶段重构方案

### Phase A：依赖方向矫正

目标：先拆掉最危险的反向依赖。

#### A1. 提取装配层

新增建议模块：

- `travel_planning_agent/runtime/agent_factory.py`
- 或 `travel_planning_agent/runtime/composition.py`

职责：

- 创建 `LLMClient`
- 创建 `PlannerAgent / ResearcherAgent / VerifierAgent / SupervisorAgent`
- 创建 `PlanningRuntime` 所需的协作者

调整后：

- `PlanRunService` 不再直接 `from travel_planning_agent.agent.xxx import ...`
- `PlanRunService` 接收已经装配好的协作者或工厂

收益：

- 去掉 `core -> concrete agent` 的硬依赖
- 更容易在测试中替换 mock agent
- 后续可以为不同产品模式装配不同 agent 集合

#### A2. 让 `core` 只依赖协议或回调

可选做法：

- 通过构造注入传入 `supervisor_runner`
- 或定义简单协议，例如 `PlanningCoordinator`

注意：

- 第一阶段不必设计过重接口
- 只要先把“直接实例化具体类”去掉，就已经收益很大

完成标准：

- `PlanRunService` 中不再出现对具体 Agent 的直接创建
- `core` 包不再 import `agent` 具体实现

---

### Phase B：拆轻 `SupervisorAgent`

目标：把 `SupervisorAgent` 从“上帝类”收敛为“调度中枢”。

建议拆分：

- `SupervisorAgent`
  - 只负责调度、降级、状态推进决策
- `DailyPipelineRunner`
  - 负责 day-level draft/research/refine/verify 流水线
- `PlanningStateService`
  - 负责 state 的局部更新、锁定、上下文写回
- `PlanArtifactService`
  - 负责 `save_state / save_trip_md / save_evidence` 这类产物落盘

建议保留在 `SupervisorAgent` 的职责：

- `dispatch_with_degrade`
- Agent 路由
- 调度阶段推进
- 失败策略选择

建议移出的职责：

- 日级 pipeline 执行细节
- 文件持久化细节
- 共享上下文预取细节
- 与 plan artifact 直接相关的格式化逻辑

完成标准：

- `SupervisorAgent` 主要是编排器
- 大段并发流水线逻辑转移到独立 runner
- `SupervisorAgent` 文件明显变短

---

### Phase C：拆轻 `ChatService`

目标：让 chat 入口从“全能服务”变成“对话用例编排器”。

建议拆分：

- `ChatService`
  - 只保留入口编排
- `ChatSessionService`
  - 负责上下文加载、保存、消息追加、session touch
- `ChatRevisionService`
  - 负责 revision 识别与 revision 应用流程
- `ChatIntakeService`
  - 负责 intake 请求构建、执行与 incomplete/complete 分流
- `TraceService`
  - 负责 trace context 与事件记录门面

这一步的关键不是目录，而是职责可替换。

收益：

- 更容易测试“缺信息追问”
- 更容易测试“revision 流程”
- 更容易替换 session 存储策略

完成标准：

- `ChatService` 从重逻辑类变成薄编排类
- session / revision / trace 不再揉在一个文件里

---

### Phase D：拆分 LLM 与 Tool Loop

目标：让 `llm.py` 只做模型通信，不兼任工具编排器。

建议拆分：

- `llm_client.py`
  - 只负责和模型 API 通信
- `tool_calling_service.py`
  - 负责 tool calling 循环
- `tool_executor.py`
  - 负责执行工具并返回统一结果
- `tool_registry.py`
  - 负责工具元数据与 schema

推荐的数据流：

```text
Agent
  -> ToolCallingService
      -> LLMClient
      -> ToolExecutor
      -> LLMClient
```

这样 `LLMClient` 不需要知道：

- 工具怎么执行
- 工具注册在哪里
- 工具失败如何降级

收益：

- mock LLM 更容易
- mock tool executor 更容易
- 以后替换模型供应商几乎不影响工具执行层

完成标准：

- `llm.py` 或替代模块中不再直接调用 `tools.execute_tool`
- tool loop 从 LLM client 中抽出

---

### Phase E：收薄 API 层

目标：让路由只保留传输职责。

建议拆分：

- `TripApplicationService`
  - trip 创建、读取、聚合 plan version
- `SessionApplicationService`
  - session 生命周期逻辑
- `PreferenceApplicationService`
  - 偏好保存/读取

API 层只做：

- request model
- 调用 service
- response model mapping

这一步优先级低于前四步，因为它带来的收益不如核心流程解耦直接，但仍然值得在后续做。

---

## 7. 优先级与实施顺序

建议按下面顺序推进：

1. **第一优先级**
   - 提取装配层
   - 去掉 `core -> agent` 直接依赖

2. **第二优先级**
   - 拆 `SupervisorAgent`
   - 把流水线执行逻辑抽到独立 runner

3. **第三优先级**
   - 拆 `ChatService`
   - 收缩 session / trace / revision 职责

4. **第四优先级**
   - 抽出 tool calling service
   - 让 LLM client 与工具执行解耦

5. **第五优先级**
   - 收薄 API 层
   - 补足应用服务边界

这个顺序的原因是：

- 前三项会直接降低核心耦合
- 对现有功能最有结构性收益
- 改造风险相对可控

---

## 8. 建议的新模块草图

以下不是强制目录结构，而是推荐职责落点。

```text
travel_planning_agent/
  api/
  agent/
  core/
    planning_runtime.py
    plan_run_service.py
    daily_pipeline_runner.py
    planning_state_service.py
    chat_service.py
    chat_revision_service.py
    chat_session_service.py
    tool_calling_service.py
  runtime/
    composition.py
    agent_factory.py
  tools/
    registry.py
    executor.py
  infrastructure/
    llm_client.py
    file_artifact_store.py
    plan_repository.py
```

如果你暂时不想引入 `infrastructure/` 目录，也可以先不动目录，只做职责提取。

---

## 9. 风险与控制措施

### 风险一：重构过程中行为回归

控制方式：

- 每一阶段只改一个中心点
- 保持原有测试先绿
- 新增“边界测试”而不是只看集成测试

### 风险二：为了抽象而抽象

控制方式：

- 先提取具体协作者
- 接口只在有两个以上候选实现或明确 mock 需求时再引入

### 风险三：文件减少了，但调用链更绕

控制方式：

- 每个新模块必须有一句话职责定义
- 新模块如果只有简单转发且没有稳定价值，就不要拆

### 风险四：并发流水线拆分后状态管理变乱

控制方式：

- 把 state 写回口集中
- 并发 worker 只返回结果，不直接任意修改主状态

---

## 10. 验收标准

当以下条件成立时，可认为本轮解耦成功：

1. `core` 不再直接创建具体 Agent。
2. `SupervisorAgent` 的主要职责收敛为调度，不再承载大段流水线细节。
3. `ChatService` 不再同时承担 session、trace、revision、runtime 全流程。
4. `LLMClient` 与工具执行分离。
5. API 路由不再直接堆放过多业务逻辑。
6. 现有主要测试仍通过。
7. 新增若干边界测试，确保依赖方向不会轻易回退。

---

## 11. 推荐的第一轮低风险落地包

如果只做一轮、且希望投入小但收益明显，建议只做下面 4 件事：

### 第一轮范围

1. 提取 `runtime/composition.py`
2. 修改 `PlanRunService`，不再直接创建具体 Agent
3. 从 `SupervisorAgent` 提取 `DailyPipelineRunner`
4. 从 `ChatService` 提取 `ChatRevisionService` 或 `ChatSessionService`

### 第一轮预期收益

- 去掉最明显的反向依赖
- 降低两个最大中心类的体积
- 不需要大规模迁移所有文件
- 对现有测试和产品行为影响较小

### 第一轮不做的事

- 不重命名全部目录
- 不引入过度抽象的接口体系
- 不改动前端与 API 协议
- 不同时重构 tool runtime 与 db 层

---

## 12. 结论

这个项目当前最需要的不是“继续加层”，而是：

**先把对象创建挪出去，先把中心类拆轻，先把 tool loop 从 LLM 客户端里分离出来。**

只要先把这三件事做好，项目的耦合度会明显下降，后续再演进到更标准的应用层 / 领域层 / 基础设施层会自然得多。

建议把这次解耦当成一次 **结构收口**，而不是一次“全量重构”。  
目标不是立刻变成最漂亮的架构，而是先把最危险的耦合点消掉，让后续每一次开发都更轻松。
