from travel_planning_agent.core.repair_plan import build_repair_plan


def test_build_repair_plan_for_missing_must_have():
    failures = [{"rule_id": "W08", "detail": "缺少用户必去项：玄武湖"}]

    plan = build_repair_plan(failures, warnings=[])

    assert plan["status"] == "repair_needed"
    assert plan["tasks"] == [{
        "repair_type": "insert_required_poi",
        "target": "玄武湖",
        "reason": "缺少用户必去项：玄武湖",
        "priority": 1,
    }]


def test_build_repair_plan_for_missing_return_transport():
    failures = [{"rule_id": "W04", "detail": "最后一天缺少返程交通"}]

    plan = build_repair_plan(failures, warnings=[])

    assert plan["tasks"][0]["repair_type"] == "add_return_transport"
    assert plan["tasks"][0]["priority"] == 1


def test_build_repair_plan_for_route_buffer_warning():
    warnings = [{"rule_id": "W07", "detail": "两点之间仅 0 分钟，建议补充交通缓冲"}]

    plan = build_repair_plan(failures=[], warnings=warnings)

    assert plan["status"] == "repair_recommended"
    assert plan["tasks"][0]["repair_type"] == "add_route_buffer"
