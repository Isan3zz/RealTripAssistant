import logging
from datetime import datetime

from travel_planning_agent.core.chat_questioning import (
    normalize_followup_question,
    normalize_known_field_question,
)
from travel_planning_agent.core.chat_types import ChatServiceResult
from travel_planning_agent.core.context_ledger import (
    record_active_constraints,
    record_initial_constraints,
)
from travel_planning_agent.core.plan_schema import format_plan_view
from travel_planning_agent.core.tracing import record_trace_event, set_trace_context

logger = logging.getLogger(__name__)


class ChatRuntimeService:
    def __init__(self, db, session_store):
        self.db = db
        self.session_store = session_store

    def handle_intake_result(self, *, session_id: str, message: str, context: dict, data: dict, trace_id: str, llm):
        if not data.get("complete"):
            return self._handle_incomplete_intake(session_id, message, context, data, trace_id)
        return self._handle_complete_intake(session_id, message, context, data, trace_id, llm)

    def _handle_incomplete_intake(self, session_id: str, message: str, context: dict, data: dict, trace_id: str):
        new_extracted = data.get("extracted", {})
        context["extracted"] = dict(new_extracted)
        record_active_constraints(context, new_extracted, message, trace_id)
        self.session_store.touch_session(session_id, new_extracted.get("destination"))
        self.session_store.append_message(context, "user", message)

        known = []
        labels = {
            "destination": "目的地",
            "start_date": "日期",
            "days": "天数",
            "origin": "出发城市",
            "budget": "预算",
            "travelers": "人员",
            "pace": "节奏",
            "transport_mode": "交通偏好",
            "interests": "必去项",
        }
        for key, value in new_extracted.items():
            if key == "extracted" or not value:
                continue
            known.append(f"{labels.get(key, key)}：{value}")

        question = data.get("question", "请提供更多信息")
        question = normalize_known_field_question(question, new_extracted)
        question = normalize_followup_question(question)
        content = f"已了解：{'；'.join(known)}\n\n{question}" if known else question
        logger.info("Chat response: %s", content[:100])

        self.session_store.append_message(context, "assistant", content, "question")
        context["last_response"] = {"type": "question", "content": content}
        self.session_store.save_context(session_id, context)
        record_trace_event(
            "followup_question",
            "chat",
            {"question": question, "known": known},
            trace_id=trace_id,
            session_id=session_id,
        )
        return ChatServiceResult(type="question", content=content, session_id=session_id)

    def _handle_complete_intake(self, session_id: str, message: str, context: dict, data: dict, trace_id: str, llm):
        from travel_planning_agent.core.chat_service import format_days_text, format_plan_summary
        from travel_planning_agent.core.planning_runtime import PlanningRuntime
        from travel_planning_agent.core.session_naming import generate_session_title
        from travel_planning_agent.types import TripSpec

        constraints = data.get("constraints")
        try:
            record_initial_constraints(context, constraints, message, trace_id)
            record_active_constraints(context, constraints, message, trace_id)
            spec = TripSpec.from_constraints(constraints)
            session_title = generate_session_title(llm, constraints, message)
            self.session_store.set_session_title(session_id, session_title)
            runtime = PlanningRuntime(db=self.db, llm_client=llm)
            result = runtime.run(spec, session_id=session_id)
            state = result["state"]
            set_trace_context(
                trace_id,
                session_id=session_id,
                trip_id=result["trip_id"],
                run_id=result["run_id"],
            )

            context.update(
                {
                    "extracted": {
                        "destination": constraints.destination,
                        "start_date": str(constraints.start_date),
                        "days": constraints.days,
                        "origin": constraints.origin or "",
                        "travelers": self._format_travelers(constraints),
                        "budget": constraints.budget,
                        "pace": constraints.pace,
                        "preferences_detail": constraints.preferences_detail or "",
                        "transport_mode": constraints.transport_mode or "",
                        "interests": list(constraints.interests or []),
                    },
                    "last_trip_id": result["trip_id"],
                    "last_run_id": result["run_id"],
                    "last_plan_version": result["plan_version"],
                    "session_title": session_title,
                }
            )
            self.session_store.touch_session(session_id, constraints.destination)
            self.session_store.append_message(context, "user", message)

            summary = format_plan_summary(state)
            days_text = format_days_text(state)

            plan_view = format_plan_view(result["plan_data"], trip=state.constraints, summary=summary)
            origin_str = f" {state.constraints.origin}→" if state.constraints.origin else ""
            content = (
                f"✅ 行程规划完成！\n\n"
                f"📍{origin_str}{state.constraints.destination} {state.constraints.days}天\n"
                f"💰 预算 ¥{state.constraints.budget:,.0f} | 总花费 ¥{summary['total_cost']:,.0f}\n"
                f"节奏：{state.constraints.pace}\n\n"
                f"{days_text}"
            )

            self.session_store.append_message(context, "assistant", content, "plan")
            context["last_response"] = {
                "type": "plan",
                "content": content,
                "trip_id": state.trip_id,
                "plan": plan_view,
            }
            self.session_store.save_context(session_id, context)

            if message and state is not None:
                state.message_history.insert(
                    0,
                    {
                        "role": "user",
                        "content": message,
                        "timestamp": datetime.now().isoformat(),
                        "msg_type": "user_input",
                    },
                )

            record_trace_event(
                "plan_created",
                "planning",
                {
                    "trip_id": state.trip_id,
                    "run_id": result["run_id"],
                    "plan_version": result["plan_version"],
                    "summary": summary,
                },
                trace_id=trace_id,
                session_id=session_id,
                trip_id=state.trip_id,
                run_id=result["run_id"],
            )
            return ChatServiceResult(
                type="plan_result",
                content=content,
                trip_id=state.trip_id,
                plan_summary=summary,
                session_id=session_id,
                plan=plan_view,
            )
        except Exception as exc:
            logger.error("规划失败: %s", exc)
            record_trace_event(
                "error",
                "planning",
                {"error": str(exc)},
                trace_id=trace_id,
                session_id=session_id,
            )
            return ChatServiceResult(
                type="error",
                content=f"规划失败: {str(exc)}",
                session_id=session_id,
            )

    @staticmethod
    def _format_travelers(constraints) -> str:
        adults = len([t for t in constraints.travelers if t.age_group == "adult"])
        elderly = len([t for t in constraints.travelers if t.age_group == "elderly"])
        children = len([t for t in constraints.travelers if t.age_group == "child"])
        text = f"{adults}位成人"
        if elderly:
            text += f"，{elderly}位老人"
        if children:
            text += f"，{children}位小孩"
        return text
