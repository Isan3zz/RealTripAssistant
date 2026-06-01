import uuid
from dataclasses import asdict
from typing import Optional

from travel_planning_agent.types import PlanState, TripSpec


class PlanPersistenceService:
    def __init__(self, db):
        self.db = db

    def ensure_trip(self, spec: TripSpec, session_id: Optional[str], trip_id: Optional[str]) -> str:
        from travel_planning_agent.db.models import User, Session as TripSession, Trip

        if trip_id:
            trip = self.db.query(Trip).filter(Trip.trip_id == trip_id).first()
            if trip:
                return trip.trip_id

        user = self.db.query(User).filter(User.email == "default@realtrip.ai").first()
        if not user:
            user = User(email="default@realtrip.ai", password_hash="", display_name="默认用户")
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

        session = None
        if session_id:
            session = self.db.query(TripSession).filter(TripSession.session_id == session_id).first()
        if not session:
            session = TripSession(session_id=session_id or str(uuid.uuid4()), user_id=user.user_id, title=spec.destination)
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        trip = Trip(
            session_id=session.session_id,
            user_id=user.user_id,
            destination=spec.destination,
            start_date=spec.start_date,
            days=spec.days,
            traveler_count=len(spec.travelers),
            elderly_count=sum(1 for t in spec.travelers if t.age_group == "elderly"),
            child_count=sum(1 for t in spec.travelers if t.age_group == "child"),
            budget=spec.budget,
            pace=spec.pace,
            interests=spec.must_have,
        )
        self.db.add(trip)
        self.db.commit()
        self.db.refresh(trip)
        return trip.trip_id

    def create_plan_run(
        self,
        run_id: str,
        trip_id: str,
        session_id: Optional[str],
        profile: str,
        spec: TripSpec,
        events: list[dict],
    ) -> None:
        from travel_planning_agent.db.models import PlanRunRecord

        rec = PlanRunRecord(
            run_id=run_id,
            trip_id=trip_id,
            session_id=session_id,
            status="started",
            profile=profile,
            input_spec=_jsonable_spec(spec),
            events=list(events),
        )
        self.db.add(rec)
        self.db.commit()

    def finish_plan_run(self, run_id: str, status: str, events: list[dict], version: Optional[int]) -> None:
        from travel_planning_agent.db.models import PlanRunRecord

        rec = self.db.query(PlanRunRecord).filter(PlanRunRecord.run_id == run_id).first()
        if rec:
            rec.status = status
            rec.events = list(events)
            rec.final_plan_version = version
            self.db.commit()

    def persist_plan(
        self,
        trip_id: str,
        plan_data: dict,
        verification: dict,
        activate: bool = True,
        trip_status: str = "completed",
    ) -> int:
        from travel_planning_agent.db.models import Trip, PlanVersion

        version_count = self.db.query(PlanVersion).filter(PlanVersion.trip_id == trip_id).count()
        version = version_count + 1
        if activate:
            self.db.query(PlanVersion).filter(PlanVersion.trip_id == trip_id).update({"is_active": False})
        pv = PlanVersion(
            trip_id=trip_id,
            version=version,
            plan_data=plan_data,
            verification=verification,
            is_active=activate,
        )
        trip = self.db.query(Trip).filter(Trip.trip_id == trip_id).first()
        if trip:
            trip.status = trip_status
        self.db.add(pv)
        self.db.commit()
        return version

    def persist_evidence(self, trip_id: str, state: PlanState) -> None:
        from travel_planning_agent.db.models import EvidenceRecord

        for ev in state.evidence.values():
            existing = self.db.query(EvidenceRecord).filter(EvidenceRecord.evidence_id == ev.evidence_id).first()
            if existing:
                continue
            self.db.add(EvidenceRecord(
                evidence_id=ev.evidence_id,
                trip_id=trip_id,
                source=ev.source,
                source_type=ev.source_type,
                confidence=ev.confidence,
                claim=ev.claim,
                payload={
                    "url": ev.url,
                    "url_reachable": ev.url_reachable,
                    "url_checked_at": ev.url_checked_at,
                },
            ))
        self.db.commit()


def _jsonable_spec(spec: TripSpec) -> dict:
    data = asdict(spec)
    data["start_date"] = spec.start_date.isoformat()
    return data
