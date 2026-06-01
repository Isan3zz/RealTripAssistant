"""
test_pin.py — Pin 规则与操作测试
"""

from travel_planning_agent.models.pin import create_pin, find_pinned_segment, is_segment_pinned
from travel_planning_agent.types import Pin


def test_create_pin():
    pin = create_pin("segment", "seg_001")
    assert pin.pin_id.startswith("pin_")
    assert pin.target_type == "segment"
    assert pin.target_id == "seg_001"
    assert pin.mutable is False


def test_find_pin():
    pins = [
        Pin(pin_id="p1", target_type="segment", target_id="s1", scope="entire_trip"),
        Pin(pin_id="p2", target_type="segment", target_id="s2", scope="entire_trip"),
    ]
    result = find_pinned_segment(pins, "s1")
    assert result is not None
    assert result.pin_id == "p1"


def test_find_pin_not_found():
    result = find_pinned_segment([], "nonexistent")
    assert result is None


def test_is_pinned():
    pins = [Pin(pin_id="p1", target_type="segment", target_id="s1", scope="entire_trip", mutable=False)]
    assert is_segment_pinned(pins, "s1") is True
    assert is_segment_pinned(pins, "s2") is False


def test_mutable_pin_not_considered_pinned():
    pins = [Pin(pin_id="p1", target_type="segment", target_id="s1", scope="entire_trip", mutable=True)]
    assert is_segment_pinned(pins, "s1") is False
