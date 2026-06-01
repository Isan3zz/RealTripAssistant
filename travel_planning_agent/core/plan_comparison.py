"""
core/plan_comparison.py — comparison service backed by PlanningRuntime.
"""

from typing import Optional

from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.types import TripSpec
from travel_planning_agent.core.planning_runtime import PlanningRuntime


PLAN_PROFILES = [
    {"id": "relaxed", "label": "轻松慢游", "description": "降低每日活动密度，保留休息和弹性时间"},
    {"id": "classic", "label": "经典初游", "description": "覆盖目的地代表性景点，适合第一次到访"},
    {"id": "food", "label": "美食深度", "description": "围绕本地餐饮和街区体验组织行程"},
    {"id": "economy", "label": "省钱优先", "description": "优先控制总预算，减少高价项目"},
]


class PlanComparisonService:
    def __init__(self, llm_client=None, db: Optional[DBSession] = None):
        self.runtime = PlanningRuntime(db=db, llm_client=llm_client)

    def estimate_cost(self, plan_count: int) -> dict:
        shared = 8000
        per_plan = 12000
        total = shared + per_plan * plan_count
        return {
            "plan_count": plan_count,
            "estimated_tokens": total,
            "estimated_usd": round(total * 0.000006, 4),
        }

    def run_comparison(
        self,
        base_spec: TripSpec,
        trip_id: Optional[str] = None,
        count: int = 2,
        dimensions: list[str] = None,
    ) -> dict:
        dimensions = dimensions or ["budget", "pace", "diversity"]
        profiles = PLAN_PROFILES[:max(1, min(count, len(PLAN_PROFILES)))]

        plans = []
        for profile in profiles:
            result = self.runtime.run(
                base_spec,
                trip_id=trip_id,
                profile=profile["id"],
                persist=bool(trip_id),
                activate_plan=False,
            )
            plan = result["plan_data"]
            summary = _summarize(plan)
            plans.append({
                "run_id": result["run_id"],
                "label": profile["label"],
                "profile_id": profile["id"],
                "description": profile["description"],
                "version": result.get("plan_version"),
                "summary": summary,
                "verification": result["verification"],
                "days": plan.get("days", []),
            })

        return {
            "plans": plans,
            "comparison": {
                "dimensions": dimensions,
                "diff_matrix": _build_diff_matrix(plans, dimensions),
            },
        }


def _summarize(plan: dict) -> dict:
    days = plan.get("days", [])
    total_cost = 0
    activities = 0
    for day in days:
        for seg in day.get("segments", []):
            cost = seg.get("estimated_cost") or {}
            total_cost += cost.get("amount", 0) or 0
            if seg.get("type") == "activity":
                activities += 1
    return {
        "days": len(days),
        "total_cost": total_cost,
        "activity_count": activities,
        "avg_daily_cost": round(total_cost / len(days), 0) if days else 0,
    }


def _build_diff_matrix(plans: list[dict], dimensions: list[str]) -> list[dict]:
    rows = []
    if "budget" in dimensions:
        rows.append({"dimension": "总花费", "values": [f"¥{p['summary']['total_cost']:,.0f}" for p in plans]})
    if "pace" in dimensions:
        rows.append({"dimension": "方案类型", "values": [p["label"] for p in plans]})
    if "diversity" in dimensions:
        rows.append({"dimension": "活动数", "values": [str(p["summary"]["activity_count"]) for p in plans]})
    rows.append({"dimension": "天数", "values": [str(p["summary"]["days"]) for p in plans]})
    rows.append({"dimension": "日均花费", "values": [f"¥{p['summary']['avg_daily_cost']:,.0f}" for p in plans]})
    return rows
