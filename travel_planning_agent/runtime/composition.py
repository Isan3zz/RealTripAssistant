def build_planning_supervisor(llm_client, use_react_research: bool = False):
    from travel_planning_agent.agent.planner import PlannerAgent
    from travel_planning_agent.agent.researcher import ResearcherAgent
    from travel_planning_agent.agent.supervisor import SupervisorAgent
    from travel_planning_agent.agent.verifier import VerifierAgent

    researcher = ResearcherAgent(llm_client)
    researcher.use_react_research = use_react_research
    return SupervisorAgent(
        llm_client,
        {
            "researcher": researcher,
            "planner": PlannerAgent(llm_client),
            "verifier": VerifierAgent(llm_client),
        },
    )
