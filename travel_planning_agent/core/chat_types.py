from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatServiceResult:
    type: str
    content: str
    trip_id: Optional[str] = None
    plan_summary: Optional[dict] = None
    session_id: Optional[str] = None
    plan: Optional[dict] = None
