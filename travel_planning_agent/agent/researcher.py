"""
agent/researcher.py — Researcher Agent

LLM 驱动的多源信息收集。

设计：
  1. 接收旅行约束条件
  2. 用 LLM + RESEARCHER_TOOLS 自主决定查什么、怎么查
  3. LLM 调用工具（高德/途牛），工具失败时 LLM 用自己的知识兜底
  4. LLM 输出 JSON 格式的发现汇总
  5. 解析为 Evidence 对象返回

两阶段流程的 price_lookup 模式不走 LLM，直接途牛查门票价。
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from travel_planning_agent.agent.base import BaseAgent
from travel_planning_agent.types import (
    AgentRequest, AgentResponse, ContextRequirement,
    Evidence, Constraints,
)
from travel_planning_agent.tools import RESEARCHER_TOOLS, execute_tool
from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.core.execution_plan import execution_plan_from_research_tasks
from travel_planning_agent.core.research_plan import build_research_plan
from travel_planning_agent.tuniu_client import search_poi_by_name, check_available
from travel_planning_agent.storage.sqlite_store import cache_get, cache_set, build_cache_key

logger = logging.getLogger(__name__)

# ── 提示词 ──

RESEARCHER_PROMPT = """你是一个旅行规划研究员。你的任务是为当前时间段的行程提供精确信息。

## 旅行约束

{constraints_text}

## 当前日期

{today}

## 需核实的项目

{research_needs_text}

## 可用工具

- query_ticket_price: 【途牛】查景点门票价格
- search_hotel: 【途牛】查目的地酒店，优先传 nearby=核心景点/商圈名，避免只按城市泛搜
- search_flight: 【途牛】查国内航班
- search_train: 【途牛】查火车车次
- search_poi: 搜索景点/美食/购物等 POI

## 工作流程

1. **只查 `需核实的项目` 中列出的内容**，不要多查
2. 每个 `type` 对应的查法：

   | type | 查什么 | 用什么工具 |
   |------|--------|-----------|
   | transport | 具体航班号/车次号、时间、票价 | search_flight 或 search_train |
   | ticket_price | 具体景点的门票价格 | query_ticket_price |
   | hotel | 核心景点/商圈附近的酒店名称、价格、评分、位置 | search_hotel |
   | poi_detail | 景点介绍、开放时间 | search_poi |

3. 工具返回空或失败 → 用你的知识补充，不要重试
4. 输出必须只包含与 `需核实的项目` 相关的发现
5. **交通偏好约束**：如果用户指定了交通偏好（如"自驾"），禁止搜索相反的交通方式（如不要查航班/火车）

## 输出格式

纯 JSON（不要 markdown 包裹）：

