"""
test_rules.py — 4 条确定性规则的单元测试

覆盖 Case 1-4 的验收用例（Section 8 of Phase 1 spec）。
"""

import pytest

from travel_planning_agent.engine.rules import (
    check_time_non_overlap,
    check_budget_not_exceeded,
    check_date_in_bounds,
    check_required_fields_complete,
    _clean_location_query,
    _get_coords,
)
from travel_planning_agent.engine.rule_engine import run_rule_engine
from travel_planning_agent.types import PlanState, Constraints, Segment, ItineraryDay, SegmentType, Cost, Location
from datetime import date


def test_clean_location_query_removes_activity_verbs_and_descriptions():
    assert _clean_location_query("游览西湖，欣赏湖光山色杭州", "杭州") == "西湖"
    assert _clean_location_query("参观灵隐寺，感受古刹的宁静与庄严杭州", "杭州") == "灵隐寺"
    assert _clean_location_query("入住全季酒店（杭州西湖鼓楼店），毗邻西湖景区杭州", "杭州") == "全季酒店"


def test_get_coords_uses_clean_query_and_cache(monkeypatch, tmp_path):
    from travel_planning_agent.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "external_rule_checks_enabled", True)
    calls = []

    def fake_geo_encode(address, city=""):
        calls.append((address, city))
        return [{"type": "text", "text": '{"geo": {"location": "120.1,30.2"}}'}]

    monkeypatch.setattr("travel_planning_agent.gaode_client.geo_encode", fake_geo_encode)

    loc = Location(name="游览西湖，欣赏湖光山色杭州", city="杭州")
    assert _get_coords(loc) == (120.1, 30.2)
    assert _get_coords(loc) == (120.1, 30.2)
    assert calls == [("西湖", "杭州")]


def test_get_coords_skips_external_lookup_when_rule_checks_disabled(monkeypatch):
    from travel_planning_agent.config import settings

    monkeypatch.setattr(settings, "external_rule_checks_enabled", False)

    def fake_geo_encode(address, city=""):
        raise AssertionError("geo_encode should not be called")

    monkeypatch.setattr("travel_planning_agent.gaode_client.geo_encode", fake_geo_encode)

    loc = Location(name="游览西湖，欣赏湖光山色杭州", city="杭州")
    assert _get_coords(loc) is None


class TestR01TimeNonOverlap:
    """R01 时间连续性测试"""

    def test_valid_times_pass(self, valid_state):
        """正常时间不重叠应 PASS。"""
        result = check_time_non_overlap(valid_state)
        assert result.result == "PASS"
        assert result.rule_id == "R01"

    def test_overlapping_times_fail(self, overlapping_state):
        """时间重叠应 FAIL。"""
        result = check_time_non_overlap(overlapping_state)
        assert result.result == "FAIL"
        assert "重叠" in result.detail
        assert len(result.affected_segments) >= 2

    def test_no_time_info_skip(self, base_constraints):
        """缺少时间信息的 segment 应跳过。"""
        state = PlanState(
            trip_id="test",
            constraints=base_constraints,
        )
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title="无时间"),  # 无 start/end_time
            Segment(segment_id="seg_002", type=SegmentType.ACTIVITY, title="也无时间"),
        ]
        state.days = [day]
        result = check_time_non_overlap(state)
        assert result.result == "PASS"  # 没有可比较的时间对

    def test_exact_boundary_pass(self, base_constraints):
        """相邻活动首尾时间完全衔接应 PASS。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(
                segment_id="seg_001", type=SegmentType.ACTIVITY, title="活动A",
                start_time="09:00", end_time="11:00",
            ),
            Segment(
                segment_id="seg_002", type=SegmentType.ACTIVITY, title="活动B",
                start_time="11:00", end_time="13:00",  # 正好衔接
            ),
        ]
        state.days = [day]
        result = check_time_non_overlap(state)
        assert result.result == "PASS"

    def test_multiple_overlaps(self, base_constraints):
        """多重重叠只报告首次冲突。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title="A", start_time="09:00", end_time="10:30"),
            Segment(segment_id="seg_002", type=SegmentType.ACTIVITY, title="B", start_time="10:00", end_time="12:00"),
            Segment(segment_id="seg_003", type=SegmentType.ACTIVITY, title="C", start_time="11:30", end_time="13:00"),
        ]
        state.days = [day]
        result = check_time_non_overlap(state)
        assert result.result == "FAIL"


