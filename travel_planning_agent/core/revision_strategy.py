from __future__ import annotations


def choose_revision_strategy(parsed_scope: dict) -> dict:
    if parsed_scope.get("clarification_needed"):
        return {
            "strategy": "clarify",
            "clarification_question": parsed_scope.get("clarification_question", ""),
        }

    change_type = parsed_scope.get("change_type")
    scope_type = parsed_scope.get("scope_type")

    if change_type in {"lighten_day", "remove_segment", "change_return_time"} and scope_type in {
        "segment",
        "day_module",
        "day",
    }:
        return {"strategy": "patch_scope"}

    if change_type == "append_day" and scope_type == "append":
        return {"strategy": "append_day"}

    if change_type in {"change_trip_days", "change_transport_mode"} and scope_type == "global":
        return {"strategy": "replan_impacted"}

    return {
        "strategy": "clarify",
        "clarification_question": parsed_scope.get("clarification_question")
        or "你想改哪一天，还是改某个具体景点/时段？",
    }
