import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.core.chat_service import ChatService, format_days_text
from travel_planning_agent.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["对话规划"])


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    type: str
    content: str
    trip_id: Optional[str] = None
    plan_summary: Optional[dict] = None
    session_id: Optional[str] = None
    plan: Optional[dict] = None


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: DBSession = Depends(get_db)):
    service = ChatService(db=db)
    result = service.handle_message(message=req.message, session_id=req.session_id)
    return ChatResponse(
        type=result.type,
        content=result.content,
        trip_id=result.trip_id,
        plan_summary=result.plan_summary,
        session_id=result.session_id,
        plan=result.plan,
    )


def _format_days_text(state) -> str:
    return format_days_text(state)
