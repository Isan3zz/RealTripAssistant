from travel_planning_agent.core.personalization import (
    build_decision_card,
    build_execution_checklist,
    build_explanation_cards,
)
from travel_planning_agent.core.plan_comparison import PLAN_PROFILES


def test_build_decision_card_summarizes_personal_plan():
    plan = {
        "days": [
            {
                "day_number": 1,
                "theme": "Arrive and explore",
                "segments": [
                    {
                        "type": "transport",
                        "title": "Train to Hangzhou",
                        "estimated_cost": {"amount": 220},
                    },
                    {
                        "type": "activity",
                        "title": "West Lake walk",
                        "tags": ["classic"],
                        "estimated_cost": {"amount": 0},
                    },
                    {
                        "type": "meal",
                        "title": "Local noodle dinner",
                        "estimated_cost": {"amount": 80},
                    },
                ],
            }
        ]
    }

    card = build_decision_card("classic", plan)

    assert card["profile_id"] == "classic"
    assert card["label"] == "经典初游"
    assert card["total_cost"] == 300
    assert card["activity_count"] == 1
    assert card["pace_level"] in {"轻松", "适中", "紧凑"}
    assert card["best_for"]
    assert card["tradeoffs"]


def test_plan_profiles_are_personal_free_travel_profiles():
    ids = [p["id"] for p in PLAN_PROFILES]
    labels = [p["label"] for p in PLAN_PROFILES]

    assert ids == ["relaxed", "classic", "food", "economy"]
    assert labels == ["轻松慢游", "经典初游", "美食深度", "省钱优先"]


def test_build_explanation_cards_explains_activity_and_transport():
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {
                        "segment_id": "a1",
                        "type": "activity",
                        "title": "West Lake",
                        "tags": ["classic"],
                        "note": "Good first visit",
                    },
                    {
                        "segment_id": "t1",
                        "type": "transport",
                        "title": "Metro to hotel",
                        "note": "Avoids traffic",
                    },
                ],
            }
        ]
    }

    cards = build_explanation_cards(plan)

    assert cards[0]["segment_id"] == "a1"
    assert "为什么推荐" in cards[0]["sections"]
    assert "注意事项" in cards[0]["sections"]
    assert cards[1]["segment_id"] == "t1"


def test_build_execution_checklist_groups_actionable_items():
    trip = {"destination": "Hangzhou", "start_date": "2026-06-01", "budget": 3000}
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"type": "transport", "title": "High-speed train", "estimated_cost": {"amount": 220}},
                    {"type": "activity", "title": "Museum", "tags": ["reservation"]},
                    {"type": "accommodation", "title": "Hotel near metro"},
                ],
            }
        ]
    }

    checklist = build_execution_checklist(trip, plan)

    categories = [item["category"] for item in checklist]
    assert "交通" in categories
    assert "预约" in categories
    assert "住宿" in categories
    assert "预算" in categories


def test_explanation_flags_rainy_outdoor_activity():
    plan = {
        "days": [
            {
                "day_number": 1,
                "day_note": "暴雨/中雨，20~21°C，南风1-3级；建议带伞",
                "segments": [
                    {
                        "segment_id": "lake",
                        "type": "activity",
                        "title": "游览云龙湖景区，欣赏湖光山色",
                        "start_time": "16:00",
                        "end_time": "18:00",
                        "tags": ["outdoor"],
                    },
                ],
            }
        ]
    }

    card = build_explanation_cards(plan)[0]

    assert "降雨" in card["sections"]["为什么推荐"] or "雨" in card["sections"]["为什么推荐"]
    assert "室内" in card["sections"]["注意事项"]


