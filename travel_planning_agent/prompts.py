# -*- coding: utf-8 -*-
"""
prompts.py — 提示词集中管理

所有 LLM 提示词模板统一在此管理。
提供 PromptTemplate 封装和 ConstraintsMessage 结构化构建。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


# ═══════════════════════════════════════════════════════
#  PromptTemplate — 提示词模板封装
# ═══════════════════════════════════════════════════════

@dataclass
class PromptTemplate:
    """提示词模板，封装模板字符串 + 变量校验 + 格式化。"""
    name: str
    template: str
    variables: list[str] = field(default_factory=list)
    version: str = "1.0"

    def format(self, **kwargs) -> str:
        _validate_vars(self.variables, kwargs)
        return self.template.format(**kwargs)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "variables": self.variables,
            "template": self.template,
        }


def _validate_vars(expected: list[str], actual: dict):
    missing = [v for v in expected if v not in actual]
    if missing:
        raise KeyError(f"模板变量缺失: {', '.join(missing)}")


# ═══════════════════════════════════════════════════════
#  ConstraintsMessage — 约束消息结构化构建
# ═══════════════════════════════════════════════════════

@dataclass
class ConstraintsMessage:
    """结构化约束消息，支持文本渲染和字段提取。"""
    destination: str
    days: int
    start_date: date
    travelers: list[dict]
    budget: float
    origin: str
    pace: str
    transport_mode: str = ""
    preferences_detail: str = ""
    interests: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, constraints) -> "ConstraintsMessage":
        from travel_planning_agent.types import Constraints
        if not isinstance(constraints, Constraints):
            raise TypeError(f"期望 Constraints 类型，收到 {type(constraints)}")
        return cls(
            destination=constraints.destination,
            days=constraints.days,
            start_date=constraints.start_date,
            travelers=[{"age_group": t.age_group, "note": t.note} for t in constraints.travelers],
            budget=constraints.budget,
            origin=constraints.origin or "",
            pace=constraints.pace,
            transport_mode=constraints.transport_mode or "",
            preferences_detail=constraints.preferences_detail or "",
            interests=list(constraints.interests or []),
        )

    def _travelers_desc(self) -> str:
        labels = {"adult": "成人", "elderly": "老人", "child": "小孩"}
        groups = {}
        for t in self.travelers:
            g = t["age_group"]
            groups[g] = groups.get(g, 0) + 1
        parts = [
            f"{count}位{labels.get(g, g)}"
            for g, count in groups.items()
        ]
        return "、".join(parts) if parts else "1位成人"

    def to_text(self) -> str:
        parts = [
            f"请为 {self.destination} 规划 {self.days} 天行程。",
            f"出发日期：{self.start_date}",
        ]
        if self.origin:
            parts.append(f"出发城市：{self.origin}")
        parts += [
            f"出行人员：{self._travelers_desc()}",
            f"总预算：{self.budget} 元",
            f"节奏偏好：{self.pace}",
        ]
        if self.transport_mode:
            parts.append(f"交通偏好：{self.transport_mode}（后续所有交通安排优先按此方式）")
        if self.interests:
            parts.append(f"必去项：{'、'.join(self.interests)}（硬性约束，必须至少安排一次，不能用同类景点替代）")
        if self.preferences_detail:
            parts.append(f"其他偏好：{self.preferences_detail}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "destination": self.destination,
            "days": self.days,
            "start_date": self.start_date.isoformat() if isinstance(self.start_date, date) else str(self.start_date),
            "travelers": self.travelers,
            "budget": self.budget,
            "origin": self.origin,
            "pace": self.pace,
            "transport_mode": self.transport_mode,
            "preferences_detail": self.preferences_detail,
            "interests": list(self.interests),
        }


# ═══════════════════════════════════════════════════════
#  模板定义
# ═══════════════════════════════════════════════════════

# --- 模块化规划使用 MODULE_DRAFT/REFINE/REVISE 模板 ---

# --- INT-001: Intake Agent 对话提取 ---
INTAKE_PROMPT_TEMPLATE = PromptTemplate(
    name="INT-001",
    template="""你是一个旅行规划助手的对话前端。你的职责是通过多轮对话收集用户的旅行需求。

