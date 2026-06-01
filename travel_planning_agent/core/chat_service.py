import logging
import uuid
from typing import Optional

from travel_planning_agent.config import settings as _settings
from travel_planning_agent.core.chat_revision_service import ChatRevisionService
from travel_planning_agent.core.chat_session_store import ChatSessionStore
from travel_planning_agent.core.chat_runtime_service import ChatRuntimeService
from travel_planning_agent.core.chat_types import ChatServiceResult
from travel_planning_agent.core.personalization import build_explanation_cards
from travel_planning_agent.core.plan_revision import (
    format_plan_data_days_text,
    format_plan_data_summary,
)
from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent
from travel_planning_agent.core.tracing import (
    clear_trace_context,
    create_trace_id,
    record_trace_event,
    set_trace_context,
)
from travel_planning_agent.types import AgentRequest, SegmentType

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        db,
        *,
        session_store: ChatSessionStore | None = None,
        llm_factory=None,
        intake_agent_factory=None,
        revision_service_factory=None,
        runtime_service_factory=None,
    ):
        self.db = db
        self.session_store = session_store or ChatSessionStore(db)
        self.llm_factory = llm_factory
        self.intake_agent_factory = intake_agent_factory
        self.revision_service_factory = revision_service_factory or (
            lambda inner_db, store: ChatRevisionService(inner_db, store)
        )
        self.runtime_service_factory = runtime_service_factory or (
            lambda inner_db, store: ChatRuntimeService(inner_db, store)
        )

    def handle_message(self, message: str, session_id: Optional[str] = None) -> ChatServiceResult:
        from travel_planning_agent.agent.intake import IntakeAgent
        from travel_planning_agent.llm import create_llm_client

        session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        trace_id = create_trace_id()
        set_trace_context(trace_id, session_id=session_id)
        record_trace_event(
            "user_input",
            "chat",
            {"message": message, "session_id": session_id},
            trace_id=trace_id,
            session_id=session_id,
        )
        context = self.session_store.load_context(session_id)
        self.session_store.remember_trace_id(context, trace_id)
        extracted = context.get("extracted", {})
        self.session_store.touch_session(session_id, extracted.get("destination"))

        logger.info("Chat session=%s extracted=%s", session_id, extracted)

        try:
            revision_intent = None
            trip_id = context.get("last_trip_id")
            if trip_id:
                from travel_planning_agent.db.models import PlanVersion

                active = (
                    self.db.query(PlanVersion)
                    .filter(PlanVersion.trip_id == trip_id, PlanVersion.is_active == True)  # noqa: E712
                    .order_by(PlanVersion.version.desc())
                    .first()
                )
                if active and active.plan_data:
                    llm_factory = self.llm_factory or create_llm_client
                    llm = llm_factory(mock=not bool(_settings.llm_api_key))
                    revision_intent = classify_revision_intent(llm, message, active.plan_data, context)

            if revision_intent and revision_intent.get("is_revision"):
                revised = self.revision_service_factory(self.db, self.session_store).try_apply(
                    session_id,
                    message,
                    context,
                    revision_intent,
                )
                if revised:
                    self.session_store.append_message(context, "assistant", revised.content, "plan")
                    context["last_response"] = {
                        "type": "plan",
                        "content": revised.content,
                        "trip_id": revised.trip_id,
                        "plan": revised.plan,
                    }
                    self.session_store.save_context(session_id, context)
                    record_trace_event(
                        "revision_applied",
                        "revision",
                        {
                            "message": message,
                            "trip_id": revised.trip_id,
                            "plan_summary": revised.plan_summary,
                        },
                        trace_id=trace_id,
                        session_id=session_id,
                        trip_id=revised.trip_id,
                    )
                    return revised

            llm_factory = self.llm_factory or create_llm_client
            llm = llm_factory(mock=not bool(_settings.llm_api_key))
            intake_factory = self.intake_agent_factory or (lambda llm_client: IntakeAgent(llm_client))
            intake = intake_factory(llm)

            intake_request = AgentRequest(
                request_id=f"intake_{uuid.uuid4().hex[:8]}",
                agent="intake",
                context={},
                params={"message": message, "extracted": extracted},
            )
            intake_resp = intake.handle(intake_request)
            record_trace_event(
                "intake_result",
                "intake",
                {
                    "status": intake_resp.status,
                    "complete": bool((intake_resp.data or {}).get("complete")),
                    "data": intake_resp.data,
                    "error": intake_resp.error,
                    "tokens_used": intake_resp.tokens_used,
                },
                trace_id=trace_id,
                session_id=session_id,
            )

            if intake_resp.status == "failed":
                record_trace_event(
                    "error",
                    "intake",
                    {"error": str(intake_resp.error)},
                    trace_id=trace_id,
                    session_id=session_id,
                )
                return ChatServiceResult(
                    type="error",
                    content=str(intake_resp.error),
                    session_id=session_id,
                )

            data = intake_resp.data or {}
            return self.runtime_service_factory(self.db, self.session_store).handle_intake_result(
                session_id=session_id,
                message=message,
                context=context,
                data=data,
                trace_id=trace_id,
                llm=llm,
            )
        finally:
            clear_trace_context()


def format_plan_summary(state) -> dict:
    total_cost = 0
    activity_count = 0
    for day in state.days:
        for seg in day.segments:
            if seg.estimated_cost:
                total_cost += seg.estimated_cost.amount
            if seg.type.value == "activity":
                activity_count += 1
    return {
        "total_cost": total_cost,
        "activity_count": activity_count,
        "day_count": len(state.days),
        "destination": state.constraints.destination if state.constraints else "",
    }


def format_days_text(state) -> str:
    cat_map = {
        SegmentType.TRANSPORT: "路程",
        SegmentType.ACTIVITY: "游玩",
        SegmentType.MEAL: "用餐",
        SegmentType.ACCOMMODATION: "住宿",
    }
    explanation_by_segment = {
        card["segment_id"]: card["sections"]
        for card in build_explanation_cards(plan_dict_from_state(state))
    }
    lines = []

    for day in state.days:
        lines.append(f"📮 Day {day.day_number} - {day.theme}")
        if day.day_note:
            lines.append(f"   {day.day_note}")
        prev_type = None
        for seg in day.segments:
            if seg.type != prev_type:
                cat_name = cat_map.get(seg.type)
                if cat_name:
                    lines.append(f"  --- {cat_name} ---")
                prev_type = seg.type
            time_str = f"{seg.start_time or ''}-{seg.end_time or ''}"
            cost = f" ¥{seg.estimated_cost.amount:,.0f}" if seg.estimated_cost and seg.estimated_cost.amount else ""
            note = f" {seg.note}" if seg.note else ""
            lines.append(f"   {time_str} {seg.title}{cost}{note}")
            sections = explanation_by_segment.get(seg.segment_id) or explanation_by_segment.get(seg.title)
            if sections:
                lines.append(f"      为什么推荐：{sections.get('为什么推荐', '')}")
                lines.append(f"      注意事项：{sections.get('注意事项', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def plan_dict_from_state(state) -> dict:
    return {
        "profile": getattr(getattr(state, "constraints", None), "pace", None) or "classic",
        "days": [
            {
                "day_number": day.day_number,
                "day_note": day.day_note,
                "segments": [
                    {
                        "segment_id": seg.segment_id,
                        "type": seg.type.value if hasattr(seg.type, "value") else seg.type,
                        "title": seg.title,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "tags": list(seg.tags or []),
                        "note": seg.note,
                    }
                    for seg in day.segments
                ],
            }
            for day in state.days
        ],
    }
