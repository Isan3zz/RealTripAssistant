from datetime import date

from travel_planning_agent.core.tool_dedup import (
    find_tool_call,
    remember_tool_call,
    tool_call_fingerprint,
)


def test_tool_call_fingerprint_ignores_dict_arg_order():
    first = tool_call_fingerprint("get_weather_forecast", {"city": "南京", "days": 2, "date": "2026-05-18"})
    second = tool_call_fingerprint("get_weather_forecast", {"date": "2026-05-18", "city": "南京", "days": 2})

    assert first == second
    assert first.startswith("sha256:")


def test_tool_call_fingerprint_normalizes_dates_and_nested_values():
    first = tool_call_fingerprint("search_train", {"date": date(2026, 5, 18), "filters": {"seat": ["二等座", "一等座"]}})
    second = tool_call_fingerprint("search_train", {"filters": {"seat": ["二等座", "一等座"]}, "date": "2026-05-18"})

    assert first == second


def test_remember_and_find_tool_call_reuses_successful_evidence_ids():
    registry = {}
    fingerprint = remember_tool_call(
        registry,
        "get_weather_forecast",
        {"city": "南京", "date": "2026-05-18", "days": 2},
        status="success",
        evidence_ids=["ev_weather"],
        task_id="weather",
    )

    found = find_tool_call(registry, "get_weather_forecast", {"days": 2, "date": "2026-05-18", "city": "南京"})

    assert found["fingerprint"] == fingerprint
    assert found["status"] == "success"
    assert found["evidence_ids"] == ["ev_weather"]
