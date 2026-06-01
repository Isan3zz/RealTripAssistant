"""
agent/polisher.py — Polish Agent

在规划完成后执行一次 LLM 调用，将 Planner 产出的骨架行程润色为
完整的、可读性强的最终行程，包含天气建议、自然语言描述等。
"""

import json
import logging
from datetime import timedelta
from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    PlanState, SegmentType,
)
from travel_planning_agent.tools import execute_tool

logger = logging.getLogger(__name__)

POLISH_PROMPT = """你是一个行程润色助手。你的任务是将旅行规划系统产出的骨架行程润色为完整、自然、可读性强的最终行程。

## 旅行概况

- 目的地：{destination}
- 行程天数：{days}天
- 出发日期：{start_date}
- 出行节奏：{pace}
- 出行人员：{travelers}

## 天气预报

{weather_text}

## 原始行程（骨架）

{itinerary_text}

## 润色要求

### 天气与出行提醒
- 每天第 1 个段之前加一句天气说明，包含当天天气和着装/雨具建议
- 有雨 → ☂ 建议带伞
- 高温（≥30°C）→ ☀ 注意防晒
- 天气好的不提雨具

### 段描述润色
- **transport**：写清楚起终点，如"从成都东站乘 G2204 次高铁前往西安北站"
- **activity**：描述具体做什么，如"沿西湖白堤漫步至断桥，欣赏湖光山色"
- **meal**：点名具体美食类型，如"在河坊街品尝杭州小笼包和东坡肉"
- **accommodation**：描述酒店特点和位置，如"入住全季酒店（西湖店），毗邻湖滨商圈"

### 不可修改的字段
- 时间（start_time / end_time）不变
- 价格（estimated_cost）不变
- 段类型（type）不变
- 段数量不变
- segment_id 不变

## 输出格式

按以下 JSON 格式输出（纯 JSON，不要 markdown 包裹）：

{{
  "days": [
    {{
      "day_number": 1,
      "weather_note": "多云22-28°C，适合出游",
      "segments": [
        {{
          "segment_id": "s_xxx",
          "title": "从成都东站乘坐G2204次高铁前往西安北站（约3.5小时）"
        }},
        {{
          "segment_id": "s_yyy",
          "title": "沿西湖白堤漫步至断桥，欣赏湖光山色"
        }}
      ]
    }}
  ]
}}
"""


class PolishAgent(BaseAgent):
    """行程润色 Agent：规划完成后润色整个行程。"""

    agent_name = "polisher"
    context_required = ContextRequirement(levels=[0, 2])

    def handle(self, request: AgentRequest) -> AgentResponse:
        params = request.params
        state: PlanState = params.get("state")
        if not state or not state.constraints:
            return AgentResponse(request_id=request.request_id, status="failed", data={}, error="缺少 state")

        c = state.constraints

        # 1. 获取天气数据（优先复用预取数据，避免重复 API 调用）
        weather = self._get_weather_from_evidence(state) or self._fetch_weather(c.destination)

        # 2. 构建骨架行程文本
        itinerary_text = self._build_itinerary_text(state)

        # 3. 调 LLM 润色
        prompt = POLISH_PROMPT.format(
            destination=c.destination,
            days=c.days,
            start_date=str(c.start_date),
            pace=c.pace,
            travelers=self._travelers_desc(c),
            weather_text=weather or "无天气预报数据",
            itinerary_text=itinerary_text,
        )
        result = self.llm_client.generate("你是一个旅行文案专家。", prompt, tools=None)

        if not result.success or not result.data:
            logger.warning("Polish Agent LLM 调用失败: %s", result.error)
            return AgentResponse(request_id=request.request_id, status="degraded", data={})

        # 4. 解析输出，更新 segment 标题和 day_note
        days_data = result.data.get("days", [])
        day_map = {d.get("day_number"): d for d in days_data}

        for day in state.days:
            polished = day_map.get(day.day_number)
            if not polished:
                continue
            day.day_note = polished.get("weather_note", "") or ""

            # 按 segment_id 匹配更新标题
            polished_segs = {s["segment_id"]: s for s in polished.get("segments", []) if "segment_id" in s}
            for seg in day.segments:
                if seg.segment_id in polished_segs:
                    new_title = polished_segs[seg.segment_id].get("title", "").strip()
                    if new_title:
                        seg.title = new_title

        return AgentResponse(
            request_id=request.request_id,
            status="success",
            data={"polished_days": len(days_data)},
            tokens_used=result.tokens_used,
        )

    # ── 辅助方法 ──

    @staticmethod
    def _get_weather_from_evidence(state: PlanState) -> str:
        """从 state.evidence 中查找预取的天气数据，避免重复 API 调用。"""
        for ev in state.evidence.values():
            if ev.evidence_id.endswith("_pref_weather") and ev.claim:
                return ev.claim
        return ""

    @staticmethod
    def _fetch_weather(destination: str) -> str:
        try:
            result = execute_tool("get_weather_forecast", {"city": destination, "date": ""})
            if result and "天气预报" in result:
                return result
        except Exception as e:
            logger.warning("天气获取失败: %s", e)
        return ""

    @staticmethod
    def _travelers_desc(constraints) -> str:
        labels = {"adult": "成人", "elderly": "老人", "child": "小孩"}
        groups = {}
        for t in constraints.travelers:
            groups[t.age_group] = groups.get(t.age_group, 0) + 1
        if not groups:
            return "1位成人"
        return "、".join(f"{n}位{labels.get(g, g)}" for g, n in groups.items())

    @staticmethod
    def _build_itinerary_text(state: PlanState) -> str:
        lines = []
        for day in state.days:
            lines.append(f"Day {day.day_number}:")
            for seg in day.segments:
                t = f"{seg.start_time or ''}-{seg.end_time or ''}" if seg.start_time else ""
                cost = f" ¥{seg.estimated_cost.amount:,.0f}" if seg.estimated_cost and seg.estimated_cost.amount else ""
                lines.append(f"  [{seg.type.value}] {t} {seg.title}{cost}  (id: {seg.segment_id})")
            lines.append("")
        return "\n".join(lines)
