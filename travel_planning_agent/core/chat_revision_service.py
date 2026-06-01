from travel_planning_agent.config import settings as _settings
from travel_planning_agent.core.chat_types import ChatServiceResult
from travel_planning_agent.core.context_ledger import record_revision_note
from travel_planning_agent.core.plan_revision import (
    apply_change_request_to_plan,
    format_plan_data_days_text,
    format_plan_data_summary,
)
from travel_planning_agent.core.plan_schema import format_plan_view


class ChatRevisionService:
    def __init__(self, db, session_store):
        self.db = db
        self.session_store = session_store

    def _build_scope_result(self, session_id: str, trip_id: str, parsed_scope: dict):
        if parsed_scope.get("clarification_needed"):
            return ChatServiceResult(
                type="question",
                content=parsed_scope["clarification_question"],
                trip_id=trip_id,
                session_id=session_id,
            )
        if not parsed_scope.get("matched"):
            return None
        return False

    def _build_strategy_result(self, session_id: str, trip_id: str, strategy_result: dict):
        if strategy_result.get("strategy") == "clarify":
            return ChatServiceResult(
                type="question",
                content=strategy_result["clarification_question"],
                trip_id=trip_id,
                session_id=session_id,
            )
        if strategy_result.get("strategy") == "replan_impacted":
            return ChatServiceResult(
                type="question",
                content="这次修改会影响多天安排，我需要先确认具体范围。",
                trip_id=trip_id,
                session_id=session_id,
            )
        return False

    def try_apply(self, session_id: str, message: str, context: dict, revision_intent: dict):
        from travel_planning_agent.agent.revision import RevisionAgent
        from travel_planning_agent.db.models import PlanVersion, Trip
        from travel_planning_agent.llm import create_llm_client

        trip_id = context.get("last_trip_id")
        trip = self.db.query(Trip).filter(Trip.trip_id == trip_id).first()
        if not trip:
            return None

        active = (
            self.db.query(PlanVersion)
            .filter(PlanVersion.trip_id == trip_id, PlanVersion.is_active == True)  # noqa: E712
            .order_by(PlanVersion.version.desc())
            .first()
        )
        if not active:
            return None

        plan_data = dict(active.plan_data or {})
        if revision_intent.get("classification_failed"):
            return ChatServiceResult(
                type="question",
                content="我不太确定你想怎么改，可以具体说一下吗？比如改哪一天、哪个景点？",
                trip_id=trip_id,
                session_id=session_id,
            )
        if revision_intent.get("clarification_needed"):
            return ChatServiceResult(
                type="question",
                content=revision_intent.get("clarification_question", "你想具体怎么修改？"),
                trip_id=trip_id,
                session_id=session_id,
            )

        intent_type = revision_intent.get("intent_type")
        scope_type = revision_intent.get("scope_type")
        if not (
            intent_type in {"lighten_day", "remove_segment", "return_time_change"}
            and scope_type in {"segment", "day_module", "day"}
        ):
            return ChatServiceResult(
                type="question",
                content="你想改哪一天，还是改某个具体景点/时段？",
                trip_id=trip_id,
                session_id=session_id,
            )

        parsed_scope = {
            "matched": True,
            "target_day": revision_intent.get("target_day"),
            "target_module": revision_intent.get("target_module"),
            "target_segment": revision_intent.get("target_segment"),
            "change_type": intent_type,
            "scope_type": scope_type,
            "impact_level": revision_intent.get("impact_level"),
            "clarification_needed": False,
            "clarification_question": "",
        }
        if intent_type == "return_time_change":
            from travel_planning_agent.core.plan_revision import return_window_from_message

            return_start, return_end = return_window_from_message(message)
            parsed_scope["return_start"] = return_start
            parsed_scope["return_end"] = return_end

        llm = create_llm_client(mock=not bool(_settings.llm_api_key))
        changed = apply_change_request_to_plan(
            plan_data,
            trip,
            message,
            context,
            RevisionAgent(llm),
            parsed_scope=parsed_scope,
        )
        if not changed:
            return None

        self.db.query(PlanVersion).filter(PlanVersion.trip_id == trip_id).update({"is_active": False})
        new_version = (active.version or 0) + 1
        new_plan = PlanVersion(
            trip_id=trip_id,
            version=new_version,
            plan_data=plan_data,
            verification={"overall_pass": True, "warnings": [{"detail": "用户做了局部行程修订"}]},
            diff_previous={"reason": message, "type": "change_request_revision"},
            is_active=True,
        )
        trip.days = len(plan_data.get("days", [])) or trip.days
        trip.status = "completed"
        self.db.add(new_plan)

        context["last_plan_version"] = new_version
        context.setdefault("extracted", {})["days"] = trip.days
        record_revision_note(
            context,
            message=message,
            trace_id=context.get("last_trace_id"),
            trip_id=trip_id,
            plan_version=new_version,
        )
        self.session_store.append_message(context, "user", message)
        self.db.commit()

        summary = format_plan_data_summary(plan_data, trip)
        plan_view = format_plan_view(plan_data, trip=trip, summary=summary)
        content = (
            "已根据你的要求重新规划了受影响的行程，并保留未受影响的部分。\n\n"
            f"{format_plan_data_days_text(plan_data)}"
        )
        return ChatServiceResult(
            type="plan_result",
            content=content,
            trip_id=trip_id,
            plan_summary=summary,
            session_id=session_id,
            plan=plan_view,
        )