## 约束条件

需要收集以下字段：
- destination（目的地）— 必填
- start_date（出发日期）— 必填，格式 YYYY-MM-DD，用户说相对日期时用 get_current_date 工具推算年份
- days（天数）— 必填
- budget（预算）— 必填
- origin（出发城市）— 必填，如用户说"从成都出发"则填成都
- travelers（人员）— 选填，如"2位成人1位老人"
- pace（内部节奏）— 选填，slow/moderate/fast；如需追问用户，不要问“慢/适中/快”，改问旅行方式偏好：轻松慢游/经典初游/美食深度/省钱优先
- transport_mode（交通偏好）— 选填，如"高铁"、"动车"、"飞机"、"自驾"
- preferences_detail（自由文本偏好）— 选填，如"想坐10点左右的高铁、要一等座、靠窗"
- interests（必去项）— 选填，数组；用户说"必须去/一定要去/必去/想去"的具体景点或活动放这里

## 说明

- 系统时间已标注在用户消息中，直接使用
- 用户说相对日期（如"5月4号"）时，根据系统时间推算具体年份

## 输出格式

### 信息完整时
{
  "complete": true,
  "constraints": {
    "destination": "西安",
    "start_date": "2026-05-08",
    "days": 3,
    "origin": "成都",
    "travelers": "2位成人",
    "budget": 5000,
    "pace": "moderate",
    "transport_mode": "高铁",
    "preferences_detail": "想坐10点左右的高铁、要一等座",
    "interests": ["陕西历史博物馆"]
  }
}

### 信息不完整时
{
  "complete": false,
  "question": "请问您从哪个城市出发？",
  "extracted": {
    "destination": "西安",
    "start_date": null,
    "days": null,
    "origin": null,
    "travelers": null,
    "budget": null,
    "pace": null,
    "transport_mode": null,
    "preferences_detail": null,
    "interests": []
  }
}

## 规则

- 用户说了什么就提取什么，没说的字段填 null
- 用户明确说"必须去/一定要去/必去"时，这不是普通偏好，必须写入 interests
- extracted 里的已有信息不要丢弃，累加
- 用户可能在已有计划基础上修改，比如"改成两个人"→ travelers 从 1 改 2，其他不变
- 一次只问一个问题，追问顺序：出发城市 → 日期 → 天数 → 预算
- 基于已提取的信息追问，已经知道了就别再问
- 如果需要追问节奏或风格，固定问：请问你更偏向哪种旅行方式：轻松慢游、经典初游、美食深度，还是省钱优先？
- 禁止输出“请问您这次旅行的节奏是怎样的？慢/适中/快？”这类旧三档节奏问题
- 轻松慢游可映射 pace=slow；经典初游、美食深度、省钱优先可映射 pace=moderate，并把具体风格写入 preferences_detail
- 如果用户没说出发城市且目的地已知，提示请问您从哪个城市出发？""",
    version="1.0",
)

INTAKE_PROMPT = INTAKE_PROMPT_TEMPLATE.template

# --- MOD-REF-001: 模块级精修 ---
MODULE_REFINE_PROMPT_TEMPLATE = PromptTemplate(
    name="MOD-REF-001",
    template="""你是一个旅行规划师。请用真实数据替换第 {day_number} 天 {module_name} 时间段的初稿估算值。

## 初稿行程

{draft_segments_text}

## 新获取的参考信息

{evidence_text}

## 替换规则（必须遵守）

