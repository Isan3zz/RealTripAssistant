from datetime import date

from travel_planning_agent.agent.intake import IntakeAgent
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.types import AgentRequest


class FakeDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 16)


class FakeLLM:
    def generate(self, system_prompt: str, user_message: str, tools=None):
        return LLMResult(
            success=True,
            data={
                "complete": False,
                "question": "请问您的出发日期是哪天？",
                "extracted": {
                    "destination": "南京",
                    "start_date": None,
                    "days": 2,
                    "origin": "杭州",
                    "budget": 2000,
                    "transport_mode": "高铁",
                    "interests": ["玄武湖"],
                },
            },
        )


def test_intake_resolves_tomorrow_before_asking_for_date(monkeypatch):
    monkeypatch.setattr("travel_planning_agent.agent.intake.date", FakeDate)
    agent = IntakeAgent(FakeLLM())

    resp = agent.handle(
        AgentRequest(
            request_id="intake_tomorrow",
            agent="intake",
            context={},
            params={
                "message": "明天我从杭州去南京玩两天，坐高铁去吧，然后我想看玄武湖，预算2000",
                "extracted": {},
            },
        )
    )

    assert resp.status == "success"
    assert resp.data["complete"] is True
    assert resp.data["constraints"].start_date.isoformat() == "2026-05-17"
    assert resp.data["constraints"].destination == "南京"
    assert resp.data["constraints"].origin == "杭州"
