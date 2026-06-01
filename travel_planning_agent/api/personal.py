from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.core.personalization import (
    build_decision_card,
    build_execution_checklist,
    build_explanation_cards,
)
from travel_planning_agent.db.models import PlanVersion, Trip
from travel_planning_agent.db.session import get_db

router = APIRouter(prefix="/api/trips", tags=["个人自由行"])


@router.get("/{trip_id}/personal")
def get_personal_trip_view(trip_id: str, db: DBSession = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(404, "行程不存在")
    plan = db.query(PlanVersion).filter(
        PlanVersion.trip_id == trip_id,
        PlanVersion.is_active == True,  # noqa: E712
    ).order_by(PlanVersion.version.desc()).first()
    if not plan:
        raise HTTPException(404, "当前行程还没有可用方案")
    trip_data = {
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat(),
        "budget": trip.budget,
        "pace": trip.pace,
    }
    profile = _personal_profile_from_plan(plan.plan_data)
    return {
        "decision_card": build_decision_card(profile, plan.plan_data),
        "explanations": build_explanation_cards(plan.plan_data),
        "checklist": build_execution_checklist(trip_data, plan.plan_data),
        "revision_suggestions": [
            "这一天太累了，帮我轻松一点",
            "下雨的话，把户外项目换成室内",
            "预算降一点，但保留必去景点",
            "保留酒店和交通，只改景点",
        ],
    }


def _personal_profile_from_plan(plan_data: dict) -> str:
    profile = (plan_data or {}).get("profile") or "classic"
    return "classic" if profile == "default" else str(profile)