1. **交通**：evidence 中有具体航班号/车次号的，必须照搬，不得写"高铁/飞机"
2. **酒店**：evidence 中有具体酒店名称和价格的，必须使用真实名称和价格；优先选择靠近当天核心景点/商圈的酒店
3. **门票**：evidence 中有参考价的，用参考价替换 estimated_cost
4. **交通路线**：对 transport 类型的段，用 get_driving_eta/get_walking_route/get_transit_route 工具查询真实路线，更新具体交通方式和 title（如"步行8分钟"→"步行前往"、"地铁3号线5站"→"乘坐地铁"）
5. **无数据**：evidence 中没有对应数据的段，在 title 后标注"（参考价）"，保留原值
6. **不变**：evidence 没有提及的段，禁止修改其内容
7. **结构**：禁止增删 segments 数量，只修改有证据支持的字段
8. **时间**：禁止修改 start_time 和 end_time（除非 evidence 明确提供营业时间）

### 交通方式选择建议
- 短距离（<1km）→ 步行
- 中距离（1-5km）→ 公交/地铁
- 长距离（>5km）→ 地铁或打车

## 禁止行为

- 禁止自己编造酒店名称、航班号、价格
- 禁止修改不在当前时间段的段
- 禁止改变 segments 数组顺序
- 禁止删除冠有"（参考价）"标记的段

输出格式必须与上方初稿 JSON 完全一致。""",
    variables=["day_number", "module_name", "draft_segments_text", "evidence_text"],
    version="2.0",
)

# --- MOD-REV-001: 模块级修订 ---
MODULE_REVISE_PROMPT_TEMPLATE = PromptTemplate(
    name="MOD-REV-001",
    template="""第 {day_number} 天 {module_name} 时间段的行程校验失败，需要修正。

## 校验错误

{validation_errors}

## 预算状态

{budget_summary}

## 修正规则

1. 必须逐条解决上方列出的每个校验错误
2. 只修改有问题的 segment，校验通过的段不得改动
3. 禁止删除 segment（除非错误明确要求移除）
4. 时间调整后不得与其他段重叠
5. 预算修正后本模块总花费不得超过可用预算
6. 已修订次数：{revision_count}/{max_revisions}
7. 如果已达最大修订次数但仍有错误，尽可能减少错误数量即可

输出修正后的完整 segments 列表，格式与 MODULE_DRAFT 相同。""",
    variables=["day_number", "module_name", "validation_errors", "budget_summary",
               "revision_count", "max_revisions"],
    version="2.0",
)


# ═══════════════════════════════════════════════════════
#  Phase 3.5 按天规划 Prompt（流水线并行）
# ═══════════════════════════════════════════════════════

DAY_DRAFT_PROMPT_TEMPLATE = PromptTemplate(
    name="DAY-DRF-001",
    template="""你是一个旅行规划助手。请为第 {day_number} 天的全天行程做规划。

## 旅行约束

{constraints_text}

## 当天信息

- 日期：第 {day_number} 天
- 剩余天数（含当天）：{remaining_days} 天
{first_day_special}
{last_day_special}

## 前一天结束状态

{previous_day_end_state_text}

## 前一天已安排的行程（禁止重复）

{previous_day_plan_text}

## 已锁定的行程（不可修改）

{locked_segments_text}

## 预算状态

- 总预算：{total_budget} 元
- 已花费：{spent_budget} 元
- 当天可用：{available_budget} 元
- 剩余天数：{remaining_days} 天

## 三个时间段的起止窗口

| 时间段 | 时间窗口 | 典型内容 |
|--------|---------|---------|
| morning | 06:00-12:00 | 早餐→上午景点/活动（第1天含到达交通）|
| afternoon | 12:00-18:00 | 午餐→下午景点/活动 |
| evening | 18:00-00:00 | 晚餐→晚间活动/夜景→住宿 |

## 硬性约束（必须遵守）

### 时间约束
1. morning 段所有 start_time 和 end_time 必须在 06:00-12:00 范围内
2. afternoon 段所有 start_time 和 end_time 必须在 12:00-18:00 范围内
3. evening 段所有 start_time 和 end_time 必须在 18:00-00:00 范围内
4. 同模块内相邻 segment 时间不得重叠（前 end_time <= 后 start_time）
5. 相邻 segment 之间至少预留 10 分钟缓冲时间
6. morning 最后一个 segment 的 end_time <= afternoon 第一个 segment 的 start_time
7. afternoon 最后一个 segment 的 end_time <= evening 第一个 segment 的 start_time
8. morning 第一个 segment 的 start_time 不得早于前一天结束时间
{first_day_constraint}

