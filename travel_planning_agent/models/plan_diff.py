"""
models/plan_diff.py — PlanDiff 数据模型辅助函数
"""

from travel_planning_agent.types import PlanDiff, ChangeItem, Pin


def create_diff(
    old_version: int,
    new_version: int,
    changes: list[ChangeItem],
    pins: list[Pin],
) -> PlanDiff:
    """创建 PlanDiff 实例。"""
    import uuid

    # 检查 pin integrity
    pin_integrity = {}
    for pin in pins:
        if not pin.mutable:
            pin_integrity[pin.pin_id] = {"preserved": True}

    return PlanDiff(
        diff_id=f"diff_{uuid.uuid4().hex[:8]}",
        old_plan_version=old_version,
        new_plan_version=new_version,
        changes=changes,
        pin_integrity=pin_integrity,
    )


def format_diff_for_user(diff: PlanDiff) -> str:
    """输出人类可读的 Diff 文本。"""
    lines = ["本次调整："]
    idx = 1

    for change in diff.changes:
        if change.change_type == "unchanged":
            continue

        desc = f"{idx}. {change.segment_id}"
        if change.field_changes.get("title"):
            old_title = change.field_changes["title"].get("old", "?")
            new_title = change.field_changes["title"].get("new", "?")
            desc += f" 「{old_title}」→「{new_title}」"

        if change.reason:
            desc += f"\n   原因：{change.reason}"

        if change.impact:
            impact_parts = []
            for k, v in change.impact.items():
                impact_parts.append(f"{k} {'增加' if v > 0 else '减少'} {abs(v)}")
            if impact_parts:
                desc += f"\n   影响：{'，'.join(impact_parts)}"

        lines.append(desc)
        idx += 1

    # Pin integrity
    for pin_id, info in diff.pin_integrity.items():
        if info.get("preserved"):
            lines.append(f"{idx}. {pin_id} 未变（用户已锁定）")
            idx += 1

    return "\n".join(lines)
