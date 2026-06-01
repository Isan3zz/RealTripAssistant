"""Build structured research plans from planner needs."""

from __future__ import annotations

from datetime import datetime

from travel_planning_agent.core.lodging_selector import select_lodging_anchor
from travel_planning_agent.types import Constraints, ResearchPlan, ResearchTask


def build_research_plan(
    constraints: Constraints,
    research_needs: list[dict],
    draft_result: dict | None = None,
    today: str | None = None,
) -> ResearchPlan:
    today = today or datetime.now().strftime("%Y-%m-%d")
    destination = constraints.destination
    hotel_anchor = select_lodging_anchor(constraints, draft_result, research_needs)

    tasks: list[ResearchTask] = []
    for need in research_needs:
        if not isinstance(need, dict):
            continue
        ntype = need.get("type", "")
        item = str(need.get("item", "") or "")
        reason = str(need.get("reason", "") or "")

        if ntype == "ticket_price":
            scenic_name = item or hotel_anchor
            tasks.append(ResearchTask(
                task_type=ntype,
                tool_name="query_ticket_price",
                args={"scenic_name": scenic_name},
                reason=reason or f"核实 {scenic_name} 门票价格",
                priority=4,
                reuse_key=f"ticket:{scenic_name}",
            ))
        elif ntype == "hotel":
            anchor = _hotel_anchor_from_item(item, destination) or hotel_anchor
            tasks.append(ResearchTask(
                task_type=ntype,
                tool_name="search_hotel",
                args={"city": destination, "nearby": anchor},
                reason=reason or f"住宿应靠近核心活动区 {anchor}",
                priority=3,
                reuse_key=f"hotel:{destination}:nearby:{anchor}",
            ))
        elif ntype == "poi_detail":
            tasks.append(ResearchTask(
                task_type=ntype,
                tool_name="search_poi",
                args={"destination": destination, "category": "cultural", "context": item},
                reason=reason or f"核实 {item or destination} POI 信息",
                priority=5,
                reuse_key=f"poi:{destination}:{item}",
            ))
        elif ntype == "transport":
            origin = need.get("from", "")
            to = need.get("to", destination)
            tasks.append(ResearchTask(
                task_type=ntype,
                tool_name="search_train",
                args={"from_station": origin, "to_station": to, "date": today},
                reason=reason or f"核实 {origin}->{to} 交通",
                priority=2,
                reuse_key=f"transport:train:{origin}->{to}:{today}",
            ))

    return ResearchPlan(tasks=_dedupe_tasks(tasks))


def _hotel_anchor_from_item(item: str, destination: str) -> str:
    value = item.strip()
    for token in (
        destination, "附近", "周边", "旁边", "酒店", "住宿", "宾馆", "民宿",
        "推荐", "查询", "查找", "核实", "价格", "评分", "位置", "目的地",
    ):
        value = value.replace(token, "")
    value = value.strip(" ：:，,。()（）[]【】")
    return "" if value in {"", "市区", "城区", "当地"} else value


def _dedupe_tasks(tasks: list[ResearchTask]) -> list[ResearchTask]:
    seen = set()
    result = []
    for task in sorted(tasks, key=lambda t: t.priority):
        key = task.reuse_key or f"{task.tool_name}:{task.args}"
        if key in seen:
            continue
        seen.add(key)
        result.append(task)
    return result