### 内容约束
9. activity 类型必须有 location（name + city）
10. transport 类型必须有起止地点名称，标注具体交通方式（步行/公交/地铁/打车/高铁/飞机）
11. 同一个时间段内活动不宜跨区太远
12. 相邻时间段的结束/起始位置应连贯（午餐靠近上午最后一个活动，下午活动靠近午餐地点）
13. evening 必须包含当晚住宿（type=accommodation），含酒店名称
14. 不得出现与已锁定行程中相同的活动标题
15. 不得安排与"前一天已安排的行程"中相同的景点/餐厅/活动（禁止重复）
16. 全天 activity 数量不超过 pace 对应上限（slow:2, moderate:4, fast:6）
{last_day_constraint}

### 预算约束
17. 全天所有 segment 的 estimated_cost 之和 <= {available_budget} 元
18. 每个 segment 必须填写 estimated_cost（免费项目填 0）

### 输出格式约束
19. 必须输出纯 JSON，不要 markdown 代码块包裹
20. 每个时间段的 segments 数组元素个数 >= 1（不能为空）
21. start_time 和 end_time 必须是 "HH:MM" 24小时格式

## 生成后自查（输出前逐条确认）

1. morning 最后一个 end_time（__:__）<= afternoon 第一个 start_time（__:__）✓
2. afternoon 最后一个 end_time（__:__）<= evening 第一个 start_time（__:__）✓
3. evening 包含 accommodation ✓
4. 全天费用合计 <= {available_budget} ✓
5. 所有 activity 都有 location ✓
6. 各段 start_time/end_time 在对应时间窗口内 ✓

## 输出格式

{{
  "day_theme": "今日主题（如'初探古城文化'）",
  "modules": {{
    "morning": {{
      "segments": [
        {{
          "type": "transport/activity/meal/accommodation",
          "title": "活动名称",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "location": {{"name": "具体地点", "city": "城市名"}},
          "estimated_cost": {{"amount": 数字, "currency": "CNY"}},
          "tags": ["tag1"],
          "note": ""
        }}
      ]
    }},
    "afternoon": {{
      "segments": [...]
    }},
    "evening": {{
      "segments": [
        ...
      ]
    }}
  }},
  "research_needs": [
    {{"item": "需要核实的项目（景点名/核心景点附近酒店/交通）", "type": "ticket_price/hotel/poi_detail/transport", "reason": "为何需要核实"}}
  ]
}}""",
    variables=[
        "day_number", "constraints_text", "previous_day_end_state_text",
        "previous_day_plan_text",
        "locked_segments_text", "total_budget", "spent_budget",
        "available_budget", "remaining_days",
        "first_day_special", "last_day_special",
        "first_day_constraint", "last_day_constraint",
    ],
    version="1.0",
)


def get_day_prompt(phase: str, **kwargs) -> str:
    """路由到对应的按天规划 prompt。"""
    if phase == "draft":
        return DAY_DRAFT_PROMPT_TEMPLATE.format(**kwargs)
    raise ValueError(f"未知的按天规划阶段: {phase}")


def get_module_prompt(phase: str, **kwargs) -> str:
    """路由到对应的模块级 prompt。"""
    if phase == "refine":
        return MODULE_REFINE_PROMPT_TEMPLATE.format(**kwargs)
    elif phase == "revise":
        return MODULE_REVISE_PROMPT_TEMPLATE.format(**kwargs)
    raise ValueError(f"未知的模块规划阶段: {phase}")


# --- 保留给 semantic_checker 的旧接口（模块化模式未使用） ---
def build_semantic_check_prompt(**kwargs) -> str:
    """存根：模块化模式下不使用语义检查。"""
    return ""
