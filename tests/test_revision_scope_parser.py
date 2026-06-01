from travel_planning_agent.core.revision_scope_parser import parse_revision_scope


def _sample_plan():
    return {
        "days": [
            {
                "day_number": 1,
                "segments": [
                    {"title": "中山路步行街", "type": "activity", "module": "evening"},
                ],
            },
            {
                "day_number": 2,
                "segments": [
                    {"title": "鼓浪屿", "type": "activity", "module": "morning"},
                    {"title": "午餐", "type": "meal", "module": "afternoon"},
                    {"title": "环岛路骑行", "type": "activity", "module": "afternoon"},
                ],
            },
        ]
    }


def test_parse_revision_scope_matches_day_level_request():
    parsed = parse_revision_scope("第二天轻松一点", _sample_plan())

    assert parsed["matched"] is True
    assert parsed["target_day"] == 2
    assert parsed["target_module"] is None
    assert parsed["change_type"] == "lighten_day"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_matches_day_module_request():
    parsed = parse_revision_scope("第二天下午轻松一点", _sample_plan())

    assert parsed["matched"] is True
    assert parsed["target_day"] == 2
    assert parsed["target_module"] == "afternoon"
    assert parsed["change_type"] == "lighten_day"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_matches_unique_segment_request():
    parsed = parse_revision_scope("把鼓浪屿换掉", _sample_plan())

    assert parsed["matched"] is True
    assert parsed["target_segment"] == "鼓浪屿"
    assert parsed["change_type"] == "remove_segment"
    assert parsed["clarification_needed"] is False


def test_parse_revision_scope_requires_clarification_for_vague_request():
    parsed = parse_revision_scope("改一下", _sample_plan())

    assert parsed["matched"] is False
    assert parsed["clarification_needed"] is True
    assert parsed["clarification_question"] == "你想改哪一天，还是改某个具体景点/时段？"


def test_parse_revision_scope_detects_append_day_request():
    parsed = parse_revision_scope("我还能多玩一天", _sample_plan())

    assert parsed["matched"] is True
    assert parsed["change_type"] == "append_day"
    assert parsed["scope_type"] == "append"
    assert parsed["impact_level"] == "high"
    assert parsed["clarification_needed"] is True


def test_parse_revision_scope_detects_global_transport_change():
    parsed = parse_revision_scope("我要坐飞机", _sample_plan())

    assert parsed["matched"] is True
    assert parsed["change_type"] == "change_transport_mode"
    assert parsed["scope_type"] == "global"
    assert parsed["impact_level"] == "high"
    assert parsed["clarification_needed"] is True


def test_parse_revision_scope_marks_ambiguous_feedback():
    parsed = parse_revision_scope("感觉不太对", _sample_plan())

    assert parsed["matched"] is False
    assert parsed["change_type"] == "ambiguous_feedback"
    assert parsed["scope_type"] == "unknown"
    assert parsed["clarification_needed"] is True
