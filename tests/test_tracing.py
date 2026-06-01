import json

from travel_planning_agent.config import settings
from travel_planning_agent.tool_runtime import ToolSpec, registry, execute_registered_tool


def test_tool_runtime_writes_tool_call_trace(monkeypatch, tmp_path):
    from travel_planning_agent.core.tracing import clear_trace_context, set_trace_context

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    registry.register(
        ToolSpec(
            name="trace_echo",
            description="Echo for trace test",
            handler=lambda args: f"echo:{args['value']}",
        )
    )
    set_trace_context("trace_tool_test", session_id="sess_trace")

    try:
        result = execute_registered_tool("trace_echo", {"value": "hello"})
    finally:
        clear_trace_context()

    assert result.status == "success"
    trace_files = list(tmp_path.glob("traces/**/*.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    event = trace["events"][0]
    assert event["event_type"] == "tool_call"
    assert event["stage"] == "tool"
    assert event["data"]["tool"] == "trace_echo"
    assert event["data"]["input"] == {"value": "hello"}
    assert event["data"]["output"]["status"] == "success"
    assert event["data"]["output"]["data"] == "echo:hello"
