"""
models/pin.py — Pin 操作辅助函数
"""

from typing import Optional
from travel_planning_agent.types import Pin, Segment, ItineraryDay


def create_pin(
    target_type: str,
    target_id: str,
    scope: str = "entire_trip",
    day_number: Optional[int] = None,
    reason: str = "user_selected",
) -> Pin:
    """创建新的 Pin。"""
    import uuid
    return Pin(
        pin_id=f"pin_{uuid.uuid4().hex[:8]}",
        target_type=target_type,
        target_id=target_id,
        scope=scope,
        day_number=day_number,
        mutable=False,
        reason=reason,
    )


def find_pinned_segment(pins: list[Pin], segment_id: str) -> Optional[Pin]:
    """查找指定 segment_id 对应的 pin。"""
    for pin in pins:
        if pin.target_type == "segment" and pin.target_id == segment_id:
            return pin
    return None


def is_segment_pinned(pins: list[Pin], segment_id: str) -> bool:
    """判断 segment 是否被锁定。"""
    pin = find_pinned_segment(pins, segment_id)
    return pin is not None and not pin.mutable