{{
  "findings": [
    {{
      "category": "poi/ticket/hotel/transport/weather",
      "title": "名称",
      "detail": "具体信息（含价格、时间、来源）",
      "source": "途牛/高德/模型知识",
      "tags": ["标签"]
    }}
  ],
  "covered_items": ["已核实的项目列表"]
}}
"""


class ResearcherAgent(BaseAgent):
    """LLM 驱动的多源信息收集 Agent。"""

    agent_name = "researcher"
    context_required = ContextRequirement(levels=[0, 2, 5])

    def __init__(self, llm_client):
        super().__init__(llm_client)
        self._tuniu_checked = False
        self._tuniu_available = False
        self.use_react_research = False

    def _is_tuniu_available(self) -> bool:
        """惰性检查 tuniu CLI 是否可用（只检查一次）。"""
        if not self._tuniu_checked:
            self._tuniu_available = check_available()
            self._tuniu_checked = True
            if self._tuniu_available:
                logger.info("途牛 CLI 可用，将使用真实数据")
            else:
                logger.warning("途牛 CLI 不可用，将使用 LLM 知识兜底")
        return self._tuniu_available

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        主入口。根据 mode 决定走 LLM 研究模式还是价格查询模式。
        """
        params = request.params
        mode = params.get("mode", "")

        if mode == "react_research":
            return self._react_research(params)

        # 价格查询模式（两阶段流程的第二阶段）— 不走 LLM，直接查途牛
        if mode == "price_lookup":
            return self._price_lookup(params)

        if self.use_react_research and params.get("research_needs"):
            return self._react_research(params)

        # 并行研究模式：research_needs 直接转工具调用，并行执行
        research_needs = params.get("research_needs", [])
        if research_needs:
            return self._parallel_research(params, research_needs)

        # 兜底：LLM 驱动的研究模式
        return self._research_mode(params, request.context_summary)

    def _react_research(self, params: dict) -> AgentResponse:
        """Bounded ReAct research mode for dynamic tool decisions."""
        from travel_planning_agent.core.react_loop import run_react_loop

        constraints: Constraints = params.get("constraints")
        if not constraints:
            return AgentResponse(request_id="", status="failed", data={}, error="缺少 constraints")

        research_needs = params.get("research_needs", [])
        context = {
            "destination": constraints.destination,
            "origin": constraints.origin,
            "start_date": constraints.start_date.isoformat(),
            "days": constraints.days,
            "budget": constraints.budget,
            "pace": constraints.pace,
            "transport_mode": constraints.transport_mode,
            "interests": list(constraints.interests or []),
            "research_needs": research_needs,
        }
        result = run_react_loop(
            self.llm_client,
            task="Research travel facts for the requested itinerary. Return findings and covered_items.",
            context=context,
            allowed_tools=[
                "search_poi",
                "get_weather_forecast",
                "query_ticket_price",
                "search_hotel",
                "get_hotel_detail",
                "search_flight",
                "search_train",
                "geo_encode",
                "search_around",
            ],
            max_steps=5,
        )
        if result.status != "success":
            fallback = self._fallback_model_knowledge(params)
            fallback.data = dict(fallback.data or {})
            fallback.data["react"] = {"status": result.status, "error": result.error}
            return fallback

        evidence_list = []
        for finding in result.final.get("findings") or []:
            if isinstance(finding, dict):
                evidence_list.append(self._finding_to_evidence(finding, constraints.destination))

        return AgentResponse(
            request_id="",
            status="success",
            data={
                "evidence": evidence_list,
                "react": {
                    "status": result.status,
                    "steps": [
                        {
                            "step_index": step.step_index,
                            "tool": step.tool,
                            "args": step.args,
                            "observation_status": step.observation_status,
                            "rationale_summary": step.rationale_summary,
                        }
                        for step in result.steps
                    ],
                    "covered_items": result.final.get("covered_items") or [],
                },
            },
            tokens_used=result.tokens_used,
            source_note="react_tool_loop",
        )

    def _parallel_research(self, params: dict, research_needs: list) -> AgentResponse:
        """LLM 规划 → 并行执行 → LLM 汇总。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        constraints: Constraints = params.get("constraints")
        if not constraints:
            return AgentResponse(request_id="", status="failed", data={}, error="缺少 constraints")

        tool_call_registry = params.get("tool_call_registry")
        destination = constraints.destination
        today = datetime.now().strftime("%Y-%m-%d")
        # Research semantics: decide what facts we need for this draft.
        research_plan = build_research_plan(
            constraints,
            research_needs,
            draft_result=params.get("draft_result"),
            today=today,
        )
        tool_calls = [
            {"tool": task.tool_name, "args": task.args, "reuse_key": task.reuse_key}
            for task in research_plan.tasks
        ]
        logger.info("ResearchPlan built: %s", research_plan.to_dict())
        # Execution shape: represent those research tasks as executable tool work.
        execution_plan = execution_plan_from_research_tasks(
            f"exec_research_{uuid.uuid4().hex[:8]}",
            research_plan.tasks,
        )
        execution_result = execute_execution_plan(
            execution_plan,
            reuse_context=tool_call_registry,
        )
        evidence_list = list(execution_result.get("evidence") or [])
        execution_results = list(execution_result.get("results") or [])
        all_duplicate = bool(execution_results) and all(
            getattr(result, "status", None) == "skipped_duplicate"
            for result in execution_results
        )
        if evidence_list:
            return AgentResponse(
                request_id="",
                status="success",
                data={
                    "evidence": evidence_list,
                    "research_plan": research_plan.to_dict(),
                    "execution_plan": execution_plan.to_dict(),
                    "tool_calls": execution_result.get("tool_calls") or tool_call_registry,
                },
                tokens_used=0,
                source_note="execution_plan",
            )

        if all_duplicate:
            return AgentResponse(
                request_id="",
                status="success",
                data={
                    "evidence": [],
                    "research_plan": research_plan.to_dict(),
                    "execution_plan": execution_plan.to_dict(),
                    "tool_calls": execution_result.get("tool_calls") or tool_call_registry,
                    "reused_evidence_ids": [
                        evidence_id
                        for result in execution_results
                        for evidence_id in (getattr(result, "evidence_ids", []) or [])
                    ],
                },
                tokens_used=0,
                source_note="execution_plan_duplicate",
            )

        # ── Step 2: 并行执行工具 ──
        evidence_list = []
        if tool_calls:
            with ThreadPoolExecutor(max_workers=min(len(tool_calls), 5)) as executor:
                fut_map = {}
                for tc in tool_calls:
                    tool_name = tc.get("tool", "")
                    args = tc.get("args", {})
                    if tool_name and args:
                        fut = executor.submit(execute_tool, tool_name, args)
                        fut_map[fut] = (tool_name, args)

                for fut in as_completed(fut_map):
                    tool_name, args = fut_map[fut]
                    try:
                        result = fut.result()
                        if result and "查询失败" not in result:
                            evidence_list.append({
                                "evidence_id": f"ev_{uuid.uuid4().hex[:8]}",
                                "source": "API",
                                "source_type": "api",
                                "retrieved_at": datetime.now().isoformat(),
                                "claim": f"[{tool_name}] {result[:300]}",
                                "confidence": "high",
                            })
                    except Exception as e:
                        logger.warning("工具 %s 失败: %s", tool_name, e)

        if not evidence_list:
            logger.info("并行查询无结果，走 LLM 知识兜底")
            return self._fallback_model_knowledge(params)

        # ── Step 3: LLM 汇总为 findings ──
        ev_text = "\n".join(f"  {e['claim'][:200]}" for e in evidence_list)
        summary_prompt = f"""以下是查询到的信息，请整理为 findings。

