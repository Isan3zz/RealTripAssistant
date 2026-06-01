"""
test_diff.py — Plan Diff 测试
"""

from travel_planning_agent.types import (
    PlanState, Constraints, Traveler, ItineraryDay, Segment, SegmentType, Pin, PlanDiff, ChangeItem,
)
from travel_planning_agent.storage.diff import generate_diff
from travel_planning_agent.models.plan_diff import create_diff, format_diff_for_user
from datetime import date


def _make_state(trip_id: str, day_count: int) -> PlanState:
    c = Constraints(destination="HZ", start_date=date(2026, 5, 1), end_date=3,
                    travelers=[Traveler(age_group="adult")], budget=5000, pace="moderate")
    s = PlanState(trip_id=trip_id, constraints=c)
    for i in range(1, day_count + 1):
        day = ItineraryDay(day_id=f"d{i}", day_number=i, theme=f"Day {i}")
        seg = Segment(segment_id=f"s{i}", type=SegmentType.ACTIVITY, title=f"Activity {i}")
        day.segments.append(seg)
        s.days.append(day)
    return s


def test_diff_no_changes():
    old = _make_state("test", 2)
    new = _make_state("test", 2)
    diff = generate_diff(old, new)
    assert all(c.change_type == "unchanged" for c in diff.changes)


def test_diff_title_modified():
    old = _make_state("test", 1)
    new = _make_state("test", 1)
    new.days[0].segments[0].title = "Modified"
    diff = generate_diff(old, new, reasons=["test change"])
    modified = [c for c in diff.changes if c.change_type == "modified"]
    assert len(modified) == 1
    assert modified[0].field_changes["title"]["new"] == "Modified"


def test_diff_segment_added():
    old = _make_state("test", 1)
    new = _make_state("test", 1)
    new.days[0].segments.append(
        Segment(segment_id="s2", type=SegmentType.ACTIVITY, title="New")
    )
    diff = generate_diff(old, new)
    added = [c for c in diff.changes if c.change_type == "added"]
    assert len(added) == 1
    assert added[0].segment_id == "s2"


def test_diff_pin_integrity():
    old = _make_state("test", 1)
    new = _make_state("test", 1)
    new.pins = [Pin(pin_id="p1", target_type="segment", target_id="s1", scope="entire_trip", mutable=False)]
    diff = generate_diff(old, new)
    assert diff.pin_integrity["p1"]["preserved"] is True


def test_format_diff():
    diff = PlanDiff(
        diff_id="d1", old_plan_version=1, new_plan_version=2,
        changes=[
            ChangeItem(segment_id="s1", change_type="modified",
                       field_changes={"title": {"old": "A", "new": "B"}},
                       reason="changed", impact={"budget": -100}),
        ],
        pin_integrity={"p1": {"preserved": True}},
    )
    text = format_diff_for_user(diff)
    assert "A" in text
    assert "B" in text
    assert "p1" in text
