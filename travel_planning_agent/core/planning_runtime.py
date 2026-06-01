"""
core/planning_runtime.py - unified product planning runtime.

Single entrypoint for chat planning, trip planning, and comparison profiles.
"""

from typing import Optional

from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.config import settings
from travel_planning_agent.core.plan_run_service import (
    PlanRunService,
    apply_profile,
    ensure_required_plan_content,
    normalize_final_day_departure,
    plan_data_from_state,
    record_event,
    verification_to_dict,
    verify_whole_plan,
)
from travel_planning_agent.types import TripSpec, Traveler


class PlanningRuntime:
    def __init__(self, db: Optional[DBSession] = None, llm_client=None):
        self.db = db
        if llm_client is None:
            from travel_planning_agent.llm import create_llm_client

            llm_client = create_llm_client(mock=not bool(settings.llm_api_key))
        self.llm = llm_client

    def run(
        self,
        spec: TripSpec,
        session_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        profile: str = "default",
        persist: bool = True,
        activate_plan: bool = True,
        use_react_research: bool = False,
        use_execution_plan: bool = True,
    ) -> dict:
        service = PlanRunService(self.db, self.llm)
        return service.run(
            spec,
            session_id=session_id,
            trip_id=trip_id,
            profile=profile,
            persist=persist,
            activate_plan=activate_plan,
            use_react_research=use_react_research,
            use_execution_plan=use_execution_plan,
        )


def spec_from_trip(trip) -> TripSpec:
    travelers = [Traveler(age_group="adult")] * max((trip.traveler_count or 1) - (trip.elderly_count or 0) - (trip.child_count or 0), 0)
    travelers.extend(Traveler(age_group="elderly") for _ in range(trip.elderly_count or 0))
    travelers.extend(Traveler(age_group="child") for _ in range(trip.child_count or 0))
    if not travelers:
        travelers = [Traveler(age_group="adult")]
    return TripSpec(
        origin="",
        destination=trip.destination,
        start_date=trip.start_date,
        days=trip.days,
        travelers=travelers,
        budget=trip.budget or 0,
        pace=trip.pace or "moderate",
        must_have=list(trip.interests or []),
    )