目的地：{destination}

查询结果：
{ev_text}

输出格式：
{{"findings": [{{"category": "poi/ticket/hotel/transport/weather/social_advice", "title": "名称", "detail": "具体信息（含价格/建议）", "source": "来源"}}]}}"""
        summary_result = self.llm_client.generate("你是一个信息整理助手。", summary_prompt, tools=None)
        if summary_result.success and summary_result.data:
            findings = summary_result.data.get("findings", [])
            for f in findings:
                evidence_list.append(self._finding_to_evidence(f, destination))
            tokens = summary_result.tokens_used or 0
        else:
            tokens = 0

        return AgentResponse(
            request_id="", status="success",
            data={
                "evidence": evidence_list,
                "research_plan": research_plan.to_dict(),
                "tool_calls": execution_result.get("tool_calls") or tool_call_registry,
            },
            tokens_used=tokens,
            source_note="auto",
        )

    def _research_mode(self, params: dict, context_summary: str) -> AgentResponse:
        """LLM 驱动的信息收集（模块级：只查 research_needs 指定的内容）。"""
        constraints: Constraints = params.get("constraints")
        if not constraints:
            return AgentResponse(
                request_id="", status="failed", data={},
                error="缺少 constraints 参数",
            )

        # 构造约束文本
        travelers_desc = self._travelers_desc(constraints)
        origin_str = f"出发城市：{constraints.origin}\n" if constraints.origin else ""
        transport_str = f"交通偏好：{constraints.transport_mode}\n" if constraints.transport_mode else ""
        pref_str = f"其他偏好：{constraints.preferences_detail}\n" if constraints.preferences_detail else ""
        constraints_text = (
            f"目的地：{constraints.destination}\n"
            f"天数：{constraints.days}天\n"
            f"出发日期：{constraints.start_date}\n"
            f"{origin_str}"
            f"{transport_str}"
            f"{pref_str}"
            f"人员：{travelers_desc}\n"
            f"预算：{constraints.budget}元\n"
            f"节奏：{constraints.pace}\n"
        ).strip()

        if context_summary:
            constraints_text += f"\n\n附加上下文：\n{context_summary}"

        # 构造 research_needs 文本（模块级，精确指定查什么）
        research_needs = params.get("research_needs", [])
        if research_needs:
            needs_lines = [f"请核实以下 {len(research_needs)} 项内容："]
            for i, need in enumerate(research_needs, 1):
                item = need.get("item", "?") if isinstance(need, dict) else str(need)
                ntype = need.get("type", "poi_detail") if isinstance(need, dict) else "poi_detail"
                reason = need.get("reason", "") if isinstance(need, dict) else ""
                needs_lines.append(f"  {i}. [{ntype}] {item}")
                if reason:
                    needs_lines.append(f"     原因：{reason}")
            research_needs_text = "\n".join(needs_lines)
        else:
            research_needs_text = "（无特定核实需求，按常规搜索目的地基本信息）"

        today = datetime.now().strftime("%Y-%m-%d")
        prompt = RESEARCHER_PROMPT.format(
            constraints_text=constraints_text,
            today=today,
            research_needs_text=research_needs_text,
        )

        # 调 LLM 用工具收集信息
        try:
            result = self.llm_client.generate(prompt, "请开始收集信息。", tools=RESEARCHER_TOOLS)
        except Exception as e:
            logger.warning("Researcher LLM 调用失败: %s", e)
            return self._fallback_model_knowledge(params)

        if not result.success:
            logger.warning("Researcher LLM 失败: %s", result.error)
            return self._fallback_model_knowledge(params)

        # 解析 LLM 输出
        findings = []
        if result.data and "findings" in result.data:
            findings = result.data["findings"]
        elif result.data:
            # 可能是其他格式，尝试提取
            for key in ("results", "evidence", "poi_list", "data"):
                if key in result.data and isinstance(result.data[key], list):
                    findings = result.data[key]
                    break

        if not findings:
            logger.info("Researcher LLM 未返回结构化发现，走 LLM 知识兜底")
            return self._fallback_model_knowledge(params)

        # 创建 Evidence 对象
        evidence_list = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            ev = self._finding_to_evidence(f, constraints.destination)
            evidence_list.append(ev)

        # 工具原始结果也作为 evidence（绕过 LLM 总结的信息丢失）
        if result.tool_calls_log:
            added_tools = set()
            for tc in result.tool_calls_log:
                tname = tc.get("tool", "")
                if tname in added_tools or tname in ("search_poi", "get_weather_forecast"):
                    continue
                added_tools.add(tname)
                tres = tc.get("result", "")
                if tres and not tres.endswith("暂未查到"):
                    evidence_list.append({
                        "evidence_id": f"ev_{uuid.uuid4().hex[:8]}",
                        "source": "途牛API" if "tuniu" in tname else "高德",
                        "source_type": "api",
                        "retrieved_at": datetime.now().isoformat(),
                        "claim": tres[:200],
                        "confidence": "high",
                    })

        source_note = "tuniu_api" if self._is_tuniu_available() else "model_knowledge"

        return AgentResponse(
            request_id="",
            status="success",
            data={"evidence": evidence_list},
            tokens_used=result.tokens_used,
            source_note=source_note,
        )

    def _price_lookup(self, params: dict) -> AgentResponse:
        """
        查具体景点的真实门票价格（两阶段流程的第二阶段）。

        Planner 已确定景点名，逐一查途牛，查不到的用 LLM 知识估参考价。
        """
        scenic_names = params.get("scenic_names", [])
        tuniu_ok = self._is_tuniu_available()
        results = []

        if not scenic_names:
            return AgentResponse(request_id="", status="success",
                                 data={"evidence": []}, source_note="no_scenic_names")

        if tuniu_ok:
            for name in scenic_names:
                cache_key = build_cache_key("ticket_price", scenic_name=name)
                cached = cache_get(cache_key)
                if cached:
                    results.extend(cached)
                    continue

                ticket_data = search_poi_by_name(name)
                if ticket_data:
                    cache_set(cache_key, ticket_data, ttl_seconds=3600)
                    results.extend(ticket_data)
                    logger.info("途牛查价成功: %s", name)
                else:
                    logger.info("途牛查价失败: %s", name)

        # 查不到的用 LLM 知识估参考价
        found_names = {r.get("title") for r in results}
        for name in scenic_names:
            if name not in found_names:
                results.append({
                    "title": name,
                    "description": f"{name} 参考价格",
                    "category": "ticket",
                    "claim": f"{name} 参考价格（来源：模型知识）",
                    "source": "模型知识",
                    "source_type": "model_knowledge",
                    "confidence": "low",
                })

        evidence_list = [self._to_evidence(r) for r in results]
        return AgentResponse(
            request_id="", status="success",
            data={"evidence": evidence_list},
            tokens_used=0,
            source_note="tuniu_api" if tuniu_ok else "model_knowledge",
        )

    def _fallback_model_knowledge(self, params: dict) -> AgentResponse:
        """L2 降级：用模型知识兜底。"""
        constraints: Constraints = params.get("constraints")
        if not constraints:
            return AgentResponse(
                request_id="", status="degraded", data={"evidence": []},
                source_note="model_knowledge",
            )

        # 用 search_poi 工具获取基础信息
        result_text = execute_tool("search_poi", {
            "destination": constraints.destination,
            "category": "cultural",
            "context": f"为{constraints.destination}规划{constraints.days}天行程",
        })

        ev = self._to_evidence({
            "title": f"{constraints.destination} 旅行信息",
            "description": result_text,
            "category": "poi",
            "claim": f"关于{constraints.destination}的旅行推荐（来源：模型知识）",
            "source": "模型知识",
            "source_type": "model_knowledge",
            "confidence": "medium",
        })

        return AgentResponse(
            request_id="", status="degraded",
            data={"evidence": [ev]},
            source_note="model_knowledge",
        )

    # ── 辅助方法 ──

    def _finding_to_evidence(self, finding: dict, destination: str) -> dict:
        """将 LLM 输出的 finding 转为 Evidence 格式。"""
        category = finding.get("category", "poi")
        title = finding.get("title", "")
        detail = finding.get("detail", "")
        source = finding.get("source", "模型知识")

        # 构造 claim
        if category == "weather":
            claim = detail or f"{destination} 天气预报"
        elif category == "hotel":
            claim = f"{title}: {detail}" if title else detail
        else:
            claim = f"{title}: {detail}" if title else detail

        source_type = "model_knowledge"
        confidence = "medium"
        if source in ("高德POI", "高德天气"):
            source_type = "api"
            confidence = "high"
        elif source == "途牛":
            source_type = "api"
            confidence = "high"

        return {
            "evidence_id": f"ev_{uuid.uuid4().hex[:8]}",
            "source": source,
            "source_type": source_type,
            "retrieved_at": datetime.now().isoformat(),
            "claim": claim,
            "confidence": confidence,
            "url_reachable": None,
        }

    @staticmethod
    def _to_evidence(raw: dict) -> dict:
        """原始结果 → Evidence 格式。"""
        source_type = raw.get("source_type", "model_knowledge")
        confidence = raw.get("confidence", "medium")

        return {
            "evidence_id": f"ev_{uuid.uuid4().hex[:8]}",
            "source": raw.get("source", "模型知识"),
            "source_type": source_type,
            "retrieved_at": datetime.now().isoformat(),
            "claim": raw.get("claim", ""),
            "confidence": confidence,
            "url_reachable": None,
        }

    @staticmethod
    def _travelers_desc(constraints: Constraints) -> str:
        """格式化人员描述。"""
        labels = {"adult": "成人", "elderly": "老人", "child": "小孩"}
        groups = {}
        for t in constraints.travelers:
            groups[t.age_group] = groups.get(t.age_group, 0) + 1
        if not groups:
            return "1位成人"
        return "、".join(f"{n}位{labels.get(g, g)}" for g, n in groups.items())
