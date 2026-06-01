from __future__ import annotations


def append_one_day_plan(plan_data: dict, new_day: dict) -> dict:
    updated = {"days": [dict(day) for day in plan_data.get("days") or []]}

    if updated["days"]:
        last_day = dict(updated["days"][-1])
        last_day["segments"] = [
            dict(seg)
            for seg in last_day.get("segments", [])
            if "return" not in list(seg.get("tags") or [])
        ]
        updated["days"][-1] = last_day

    updated["days"].append(dict(new_day))
    updated["days"] = sorted(updated["days"], key=lambda day: int(day.get("day_number") or 0))
    return updated
