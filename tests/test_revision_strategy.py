from travel_planning_agent.core.revision_strategy import choose_revision_strategy


def test_choose_revision_strategy_for_scope_patch():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "lighten_day",
            "scope_type": "day_module",
            "impact_level": "low",
            "clarification_needed": False,
        }
    )

    assert strategy["strategy"] == "patch_scope"


def test_choose_revision_strategy_for_append_day_requires_confirmation():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "append_day",
            "scope_type": "append",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？",
        }
    )

    assert strategy["strategy"] == "clarify"
    assert strategy["clarification_question"] == "你是想在现有行程后面新增一天安排，还是把整趟行程重排成 4 天？"


def test_choose_revision_strategy_for_global_transport_change():
    strategy = choose_revision_strategy(
        {
            "matched": True,
            "change_type": "change_transport_mode",
            "scope_type": "global",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你是想只改返程，还是整趟交通方式都调整？",
        }
    )

    assert strategy["strategy"] == "clarify"


def test_choose_revision_strategy_for_unknown_feedback():
    strategy = choose_revision_strategy(
        {
            "matched": False,
            "change_type": "ambiguous_feedback",
            "scope_type": "unknown",
            "impact_level": "high",
            "clarification_needed": True,
            "clarification_question": "你想改哪一天，还是改某个具体景点/时段？",
        }
    )

    assert strategy["strategy"] == "clarify"
