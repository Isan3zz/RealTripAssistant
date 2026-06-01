from types import SimpleNamespace

from travel_planning_agent.core.plan_schema import format_plan_view


def test_format_plan_view_builds_stable_schema_from_plan_data():
    trip = SimpleNamespace(origin="\u676d\u5dde", destination="\u53a6\u95e8", days=2, budget=5000)
    plan_data = {
        "days": [
            {
                "day_number": 1,
                "theme": "\u62b5\u8fbe\u53a6\u95e8",
                "day_note": "\u8f7b\u677e\u62b5\u8fbe",
                "segments": [
                    {
                        "segment_id": "s1",
                        "type": "activity",
                        "module": "afternoon",
                        "start_time": "14:00",
                        "end_time": "16:00",
                        "title": "\u4e2d\u5c71\u8def\u6b65\u884c\u8857",
                        "location": {"name": "\u4e2d\u5c71\u8def\u6b65\u884c\u8857", "city": "\u53a6\u95e8"},
                        "estimated_cost": {"amount": 50, "currency": "CNY"},
                        "tags": ["classic"],
                        "note": "\u6162\u6162\u901b",
                    }
                ],
            }
        ]
    }

    view = format_plan_view(plan_data, trip=trip)

    assert view["schema_version"] == "plan.v1"
    assert view["origin"] == "\u676d\u5dde"
    assert view["destination"] == "\u53a6\u95e8"
    assert view["day_count"] == 2
    assert view["budget"] == {"amount": 5000, "currency": "CNY"}
    assert view["total_cost"] == {"amount": 50, "currency": "CNY"}
    assert view["days"][0]["title"] == "\u62b5\u8fbe\u53a6\u95e8"
    assert view["days"][0]["segments"][0]["time"] == "14:00-16:00"
    assert view["days"][0]["segments"][0]["estimated_cost"] == {"amount": 50, "currency": "CNY"}


def test_format_plan_view_backfills_attention_for_legacy_plan_data():
    trip = SimpleNamespace(origin="杭州", destination="厦门", days=1, budget=5000)
    plan_data = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {
                        "segment_id": "train",
                        "type": "transport",
                        "start_time": "08:00",
                        "end_time": "14:00",
                        "title": "乘坐D3211次列车 杭州 → 厦门",
                    },
                    {
                        "segment_id": "meal",
                        "type": "meal",
                        "start_time": "14:30",
                        "end_time": "15:30",
                        "title": "午餐",
                        "note": "如果排队久，直接换附近同类型餐厅。",
                    },
                    {
                        "segment_id": "activity",
                        "type": "activity",
                        "start_time": "16:00",
                        "end_time": "18:00",
                        "title": "鼓浪屿",
                        "note": "系统补齐的必要规划项",
                    },
                ],
            }
        ]
    }

    segments = format_plan_view(plan_data, trip=trip)["days"][0]["segments"]

    assert segments[0]["attention"] == "请以实际出票信息为准，提前确认出发站、检票口和到站交通。"
    assert segments[1]["attention"] == "如果排队久，直接换附近同类型餐厅。"
    assert segments[2]["attention"] == ""
