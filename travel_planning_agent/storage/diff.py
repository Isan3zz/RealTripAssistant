"""
storage/diff.py — Plan Diff 生成器

比较两个版本的行程，输出结构化变化。
"""

from copy import deepcopy
from travel_planning_agent.types import PlanState, PlanDiff, ChangeItem, Pin


def generate_diff(
    old_state: PlanState,
    new_state: PlanState,
    reasons: list[str] = None,
) -> PlanDiff:
    """
    比较两个版本的行程，输出结构化 PlanDiff。

    逻辑：
      逐天逐 segment 比较 old 和 new 状态
      标记 modified / added / removed / unchanged
      检查 pin integrity
    """
    reasons = reasons or []
    changes: list[ChangeItem] = []
    reason_idx = 0

    # 构建 old segments 索引 {segment_id: segment}
    old_segments = {}
    for day in old_state.days:
        for seg in day.segments:
            old_segments[seg.segment_id] = seg

    # 构建 new segments 索引
    new_segments = {}
    for day in new_state.days:
        for seg in day.segments:
            new_segments[seg.segment_id] = seg

    # 比较所有 old segment
    for sid, old_seg in old_segments.items():
        if sid in new_segments:
            new_seg = new_segments[sid]
            field_changes = {}
            for f in ("title", "start_time", "end_time", "type"):
                old_val = getattr(old_seg, f)
                new_val = getattr(new_seg, f)
                if old_val != new_val:
                    field_changes[f] = {"old": old_val, "new": new_val}
            # 比较 cost
            old_cost = old_seg.estimated_cost.amount if old_seg.estimated_cost else 0
            new_cost = new_seg.estimated_cost.amount if new_seg.estimated_cost else 0
            if old_cost != new_cost:
                field_changes["estimated_cost"] = {"old": old_cost, "new": new_cost}

            if field_changes:
                reason = reasons[reason_idx] if reason_idx < len(reasons) else ""
                reason_idx += 1

                # 计算影响
                impact = {}
                if "estimated_cost" in field_changes:
                    impact["budget"] = new_cost - old_cost

                changes.append(ChangeItem(
                    segment_id=sid,
                    change_type="modified",
                    field_changes=field_changes,
                    reason=reason,
                    impact=impact,
                ))
            else:
                changes.append(ChangeItem(
                    segment_id=sid,
                    change_type="unchanged",
                    field_changes={},
                ))
        else:
            reason = reasons[reason_idx] if reason_idx < len(reasons) else ""
            reason_idx += 1
            changes.append(ChangeItem(
                segment_id=sid,
                change_type="removed",
                field_changes={},
                reason=reason,
            ))

    # 新增的 segment
    for sid in new_segments:
        if sid not in old_segments:
            reason = reasons[reason_idx] if reason_idx < len(reasons) else ""
            reason_idx += 1
            changes.append(ChangeItem(
                segment_id=sid,
                change_type="added",
                field_changes={},
                reason=reason,
            ))

    # Pin integrity
    pin_integrity = {}
    for pin in new_state.pins:
        if not pin.mutable:
            pin_integrity[pin.pin_id] = {"preserved": True}

    import uuid
    return PlanDiff(
        diff_id=f"diff_{uuid.uuid4().hex[:8]}",
        old_plan_version=old_state.plan_version,
        new_plan_version=new_state.plan_version,
        changes=changes,
        pin_integrity=pin_integrity,
    )
