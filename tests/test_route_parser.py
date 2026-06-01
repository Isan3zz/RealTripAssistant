import json

from travel_planning_agent.tools.route_parser import parse_route_brief, summarize_route_duration


def _mcp_text(payload):
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


def test_parse_driving_duration_from_gaode_paths():
    payload = {
        "origin": "120.155070,30.274085",
        "destination": "120.149022,30.260793",
        "paths": [{"distance": "2844", "duration": "695", "steps": [{"duration": "21"}]}],
    }

    assert summarize_route_duration(_mcp_text(payload), "driving") == "驾车约12分钟，全程约2.8公里"


def test_parse_walking_duration_from_nested_route():
    payload = {
        "route": {
            "paths": [{"distance": 2467, "duration": 1974, "steps": [{"duration": 54}]}],
        }
    }

    assert summarize_route_duration(_mcp_text(payload), "walking") == "步行约33分钟，全程约2.5公里"
    brief = parse_route_brief(_mcp_text(payload), "walking", origin="A", destination="B")
    assert brief.duration_minutes == 33
    assert brief.distance_meters == 2467
    assert brief.origin == "A"
    assert brief.destination == "B"


def test_parse_transit_uses_fastest_plan():
    payload = {
        "origin": "120.155070,30.274085",
        "destination": "120.149022,30.260793",
        "distance": "1997",
        "transits": [
            {"duration": "3781", "walking_distance": "1938"},
            {"duration": "2033", "walking_distance": "1189"},
            {"duration": "2908", "walking_distance": "2186"},
        ],
    }

    assert summarize_route_duration(_mcp_text(payload), "transit") == "公交/地铁约34分钟，全程约2.0公里，步行约1.2公里"


def test_parse_transit_keeps_line_names_from_fastest_plan():
    payload = {
        "distance": "11100",
        "transits": [
            {
                "duration": "4000",
                "walking_distance": "1200",
                "segments": [{"bus": {"buslines": [{"name": "9路(上行)"}]}}],
            },
            {
                "duration": "2940",
                "walking_distance": "1800",
                "segments": [
                    {"bus": {"buslines": [{"name": "地铁3号线(秣周东路--林场)"}]}},
                    {"bus": {"buslines": [{"name": "304路(总统府--玄武湖)"}]}},
                ],
            },
        ],
    }

    assert (
        summarize_route_duration(_mcp_text(payload), "transit")
        == "公交/地铁约49分钟，全程约11.1公里，步行约1.8公里，乘坐地铁3号线 → 304路"
    )
    brief = parse_route_brief(_mcp_text(payload), "transit")
    assert brief.transit_lines == ["地铁3号线", "304路"]


def test_parse_missing_duration_degrades_cleanly():
    assert summarize_route_duration([{"type": "text", "text": "{}"}], "walking") == "步行: 暂未查到路线用时"
