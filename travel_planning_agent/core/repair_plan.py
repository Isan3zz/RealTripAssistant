"""Build explicit repair tasks from verification failures and warnings."""

from __future__ import annotations


def build_repair_plan(failures: list[dict], warnings: list[dict]) -> dict:
    tasks = []
    for failure in failures:
        rule_id = failure.get("rule_id")
        detail = failure.get("detail", "")
        if rule_id == "W08":
            target = detail.split("：", 1)[-1] if "：" in detail else detail
            tasks.append({
                "repair_type": "insert_required_poi",
                "target": target,
                "reason": detail,
                "priority": 1,
            })
        elif rule_id == "W04":
            tasks.append({
                "repair_type": "add_return_transport",
                "target": "final_day",
                "reason": detail,
                "priority": 1,
            })
    for warning in warnings:
        rule_id = warning.get("rule_id")
        detail = warning.get("detail", "")
        if rule_id == "W07":
            tasks.append({
                "repair_type": "add_route_buffer",
                "target": warning.get("affected_segments") or [],
                "reason": detail,
                "priority": 3,
            })
    if any(task["priority"] == 1 for task in tasks):
        status = "repair_needed"
    elif tasks:
        status = "repair_recommended"
    else:
        status = "clean"
    return {"status": status, "tasks": tasks}
