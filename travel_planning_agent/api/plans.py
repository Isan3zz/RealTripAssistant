"""
api/plans.py — 方案生成、对比、选择 API
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.db.session import get_db
from travel_planning_agent.db.models import Trip, PlanVersion
from travel_planning_agent.config import settings

router = APIRouter(prefix="/api/trips", tags=["方案管理"])


class PlanRequest(BaseModel):
    mode: str = "generate"


class CompareRequest(BaseModel):
    count: int = 2
    dimensions: list[str] = ["budget", "pace", "diversity"]


class CostEstimateResponse(BaseModel):
    plan_count: int
    estimated_tokens: int
    estimated_usd: float


class SelectPlanRequest(BaseModel):
    plan_id: str


@router.post("/{trip_id}/plan")
def trigger_plan(trip_id: str, req: PlanRequest, db: DBSession = Depends(get_db)):
    """触发规划（走统一 PlanningRuntime）。"""
    t = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not t:
        raise HTTPException(404, "行程不存在")

    from travel_planning_agent.core.planning_runtime import PlanningRuntime, spec_from_trip
    runtime = PlanningRuntime(db=db)
    result = runtime.run(spec_from_trip(t), session_id=t.session_id, trip_id=trip_id, profile=req.mode if req.mode != "generate" else "default")
    active = db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id,
        PlanVersion.is_active == True,  # noqa: E712
    ).order_by(PlanVersion.version.desc()).first()

    return {
        "plan_id": active.plan_id if active else None,
        "version": result["plan_version"],
        "status": "completed",
        "trip_id": trip_id,
        "run_id": result["run_id"],
        "verification": result["verification"],
    }


@router.post("/{trip_id}/compare/cost-estimate", response_model=CostEstimateResponse)
def estimate_compare_cost(trip_id: str, req: CompareRequest, db: DBSession = Depends(get_db)):
    """预估方案对比的 token 消耗。"""
    from travel_planning_agent.core.plan_comparison import PlanComparisonService
    from travel_planning_agent.llm import MockLLMClient

    llm = MockLLMClient()
    service = PlanComparisonService(llm)
    estimate = service.estimate_cost(req.count)
    return CostEstimateResponse(**estimate)


@router.post("/{trip_id}/compare")
def compare_plans(trip_id: str, req: CompareRequest, db: DBSession = Depends(get_db)):
    """生成多个候选方案进行比较。"""
    t = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not t:
        raise HTTPException(404, "行程不存在")

    from travel_planning_agent.core.plan_comparison import PlanComparisonService
    from travel_planning_agent.core.planning_runtime import spec_from_trip

    service = PlanComparisonService(db=db)
    result = service.run_comparison(spec_from_trip(t), trip_id=trip_id, count=req.count, dimensions=req.dimensions)

    return {
        "comparison_id": f"cmp_{trip_id[:8]}",
        "status": "ready",
        "plans": result["plans"],
        "comparison": result["comparison"],
    }


@router.get("/{trip_id}/plans")
def list_plans(trip_id: str, db: DBSession = Depends(get_db)):
    """列出行程的所有方案版本。"""
    plans = db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id
    ).order_by(PlanVersion.version.desc()).all()

    return [
        {
            "plan_id": p.plan_id,
            "version": p.version,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat(),
            "summary": _summarize_plan(p.plan_data),
            "plan_data": p.plan_data,
            "verification": p.verification,
        }
        for p in plans
    ]


@router.get("/{trip_id}/plans/{plan_id}")
def get_plan(trip_id: str, plan_id: str, db: DBSession = Depends(get_db)):
    """获取方案详情。"""
    p = db.query(PlanVersion).filter(
        PlanVersion.plan_id == plan_id,
        PlanVersion.trip_id == trip_id,
    ).first()
    if not p:
        raise HTTPException(404, "方案不存在")
    return {
        "plan_id": p.plan_id,
        "version": p.version,
        "plan_data": p.plan_data,
        "verification": p.verification,
        "diff_previous": p.diff_previous,
        "is_active": p.is_active,
    }


@router.post("/{trip_id}/select-plan")
def select_plan(trip_id: str, req: SelectPlanRequest, db: DBSession = Depends(get_db)):
    """选择最终方案。"""
    p = db.query(PlanVersion).filter(
        PlanVersion.plan_id == req.plan_id,
        PlanVersion.trip_id == trip_id,
    ).first()
    if not p:
        raise HTTPException(404, "方案不存在")
    db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id
    ).update({"is_active": False})
    p.is_active = True
    db.commit()
    return {"status": "selected", "plan_id": req.plan_id}


def _summarize_plan(data: dict) -> dict:
    """提取方案摘要。"""
    days = data.get("days", [])
    total_cost = 0
    activities = 0
    for d in days:
        for s in d.get("segments", []):
            cost = s.get("estimated_cost", {})
            if cost:
                total_cost += cost.get("amount", 0) or 0
            if s.get("type") == "activity":
                activities += 1
    return {
        "days": len(days),
        "total_cost": total_cost,
        "activities": activities,
    }
