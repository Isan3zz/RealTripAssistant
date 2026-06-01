class ChatSessionStore:
    def __init__(self, db):
        self.db = db

    def load_context(self, session_id: str) -> dict:
        from travel_planning_agent.db.models import SessionContext

        rec = self.db.query(SessionContext).filter(SessionContext.session_id == session_id).first()
        return dict(rec.context_data or {}) if rec else {}

    def save_context(self, session_id: str, context: dict) -> None:
        from travel_planning_agent.db.models import SessionContext

        rec = self.db.query(SessionContext).filter(SessionContext.session_id == session_id).first()
        if not rec:
            rec = SessionContext(session_id=session_id, context_data=context)
            self.db.add(rec)
        else:
            rec.context_data = context
        self.db.commit()

    def append_message(self, context: dict, role: str, content: str, msg_type: str | None = None) -> None:
        if not content:
            return
        message = {"role": role, "content": content}
        if msg_type:
            message["type"] = msg_type
        messages = context.setdefault("messages", [])
        messages.append(message)
        del messages[:-50]

    def remember_trace_id(self, context: dict, trace_id: str) -> None:
        if not trace_id:
            return
        trace_ids = [item for item in context.get("trace_ids", []) if item != trace_id]
        trace_ids.append(trace_id)
        context["trace_ids"] = trace_ids[-20:]
        context["last_trace_id"] = trace_id

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        from travel_planning_agent.db.models import Session, User

        session = self.db.query(Session).filter(Session.session_id == session_id).first()
        if session:
            if title and (
                not session.title
                or session.title in {"新建行程", "继续上次会话", "Continue previous session"}
            ):
                session.title = title
            self.db.commit()
            return

        user = self.db.query(User).filter(User.email == "default@realtrip.ai").first()
        if not user:
            user = User(email="default@realtrip.ai", password_hash="", display_name="默认用户")
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        self.db.add(Session(session_id=session_id, user_id=user.user_id, title=title or "继续上次会话"))
        self.db.commit()

    def set_session_title(self, session_id: str, title: str | None) -> None:
        if not title:
            return
        from travel_planning_agent.db.models import Session

        session = self.db.query(Session).filter(Session.session_id == session_id).first()
        if not session:
            self.touch_session(session_id, title)
            return
        session.title = title
        self.db.commit()