def test_explanation_flags_overlapping_schedule():
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {
                        "segment_id": "bus",
                        "type": "transport",
                        "title": "乘坐公交前往云龙湖景区",
                        "start_time": "15:40",
                        "end_time": "16:21",
                    },
                    {
                        "segment_id": "lake",
                        "type": "activity",
                        "title": "游览云龙湖景区",
                        "start_time": "16:00",
                        "end_time": "18:00",
                    },
                ],
            }
        ]
    }

    cards = build_explanation_cards(plan)

    assert "时间重叠" in cards[0]["sections"]["注意事项"]
    assert "衔接不足" in cards[1]["sections"]["注意事项"]


def test_explanation_does_not_warn_for_seamless_adjacent_blocks():
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {
                        "segment_id": "lake",
                        "type": "activity",
                        "title": "游览玄武湖公园",
                        "start_time": "10:20",
                        "end_time": "12:00",
                    },
                    {
                        "segment_id": "lunch",
                        "type": "meal",
                        "title": "在附近餐厅享用午餐",
                        "start_time": "12:00",
                        "end_time": "13:00",
                    },
                ],
            }
        ]
    }

    cards = build_explanation_cards(plan)

    assert "缓冲不足" not in cards[0]["sections"]["注意事项"]
    assert "0 分钟" not in cards[1]["sections"]["注意事项"]


def test_explanation_uses_meal_specific_reasoning():
    plan = {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"segment_id": "breakfast", "type": "meal", "title": "享用早餐", "start_time": "06:30", "end_time": "07:00"},
                    {"segment_id": "lunch", "type": "meal", "title": "享用徐州特色小吃", "start_time": "14:40", "end_time": "15:40"},
                    {"segment_id": "dinner", "type": "meal", "title": "享用晚餐", "start_time": "18:30", "end_time": "19:30"},
                ],
            }
        ]
    }

    cards = build_explanation_cards(plan)

    assert "出发前" in cards[0]["sections"]["为什么推荐"]
    assert "午餐偏晚" in cards[1]["sections"]["注意事项"]
    assert "当天主要活动" in cards[2]["sections"]["为什么推荐"]


def test_explanation_warns_when_slow_profile_is_too_dense():
    plan = {
        "profile": "relaxed",
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"segment_id": "a1", "type": "activity", "title": "徐州博物馆", "start_time": "09:00", "end_time": "10:00"},
                    {"segment_id": "a2", "type": "activity", "title": "云龙湖景区", "start_time": "11:00", "end_time": "12:00"},
                    {"segment_id": "a3", "type": "activity", "title": "户部山夜游", "start_time": "20:00", "end_time": "21:00"},
                ],
            }
        ],
    }

    cards = build_explanation_cards(plan)

    assert any("慢游" in card["sections"]["注意事项"] and "偏紧" in card["sections"]["注意事项"] for card in cards)


def test_explanation_keeps_rain_notes_on_relevant_outdoor_activity_only():
    plan = {
        "days": [
            {
                "day_number": 1,
                "day_note": "中雨，18~21°C；建议带伞",
                "segments": [
                    {
                        "segment_id": "show",
                        "type": "activity",
                        "title": "夜游宋城景区，观看《宋城千古情》表演",
                        "start_time": "19:30",
                        "end_time": "21:00",
                        "tags": ["outdoor"],
                    },
                    {
                        "segment_id": "metro",
                        "type": "transport",
                        "title": "乘坐地铁返回西湖边舒适酒店",
                        "start_time": "21:00",
                        "end_time": "21:30",
                    },
                    {
                        "segment_id": "hotel",
                        "type": "accommodation",
                        "title": "入住西湖边舒适酒店",
                        "start_time": "21:30",
                        "end_time": "00:00",
                    },
                ],
            }
        ]
    }

    cards = {card["segment_id"]: card["sections"] for card in build_explanation_cards(plan)}

    assert "雨势变大" in cards["show"]["注意事项"]
    assert "户外项目作为硬性安排" not in cards["metro"]["注意事项"]
    assert "户外项目作为硬性安排" not in cards["hotel"]["注意事项"]
    assert "把夜游结束后顺路带回酒店" in cards["metro"]["为什么推荐"]
    assert "第二天出行" in cards["hotel"]["为什么推荐"]
