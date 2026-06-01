import json

from travel_planning_agent.tools.weather_parser import parse_weather_briefs, summarize_weather


def _mcp_text(payload):
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


def test_summarize_weather_selects_trip_range_from_target_date_and_adds_advice():
    payload = {
        "city": "北京市",
        "forecasts": [
            {
                "date": "2026-05-15",
                "dayweather": "多云",
                "nightweather": "阴",
                "daytemp": "31",
                "nighttemp": "19",
                "daywind": "东南",
                "daypower": "1-3",
            },
            {
                "date": "2026-05-16",
                "dayweather": "小雨",
                "nightweather": "小雨",
                "daytemp": "25",
                "nighttemp": "18",
                "daywind": "东",
                "daypower": "1-3",
            },
            {
                "date": "2026-05-17",
                "dayweather": "晴",
                "nightweather": "晴",
                "daytemp": "27",
                "nighttemp": "18",
                "daywind": "东",
                "daypower": "1-3",
            },
        ],
    }

    summary = summarize_weather(_mcp_text(payload), "北京", "2026-05-16", limit=2)

    assert "2026-05-16 小雨/小雨" in summary
    assert "2026-05-17 晴/晴" in summary
    assert "带伞" in summary
    assert "2026-05-15" not in summary


def test_summarize_weather_defaults_to_first_three_days():
    payload = {
        "city": "杭州市",
        "forecasts": [
            {"date": "2026-05-15", "dayweather": "多云", "nightweather": "晴", "daytemp": "28", "nighttemp": "20", "daywind": "东", "daypower": "1-3"},
            {"date": "2026-05-16", "dayweather": "晴", "nightweather": "晴", "daytemp": "30", "nighttemp": "20", "daywind": "东南", "daypower": "1-3"},
            {"date": "2026-05-17", "dayweather": "多云", "nightweather": "多云", "daytemp": "30", "nighttemp": "20", "daywind": "东南", "daypower": "1-3"},
            {"date": "2026-05-18", "dayweather": "晴", "nightweather": "多云", "daytemp": "31", "nighttemp": "21", "daywind": "东南", "daypower": "1-3"},
        ],
    }

    summary = summarize_weather(_mcp_text(payload), "杭州")

    assert summary.count("- 2026-") == 3
    assert "2026-05-18" not in summary


def test_parse_weather_briefs_extracts_forecasts():
    payload = {"forecasts": [{"date": "2026-05-15", "dayweather": "晴", "nightweather": "晴"}]}

    briefs = parse_weather_briefs(_mcp_text(payload))

    assert briefs[0]["date"] == "2026-05-15"
    assert briefs[0]["dayweather"] == "晴"


def test_summarize_empty_weather_degrades_cleanly():
    assert summarize_weather(_mcp_text({"forecasts": []}), "杭州") == "【天气】杭州: 暂未查到天气预报"