class TestR02Budget:
    """R02 预算测试"""

    def test_budget_within_limit_pass(self, valid_state):
        """预算未超限应 PASS。"""
        result = check_budget_not_exceeded(valid_state)
        assert result.result == "PASS"
        assert result.rule_id == "R02"

    def test_budget_exceeded_fail(self, budget_exceeded_state):
        """预算超限应 FAIL。"""
        result = check_budget_not_exceeded(budget_exceeded_state)
        assert result.result == "FAIL"
        assert "超出预算" in result.detail

    def test_budget_exact_limit_pass(self, base_constraints):
        """花费等于预算上限应 PASS。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(
                segment_id="seg_001",
                type=SegmentType.ACTIVITY,
                title="刚好花完",
                estimated_cost=Cost(amount=20000),
            ),
        ]
        state.days = [day]
        result = check_budget_not_exceeded(state)
        assert result.result == "PASS"

    def test_no_cost_segments(self, base_constraints):
        """所有 segment 无费用应 PASS（总花费 0）。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title="免费活动"),
        ]
        state.days = [day]
        result = check_budget_not_exceeded(state)
        assert result.result == "PASS"

    def test_no_constraints_fail(self):
        """无约束条件应 FAIL。"""
        state = PlanState(trip_id="test", constraints=None)
        result = check_budget_not_exceeded(state)
        assert result.result == "FAIL"


class TestR03DateBounds:
    """R03 日期边界测试"""

    def test_valid_dates_pass(self, valid_state):
        """日期在范围内应 PASS。"""
        result = check_date_in_bounds(valid_state)
        assert result.result == "PASS"
        assert result.rule_id == "R03"

    def test_day_number_exceeds_fail(self, base_constraints):
        """天数超出范围应 FAIL。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_099", day_number=99)  # 只有 4 天
        state.days = [day]
        result = check_date_in_bounds(state)
        assert result.result == "FAIL"
        assert "超出" in result.detail

    def test_day_number_zero_fail(self, base_constraints):
        """day_number 为 0 应 FAIL。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_000", day_number=0)
        state.days = [day]
        result = check_date_in_bounds(state)
        assert result.result == "FAIL"

    def test_no_constraints_fail(self):
        """无约束应 FAIL。"""
        state = PlanState(trip_id="test", constraints=None)
        state.days = [ItineraryDay(day_id="day_001", day_number=1)]
        result = check_date_in_bounds(state)
        assert result.result == "FAIL"


class TestR04RequiredFields:
    """R04 必填完整性测试"""

    def test_complete_fields_pass(self, valid_state):
        """完整行程应 PASS。"""
        result = check_required_fields_complete(valid_state)
        assert result.result == "PASS"
        assert result.rule_id == "R04"

    def test_missing_activity_fail(self, missing_activity_state):
        """缺少 ACTIVITY 应 FAIL。"""
        result = check_required_fields_complete(missing_activity_state)
        assert result.result == "FAIL"
        assert "缺少活动" in result.detail

    def test_empty_days_fail(self, base_constraints):
        """行程为空应 FAIL。"""
        state = PlanState(trip_id="test", constraints=base_constraints, days=[])
        result = check_required_fields_complete(state)
        assert result.result == "FAIL"
        assert "为空" in result.detail

    def test_empty_title_fail(self, base_constraints):
        """标题为空的 segment 应 FAIL。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title=""),
            Segment(segment_id="seg_002", type=SegmentType.MEAL, title="午餐"),
        ]
        state.days = [day]
        result = check_required_fields_complete(state)
        assert result.result == "FAIL"

    def test_multiple_activities_all_good(self, base_constraints):
        """一天有多个 activity 应 PASS。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=1)
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title="景点A"),
            Segment(segment_id="seg_002", type=SegmentType.ACTIVITY, title="景点B"),
            Segment(segment_id="seg_003", type=SegmentType.MEAL, title="午餐"),
        ]
        state.days = [day]
        result = check_required_fields_complete(state)
        assert result.result == "PASS"


class TestRuleEngine:
    """规则引擎集成测试"""

    def test_all_rules_executed(self, valid_state):
        """规则引擎应执行所有 8 条规则。"""
        result = run_rule_engine(valid_state)
        assert len(result.rule_checks) == 8
        assert result.overall_pass is True

    def test_rule_ids_present(self, valid_state):
        """所有规则 ID 应包含在结果中。"""
        result = run_rule_engine(valid_state)
        rule_ids = {r.rule_id for r in result.rule_checks}
        expected = {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"}
        assert rule_ids == expected

    def test_failure_propagation(self, overlapping_state):
        """单条规则失败应导致 overall_pass=False。"""
        result = run_rule_engine(overlapping_state)
        assert result.overall_pass is False
        failed_rules = [r for r in result.rule_checks if r.result == "FAIL"]
        assert any(r.rule_id == "R01" for r in failed_rules)

    def test_multiple_failures(self, base_constraints):
        """多条规则同时失败。"""
        state = PlanState(trip_id="test", constraints=base_constraints)
        day = ItineraryDay(day_id="day_001", day_number=99)  # R03 FAIL
        day.segments = [
            Segment(segment_id="seg_001", type=SegmentType.ACTIVITY, title="A", start_time="09:00", end_time="10:00"),
            Segment(segment_id="seg_002", type=SegmentType.ACTIVITY, title="B", start_time="09:30", end_time="11:00"),  # R01 FAIL
        ]
        state.days = [day]
        result = run_rule_engine(state)
        assert result.overall_pass is False
        failed_ids = {r.rule_id for r in result.rule_checks if r.result == "FAIL"}
        assert "R01" in failed_ids
        assert "R03" in failed_ids
