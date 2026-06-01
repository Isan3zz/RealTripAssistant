from datetime import datetime

from travel_planning_agent.types import Evidence, ItineraryDay, MODULE_WINDOWS, ModuleType


class PlanningStateService:
    def remember_prefetched_weather(self, state, weather_text: str) -> str | None:
        if not weather_text:
            return None

        ev_id = f"{state.trip_id}_pref_weather"
        if ev_id in state.evidence:
            return ev_id

        state.evidence[ev_id] = Evidence(
            evidence_id=ev_id,
            source="高德",
            source_type="api",
            retrieved_at=datetime.now().isoformat(),
            claim=weather_text,
            confidence="high",
        )
        return ev_id

    def lock_module(self, state, day_num: int, module_name: str, segments: list, day_theme: str = "") -> None:
        day = next((item for item in state.days if item.day_number == day_num), None)
        if day is None:
            day = ItineraryDay(
                day_id=f"{state.trip_id}_day_{day_num}",
                day_number=day_num,
                theme=day_theme or "",
            )
            state.days.append(day)
        elif day_theme and not day.theme:
            day.theme = day_theme

        day.segments = [segment for segment in day.segments if segment.module != module_name] + list(segments)
        day.segments.sort(key=lambda segment: segment.start_time or "")

        mod_cost = sum(
            (segment.estimated_cost.amount or 0)
            for segment in segments
            if segment.estimated_cost
        )
        last_seg = max(segments, key=lambda segment: segment.end_time or "") if segments else None
        end_time = last_seg.end_time if last_seg else MODULE_WINDOWS[ModuleType(module_name)][1]
        end_location = None
        if last_seg and last_seg.location:
            end_location = {"name": last_seg.location.name, "city": last_seg.location.city}

        state.module_context[f"{day_num}_{module_name}"] = {
            "end_time": end_time,
            "end_location": end_location,
            "budget_spent": mod_cost,
            "budget_remaining": (state.constraints.budget if state.constraints else 0) - self._calc_spent_budget(state),
            "segments_locked": [segment.segment_id for segment in segments if segment.segment_id],
        }
        state.current_module = None

    @staticmethod
    def _calc_spent_budget(state) -> float:
        total = 0.0
        for day in state.days:
            for segment in day.segments:
                if segment.module and segment.estimated_cost:
                    total += segment.estimated_cost.amount
        return total
