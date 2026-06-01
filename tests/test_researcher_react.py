from datetime import date

from travel_planning_agent.agent.researcher import ResearcherAgent
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.types import AgentRequest, Constraints, Traveler


class FinalOnlyLLM:
    def generate(self, system_prompt, user_message, tools=None):
        return LLMResult(
            success=True,
            text=(
                '{"rationale_summary":"Enough known data.",'
                '"final":{"findings":[{"category":"poi","title":"玄武湖",'
                '"detail":"适合慢游","source":"model"}],"covered_items":["玄武湖"]}}'
            ),
            tokens_used=9,
        )


def test_researcher_react_mode_returns_evidence(monkeypatch):
    agent = ResearcherAgent(FinalOnlyLLM())
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        interests=["玄武湖"],
    )

    response = agent.handle(
        AgentRequest(
            request_id="req_react",
            agent="researcher",
            context={},
            params={
                "mode": "react_research",
                "constraints": constraints,
                "research_needs": [{"type": "poi_detail", "item": "玄武湖"}],
            },
        )
    )

    assert response.status == "success"
    assert response.data["react"]["status"] == "success"
    assert response.data["evidence"][0]["claim"] == "玄武湖: 适合慢游"
    assert response.tokens_used == 9
