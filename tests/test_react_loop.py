import json

from travel_planning_agent.llm import LLMResult
from travel_planning_agent.types import ToolResult
from travel_planning_agent.core.react_loop import parse_react_decision
from travel_planning_agent.core.react_loop import run_react_loop


def test_parse_action_decision():
    decision = parse_react_decision(json.dumps({
        "rationale_summary": "Need weather before choosing activities.",
        "action": {
            "tool": "get_weather_forecast",
            "args": {"city": "南京", "date": "2026-05-18"},
        },
    }, ensure_ascii=False))

    assert decision.kind == "action"
    assert decision.rationale_summary == "Need weather before choosing activities."
    assert decision.tool == "get_weather_forecast"
    assert decision.args == {"city": "南京", "date": "2026-05-18"}
    assert decision.final is None


def test_parse_final_decision():
    decision = parse_react_decision(json.dumps({
        "rationale_summary": "Enough observations.",
        "final": {
            "findings": [{"category": "weather", "title": "南京天气", "detail": "小雨"}],
            "covered_items": ["南京天气"],
        },
    }, ensure_ascii=False))

    assert decision.kind == "final"
    assert decision.tool is None
    assert decision.args == {}
    assert decision.final["findings"][0]["title"] == "南京天气"


def test_parse_invalid_decision_returns_error_kind():
    decision = parse_react_decision("not json")

    assert decision.kind == "error"
    assert "Invalid JSON" in decision.error


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system_prompt: str, user_message: str, tools=None):
        self.calls.append({"system_prompt": system_prompt, "user_message": user_message, "tools": tools})
        text = self.responses.pop(0)
        return LLMResult(success=True, text=text, data=None, tokens_used=11)


def test_run_react_loop_executes_action_then_final(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Check weather first.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Weather observed.",
            "final": {
                "findings": [{"category": "weather", "title": "南京天气", "detail": "小雨"}],
                "covered_items": ["南京天气"],
            },
        }, ensure_ascii=False),
    ])
    executed = []

    def fake_execute(name, args):
        executed.append((name, args))
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=3,
    )

    assert result.status == "success"
    assert result.final["findings"][0]["title"] == "南京天气"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "get_weather_forecast"
    assert result.steps[0].observation == "南京小雨"
    assert executed == [("get_weather_forecast", {"city": "南京"})]
    assert "Observation 1" in llm.calls[1]["user_message"]


def test_run_react_loop_rejects_unknown_tool(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Try unsafe tool.",
            "action": {"tool": "delete_database", "args": {}},
        }, ensure_ascii=False),
    ])

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=3,
    )

    assert result.status == "failed"
    assert "not allowed" in result.error


def test_run_react_loop_stops_at_max_steps(monkeypatch):
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Still checking.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Still checking.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
    ])

    def fake_execute(name, args):
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    result = run_react_loop(
        llm,
        task="核实南京天气",
        context={"destination": "南京"},
        allowed_tools=["get_weather_forecast"],
        max_steps=2,
    )

    assert result.status == "failed"
    assert result.error == "ReAct loop reached max_steps without final answer"
    assert len(result.steps) == 2


def test_run_react_loop_writes_trace_events(monkeypatch, tmp_path):
    from travel_planning_agent.config import settings
    from travel_planning_agent.core.tracing import clear_trace_context, create_trace_id, set_trace_context

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    trace_id = create_trace_id()
    set_trace_context(trace_id, session_id="sess_react_trace")
    llm = ScriptedLLM([
        json.dumps({
            "rationale_summary": "Check weather.",
            "action": {"tool": "get_weather_forecast", "args": {"city": "南京"}},
        }, ensure_ascii=False),
        json.dumps({
            "rationale_summary": "Enough.",
            "final": {"findings": [], "covered_items": ["南京天气"]},
        }, ensure_ascii=False),
    ])

    def fake_execute(name, args):
        return ToolResult(status="success", data="南京小雨", confidence="high")

    monkeypatch.setattr("travel_planning_agent.core.react_loop.execute_registered_tool", fake_execute)

    try:
        run_react_loop(
            llm,
            task="核实南京天气",
            context={"destination": "南京"},
            allowed_tools=["get_weather_forecast"],
            max_steps=3,
        )
    finally:
        clear_trace_context()

    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event_types = [event["event_type"] for event in trace["events"]]
    assert "react_decision" in event_types
    assert "react_observation" in event_types
    assert "react_final" in event_types


def test_tool_calling_service_executes_tool_loop_and_parses_final_json(monkeypatch):
    from types import SimpleNamespace

    from travel_planning_agent.core.tool_calling_service import ToolCallingService

    responses = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_weather",
                                function=SimpleNamespace(
                                    name="get_weather_forecast",
                                    arguments='{"city":"南京"}',
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"answer":"南京小雨"}',
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
        ),
    ]

    class FakeClient:
        def __init__(self, scripted_responses):
            self.scripted_responses = list(scripted_responses)
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return self.scripted_responses.pop(0)

    client = FakeClient(responses)
    executed = []

    monkeypatch.setattr(
        "travel_planning_agent.core.tool_calling_service.execute_tool",
        lambda name, args: executed.append((name, args)) or "南京小雨",
    )

    result = ToolCallingService().run(
        client=client,
        model="fake-model",
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "南京天气怎么样"},
        ],
        tools=[{"type": "function", "function": {"name": "get_weather_forecast"}}],
        extract_json=lambda text: json.loads(text),
        summarize_tool_input=lambda tool_name, tool_input: f"{tool_name}:{tool_input['city']}",
        compute_max_tokens=lambda messages: 1024,
    )

    assert result["success"] is True
    assert result["data"] == {"answer": "南京小雨"}
    assert result["tokens_used"] == 27
    assert executed == [("get_weather_forecast", {"city": "南京"})]
    assert result["tool_calls_log"] == [
        {"tool": "get_weather_forecast", "input": "get_weather_forecast:南京", "result": "南京小雨"}
    ]
    assert len(client.calls) == 2
