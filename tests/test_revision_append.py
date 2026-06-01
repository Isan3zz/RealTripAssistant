from travel_planning_agent.core.revision_append import append_one_day_plan


def test_append_one_day_plan_preserves_existing_days():
    plan_data = {
        "days": [
            {"day_number": 1, "theme": "第一天", "segments": [{"title": "中山路"}]},
            {"day_number": 2, "theme": "第二天", "segments": [{"title": "鼓浪屿"}]},
        ]
    }
    new_day = {
        "day_number": 3,
        "theme": "新增一天",
        "segments": [{"title": "植物园"}],
    }

    updated = append_one_day_plan(plan_data, new_day)

    assert [day["day_number"] for day in updated["days"]] == [1, 2, 3]
    assert updated["days"][0]["theme"] == "第一天"
    assert updated["days"][1]["theme"] == "第二天"
    assert updated["days"][2]["theme"] == "新增一天"


def test_append_one_day_plan_removes_old_return_segment_from_previous_last_day():
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "theme": "返程日",
                "segments": [
                    {"title": "酒店早餐", "type": "meal"},
                    {"title": "从厦门返回杭州", "type": "transport", "tags": ["return"]},
                ],
            }
        ]
    }
    new_day = {
        "day_number": 3,
        "theme": "新增一天",
        "segments": [{"title": "沙坡尾", "type": "activity"}],
    }

    updated = append_one_day_plan(plan_data, new_day)

    assert [seg["title"] for seg in updated["days"][0]["segments"]] == ["酒店早餐"]
    assert updated["days"][1]["day_number"] == 3
