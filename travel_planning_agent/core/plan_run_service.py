import copy
import re
import uuid
from datetime import datetime
from typing import Optional

from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.core.execution_plan import build_global_execution_plan
from travel_planning_agent.core.plan_persistence import PlanPersistenceService
from travel_planning_agent.engine import run_rule_engine
from travel_planning_agent.types import (
    Constraints,
    Cost,
    ItineraryDay,
    Location,
    PlanState,
    Segment,
    SegmentType,
    TripSpec,
    TripStatus,
    VerificationReport,
)
from travel_planning_agent.utils import make_segment_id


class PlanRunService:
    def __init__(self, db, llm_client):
        self.db = db
        self.llm = llm_client
        self.persistence = PlanPersistenceService(db) if db else None

    def run(
        self,
        spec: TripSpec,
        session_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        profile: str = "default",
        persist: bool = True,
        activate_plan: bool = True,
        use_react_research: bool = False,
        use_execution_plan: bool = True,
    ) -> dict:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        events: list[dict] = []
        self._record_event(events, "intake", "TripSpec accepted")

        db_trip_id = trip_id
        if self.persistence and persist:
            db_trip_id = self.persistence.ensure_trip(spec, session_id=session_id, trip_id=trip_id)
            self.persistence.create_plan_run(run_id, db_trip_id, session_id, profile, spec, events)

        constraints = apply_profile(spec, profile).to_constraints()
        try:
            self._record_event(events, "research_plan", "Shared prefetch and planner research will run")
            initial_evidence = []
            execution_plan = None
            tool_call_registry = {}
            if use_execution_plan:
                execution_plan = self._build_global_execution_plan(
                    constraints,
                    plan_id=f"exec_global_{run_id}",
                )
                execution_result = self._execute_execution_plan(
                    execution_plan,
                    reuse_context=tool_call_registry,
                )
                tool_call_registry = execution_result.get("tool_calls") or tool_call_registry
                initial_evidence = execution_result.get("evidence") or []
                self._record_event(
                    events,
                    "execution_plan",
                    f"Global execution plan {execution_result.get('status')} with {len(execution_plan.tasks)} task(s)",
                )

            from travel_planning_agent.runtime.composition import build_planning_supervisor

            supervisor = build_planning_supervisor(
                self.llm,
                use_react_research=use_react_research,
            )

            state = supervisor.run_planning_loop(
                constraints,
                initial_evidence=initial_evidence,
                execution_plan=execution_plan,
                tool_call_registry=tool_call_registry,
            )
        except Exception as exc:
            state = PlanState(
                trip_id=db_trip_id or f"trip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
                status=TripStatus.FAILED,
                constraints=constraints,
                error=str(exc),
            )

        if db_trip_id:
            state.trip_id = db_trip_id

        self._record_event(events, "daily_draft", f"Generated {len(state.days)} day(s)")
        ensure_required_plan_content(state, spec)
        normalize_intercity_departure(state)
        normalize_final_day_departure(state)
        self._record_event(events, "product_normalize", "Required transport/lodging/meal/activity fields checked")

        state.validation = verify_whole_plan(state)
        from travel_planning_agent.core.repair_plan import build_repair_plan

        repair_plan = build_repair_plan(
            state.validation.blocking_failures,
            state.validation.warnings,
        )
        state.module_context["repair_plan"] = repair_plan
        self._record_event(events, "repair_plan", f"{repair_plan['status']} with {len(repair_plan['tasks'])} task(s)")
        state.status = self._final_status_for_state(state)
        self._record_event(events, "whole_plan_verify", "Whole-plan verification completed")

        plan_data = self._plan_data_from_state(state, profile=profile)
        verification = self._verification_to_dict(state.validation)

        plan_version = None
        if self.persistence and persist and db_trip_id:
            plan_version = self.persistence.persist_plan(
                db_trip_id,
                plan_data,
                verification,
                activate=activate_plan,
                trip_status=state.status.value,
            )
            self.persistence.persist_evidence(db_trip_id, state)
            self.persistence.finish_plan_run(run_id, state.status.value, events, plan_version)

        return {
            "run_id": run_id,
            "trip_id": state.trip_id,
            "state": state,
            "plan_data": plan_data,
            "verification": verification,
            "plan_version": plan_version,
            "events": events,
        }

    def _build_global_execution_plan(self, constraints, plan_id: str):
        return build_global_execution_plan(constraints, plan_id=plan_id)

    def _execute_execution_plan(self, execution_plan, reuse_context=None):
        return execute_execution_plan(execution_plan, reuse_context=reuse_context)

    def _final_status_for_state(self, state: PlanState) -> TripStatus:
        validation = state.validation
        has_verification_failure = bool(
            validation and (not validation.overall_pass or validation.blocking_failures)
        )
        return TripStatus.FAILED if state.error or has_verification_failure else TripStatus.COMPLETED

    def _record_event(self, events: list[dict], stage: str, message: str) -> None:
        record_event(events, stage, message)

    def _plan_data_from_state(self, state: PlanState, profile: str = "default") -> dict:
        return plan_data_from_state(state, profile=profile)

    def _verification_to_dict(self, verification) -> Optional[dict]:
        return verification_to_dict(verification)


def apply_profile(spec: TripSpec, profile: str) -> TripSpec:
    adjusted = copy.deepcopy(spec)
    if profile == "relaxed":
        adjusted.pace = "slow"
        adjusted.budget = round(spec.budget * 0.95)
        return adjusted
    if profile == "classic":
        adjusted.pace = "moderate"
        return adjusted
    if profile == "food":
        adjusted.food_preference = (adjusted.food_preference + " 本地特色餐饮、小吃街、老字号").strip()
        adjusted.must_have = list(dict.fromkeys([*adjusted.must_have, "本地美食"]))
        return adjusted
    if profile == "economy":
        adjusted.budget = round(spec.budget * 0.75)
        adjusted.pace = "slow" if spec.pace != "fast" else "moderate"
        return adjusted
    return adjusted


def record_event(events: list[dict], stage: str, message: str) -> None:
    events.append({"stage": stage, "message": message, "ts": datetime.now().isoformat()})


def ensure_required_plan_content(state: PlanState, spec: TripSpec) -> None:
    existing = {d.day_number: d for d in state.days}
    for day_num in range(1, max(spec.days, 1) + 1):
        if day_num not in existing:
            day = ItineraryDay(
                day_id=f"{state.trip_id}_day_{day_num}",
                day_number=day_num,
                theme=f"{spec.destination}第{day_num}天",
            )
            state.days.append(day)
            existing[day_num] = day

        day = existing[day_num]
        if not day.theme:
            day.theme = f"{spec.destination}第{day_num}天"

        for seg in day.segments:
            if seg.type in (SegmentType.ACTIVITY, SegmentType.ACCOMMODATION) and not seg.location:
                seg.location = Location(name=seg.title or spec.destination, city=spec.destination)
            if not seg.estimated_cost:
                seg.estimated_cost = Cost(amount=0)

        if day_num == 1 and not any(s.type == SegmentType.TRANSPORT for s in day.segments):
            title = f"{spec.origin or '出发地'}前往{spec.destination}" if spec.origin else f"抵达{spec.destination}"
            day.segments.insert(0, _make_segment(state.trip_id, day_num, SegmentType.TRANSPORT, title, "08:00", "10:00", spec.destination, 0, "morning"))

        if not any(s.type == SegmentType.MEAL for s in day.segments):
            day.segments.append(_make_segment(state.trip_id, day_num, SegmentType.MEAL, f"{spec.destination}当地餐食", "12:00", "13:00", spec.destination, 80, "afternoon"))

        if not any(s.type == SegmentType.ACTIVITY for s in day.segments):
            day.segments.append(_make_segment(state.trip_id, day_num, SegmentType.ACTIVITY, f"{spec.destination}核心景点游览", "14:00", "16:00", spec.destination, 0, "afternoon"))

        if day_num < spec.days and not any(s.type == SegmentType.ACCOMMODATION for s in day.segments):
            day.segments.append(_make_segment(state.trip_id, day_num, SegmentType.ACCOMMODATION, f"{spec.destination}住宿安排", "20:00", "08:00", spec.destination, 400, "evening"))

        if day_num == spec.days and not any(_is_final_return_transport(s, state.constraints) for s in day.segments):
            title = f"{spec.destination}返回{spec.origin}" if spec.origin else f"离开{spec.destination}返程"
            day.segments.append(_make_segment(state.trip_id, day_num, SegmentType.TRANSPORT, title, "17:00", "19:00", spec.destination, 0, "evening"))

        day.segments.sort(key=lambda s: s.start_time or "")

    state.days.sort(key=lambda d: d.day_number)
    _ensure_required_interests(state, spec.must_have or [], spec.destination)


def _make_segment(trip_id: str, day_num: int, seg_type: SegmentType, title: str, start: str, end: str, city: str, cost: float, module: str) -> Segment:
    return Segment(
        segment_id=make_segment_id(trip_id, title, start, end, day_num),
        type=seg_type,
        title=title,
        start_time=start,
        end_time=end,
        location=Location(name=title, city=city) if seg_type in (SegmentType.ACTIVITY, SegmentType.ACCOMMODATION) else None,
        estimated_cost=Cost(amount=cost),
        tags=[seg_type.value],
        module=module,
        note="系统补齐的必要规划项",
    )


def _ensure_required_interests(state: PlanState, required: list[str], city: str) -> None:
    required_items = [item for item in required if _is_required_interest(item)]
    if not required_items:
        return

    first_day = state.days[0] if state.days else None
    for item in required_items:
        if _plan_contains_interest(state, item):
            continue

        replacement = _find_optional_activity(state, required_items)
        if replacement:
            replacement.title = item
            replacement.location = Location(name=item, city=city)
            replacement.estimated_cost = replacement.estimated_cost or Cost(amount=0)
            replacement.tags = sorted(set([*replacement.tags, "required", "must_have"]))
            replacement.note = _append_note(replacement.note, "用户明确要求必去")
            continue

        if first_day:
            first_day.segments.append(_make_segment(
                state.trip_id,
                first_day.day_number,
                SegmentType.ACTIVITY,
                item,
                "14:00",
                "16:00",
                city,
                0,
                "afternoon",
            ))
            first_day.segments[-1].tags.extend(["required", "must_have"])
            first_day.segments[-1].note = "用户明确要求必去"
            first_day.segments.sort(key=lambda s: s.start_time or "")


def _find_optional_activity(state: PlanState, required_items: list[str]) -> Optional[Segment]:
    for day in state.days:
        for seg in day.segments:
            if seg.type != SegmentType.ACTIVITY:
                continue
            text = _segment_text(seg)
            if any(_text_matches_interest(text, item) for item in required_items):
                continue
            return seg
    return None


def _plan_contains_interest(state: PlanState, item: str) -> bool:
    return any(
        _text_matches_interest(_segment_text(seg), item)
        for day in state.days
        for seg in day.segments
    )


def _segment_text(seg: Segment) -> str:
    location_name = seg.location.name if seg.location else ""
    return " ".join([seg.title or "", seg.note or "", location_name or ""])


def _text_matches_interest(text: str, item: str) -> bool:
    normalized_text = _normalize_interest_text(text)
    normalized_item = _normalize_interest_text(item)
    if not normalized_text or not normalized_item:
        return False
    if normalized_item in normalized_text or normalized_text in normalized_item:
        return True
    tokens = [t for t in re.split(r"(纪念馆|博物馆|公园|寺|院|塔|湖|街|山|城|园)", item) if t]
    important = [_normalize_interest_text(t) for t in tokens if len(_normalize_interest_text(t)) >= 2]
    return bool(important) and all(token in normalized_text for token in important)


def _normalize_interest_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _is_required_interest(item: str) -> bool:
    text = (item or "").strip()
    broad_categories = {"文化", "自然", "美食", "购物", "历史", "艺术", "户外", "休闲", "夜景", "亲子", "拍照"}
    return bool(text) and text not in broad_categories


def _append_note(note: str, addition: str) -> str:
    if not note:
        return addition
    if addition in note:
        return note
    return f"{note}；{addition}"


def normalize_intercity_departure(state: PlanState) -> None:
    if not state.days or not state.constraints:
        return

    constraints = state.constraints
    origin = (constraints.origin or "").strip()
    destination = (constraints.destination or "").strip()
    if not origin or not destination or origin == destination:
        return

    first_day = next((day for day in state.days if day.day_number == 1), state.days[0])
    transport = next(
        (seg for seg in first_day.segments if _is_intercity_departure_transport(seg, constraints)),
        None,
    )
    if not transport:
        return

    transport.title = _format_intercity_departure_title(transport, constraints)
    transport.tags = sorted(set([*list(transport.tags or []), "intercity", "arrival"]))
    _shift_segments_after_arrival(first_day, transport)
    first_day.segments.sort(key=lambda seg: seg.start_time or "")


def _is_intercity_departure_transport(seg: Segment, constraints: Constraints) -> bool:
    if seg.type != SegmentType.TRANSPORT:
        return False
    text = f"{seg.title or ''} {seg.note or ''}"
    origin = (constraints.origin or "").strip()
    destination = (constraints.destination or "").strip()
    has_route = bool(origin and destination and origin in text and destination in text)
    has_big_transport = bool(_extract_train_no(text) or _extract_flight_no(text)) or any(
        token in text for token in ("高铁", "动车", "列车", "火车", "航班", "飞机", "机场")
    )
    prefers_big_transport = any(
        token in (constraints.transport_mode or "")
        for token in ("高铁", "动车", "火车", "飞机", "航班")
    )
    return has_route or (has_big_transport and prefers_big_transport)


def _format_intercity_departure_title(seg: Segment, constraints: Constraints) -> str:
    text = f"{seg.title or ''} {seg.note or ''}"
    origin = (constraints.origin or "出发地").strip()
    destination = (constraints.destination or "目的地").strip()
    train_no = _extract_train_no(text)
    if train_no:
        return f"乘坐{train_no}次列车 {origin} → {destination}"
    flight_no = _extract_flight_no(text)
    if flight_no:
        return f"乘坐{flight_no}航班 {origin} → {destination}"
    mode = (constraints.transport_mode or "").strip()
    if not mode:
        mode = "飞机" if any(token in text for token in ("航班", "飞机", "机场")) else "高铁"
    return f"乘坐{mode} {origin} → {destination}"


def _extract_train_no(text: str) -> str:
    match = re.search(r"([GDCZKT]\d{1,5})", text or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _extract_flight_no(text: str) -> str:
    match = re.search(r"([A-Z]{2}\d{3,4})", text or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _shift_segments_after_arrival(day: ItineraryDay, arrival: Segment) -> None:
    arrival_end = _time_to_minutes(arrival.end_time or "")
    if arrival_end is None:
        return

    cursor = arrival_end + 30
    for seg in sorted(day.segments, key=lambda item: item.start_time or ""):
        if seg is arrival or seg.type == SegmentType.TRANSPORT:
            continue
        start = _time_to_minutes(seg.start_time or "")
        end = _time_to_minutes(seg.end_time or "")
        if start is None or end is None:
            continue
        if end < start:
            end += 24 * 60
        if start >= cursor:
            cursor = max(cursor, end + 10)
            continue

        duration = max(end - start, 30)
        seg.start_time = _minutes_to_time(cursor)
        seg.end_time = _minutes_to_time(cursor + duration)
        cursor += duration + 10


def _minutes_to_time(value: int) -> str:
    value = value % (24 * 60)
    return f"{value // 60:02d}:{value % 60:02d}"


def _segment_attention(segment: Segment) -> str:
    note = (segment.note or "").strip()
    if note and not _is_internal_note(note):
        return note
    if segment.type == SegmentType.TRANSPORT and _is_big_transport_segment(segment):
        return "请以实际出票信息为准，提前确认出发站、检票口和到站交通。"
    return ""


def _is_internal_note(note: str) -> bool:
    return any(
        token in note
        for token in (
            "系统补齐",
            "用户明确要求",
            "根据用户修订",
        )
    )


def _is_big_transport_segment(segment: Segment) -> bool:
    text = f"{segment.title or ''} {segment.note or ''}"
    tags = set(segment.tags or [])
    return bool({"intercity", "arrival", "return"} & tags) or bool(_extract_train_no(text) or _extract_flight_no(text)) or any(
        token in text for token in ("高铁", "动车", "列车", "火车", "航班", "飞机", "机场")
    )


def normalize_final_day_departure(state: PlanState) -> None:
    if not state.days:
        return

    constraints = state.constraints
    expected_days = constraints.days if constraints else max(d.day_number for d in state.days)
    last_day = next((d for d in state.days if d.day_number == expected_days), state.days[-1])

    return_indices = [
        idx for idx, seg in enumerate(last_day.segments)
        if _is_final_return_transport(seg, constraints)
    ]
    final_return_idx = return_indices[-1] if return_indices else None

    cleaned = []
    for idx, seg in enumerate(last_day.segments):
        if seg.type == SegmentType.ACCOMMODATION:
            continue
        if final_return_idx is not None and idx > final_return_idx:
            continue
        if final_return_idx is not None and idx < final_return_idx and _is_hotel_return_transport(seg, constraints):
            continue
        cleaned.append(seg)

    last_day.segments = cleaned
    last_day.segments.sort(key=lambda s: s.start_time or "")


def _is_final_return_transport(seg: Segment, constraints: Optional[Constraints]) -> bool:
    if seg.type != SegmentType.TRANSPORT:
        return False
    text = f"{seg.title or ''} {seg.note or ''}"
    origin = constraints.origin if constraints else ""
    destination = constraints.destination if constraints else ""

    if "返程" in text or "离开" in text:
        return True
    if origin and origin in text and any(token in text for token in ("返回", "回", "前往", "去", "到", "飞往", "乘坐")):
        return True
    if destination and origin and destination in text and origin in text:
        return True
    if "地铁站" in text and not origin:
        return False
    return any(token in text for token in ("高铁", "动车", "火车", "航班", "飞机", "机场", "火车站", "高铁站", "客运站", "码头")) and any(
        token in text for token in ("返程", "离开", "返回", "前往", "乘坐")
    )


def _is_hotel_return_transport(seg: Segment, constraints: Optional[Constraints]) -> bool:
    if seg.type != SegmentType.TRANSPORT:
        return False
    text = f"{seg.title or ''} {seg.note or ''}"
    if _is_final_return_transport(seg, constraints):
        return False
    return any(token in text for token in ("返回", "回到", "回")) and any(
        token in text for token in ("酒店", "饭店", "宾馆", "民宿", "住宿")
    )


def verify_whole_plan(state: PlanState) -> VerificationReport:
    report = run_rule_engine(state)
    failures = []
    warnings = []

    constraints = state.constraints
    expected_days = constraints.days if constraints else len(state.days)
    day_numbers = {d.day_number for d in state.days}
    for day_num in range(1, expected_days + 1):
        if day_num not in day_numbers:
            failures.append({"rule_id": "W01", "detail": f"缺少 Day {day_num}"})

    for day in state.days:
        types = {s.type for s in day.segments}
        required_types = [
            (SegmentType.MEAL, "餐饮"),
            (SegmentType.ACTIVITY, "活动"),
        ]
        if day.day_number < expected_days:
            required_types.append((SegmentType.ACCOMMODATION, "住宿"))
        for required, label in required_types:
            if required not in types:
                failures.append({"rule_id": "W02", "detail": f"Day {day.day_number} 缺少{label}"})

    if state.days and not any(s.type == SegmentType.TRANSPORT for s in state.days[0].segments):
        failures.append({"rule_id": "W03", "detail": "第一天缺少到达交通"})
    if state.days and not any(
        _is_final_return_transport(s, constraints)
        for s in state.days[-1].segments
    ):
        failures.append({"rule_id": "W04", "detail": "最后一天缺少返程交通"})

    if constraints:
        for item in constraints.interests or []:
            if _is_required_interest(item) and not _plan_contains_interest(state, item):
                failures.append({"rule_id": "W08", "detail": f"缺少用户必去项：{item}"})

    route_failures, route_warnings = _verify_route_buffers(state)
    failures.extend(route_failures)
    warnings.extend(route_warnings)

    whole_checks = [
        {"rule_id": failure.get("rule_id"), "result": "FAIL", "detail": failure.get("detail")}
        for failure in failures
    ]
    if not whole_checks:
        whole_checks.append({"rule_id": "W00", "result": "PASS", "detail": "产品级必要规划项完整"})

    report.whole_plan_checks = whole_checks
    report.blocking_failures = failures
    report.warnings = warnings
    report.overall_pass = report.overall_pass and not failures
    return report


def _verify_route_buffers(state: PlanState) -> tuple[list[dict], list[dict]]:
    failures = []
    warnings = []
    for day in state.days:
        segments = sorted(day.segments, key=lambda s: s.start_time or "")
        for seg in segments:
            if seg.type != SegmentType.TRANSPORT:
                continue
            required = _extract_route_minutes(" ".join([seg.title or "", seg.note or ""]))
            allocated = _segment_duration_minutes(seg)
            if required is not None and allocated is not None and allocated < required:
                failures.append(
                    {
                        "rule_id": "W05",
                        "detail": f"Day {day.day_number} 交通段《{seg.title}》预留 {allocated} 分钟，少于路线用时约 {required} 分钟",
                        "affected_segments": [seg.segment_id],
                    }
                )
            if "步行" in (seg.title or "") and required is not None and required > 30:
                warnings.append(
                    {
                        "rule_id": "W06",
                        "detail": f"Day {day.day_number} 步行段《{seg.title}》约 {required} 分钟，可能偏长",
                        "affected_segments": [seg.segment_id],
                    }
                )

        for prev, nxt in zip(segments, segments[1:]):
            if not prev.end_time or not nxt.start_time:
                continue
            gap = _minutes_between(prev.end_time, nxt.start_time)
            if gap is None:
                continue
            if prev.type != SegmentType.TRANSPORT and nxt.type != SegmentType.TRANSPORT and _different_locations(prev, nxt) and gap < 10:
                warnings.append(
                    {
                        "rule_id": "W07",
                        "detail": f"Day {day.day_number}《{prev.title}》到《{nxt.title}》之间仅 {gap} 分钟，建议补充交通缓冲",
                        "affected_segments": [prev.segment_id, nxt.segment_id],
                    }
                )
    return failures, warnings


def _extract_route_minutes(text: str) -> Optional[int]:
    if not text:
        return None
    hour_match = re.search(r"约?(\d+)\s*小时(?:(\d+)\s*分钟)?", text)
    if hour_match:
        return int(hour_match.group(1)) * 60 + int(hour_match.group(2) or 0)
    minute_match = re.search(r"约?(\d+)\s*分钟", text)
    if minute_match:
        return int(minute_match.group(1))
    return None


def _segment_duration_minutes(seg: Segment) -> Optional[int]:
    if not seg.start_time or not seg.end_time:
        return None
    return _minutes_between(seg.start_time, seg.end_time)


def _minutes_between(start: str, end: str) -> Optional[int]:
    start_min = _time_to_minutes(start)
    end_min = _time_to_minutes(end)
    if start_min is None or end_min is None:
        return None
    if end_min < start_min:
        end_min += 24 * 60
    return end_min - start_min


def _time_to_minutes(value: str) -> Optional[int]:
    match = re.match(r"^(\d{1,2}):(\d{2})", value or "")
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _different_locations(a: Segment, b: Segment) -> bool:
    if not a.location or not b.location:
        return False
    return (a.location.name or "").strip() != (b.location.name or "").strip()


def plan_data_from_state(state: PlanState, profile: str = "default") -> dict:
    return {
        "profile": profile,
        "days": [
            {
                "day_id": day.day_id,
                "day_number": day.day_number,
                "theme": day.theme,
                "day_note": day.day_note,
                "segments": [
                    {
                        "segment_id": segment.segment_id,
                        "type": segment.type.value,
                        "title": segment.title,
                        "start_time": segment.start_time,
                        "end_time": segment.end_time,
                        "location": {"name": segment.location.name, "city": segment.location.city} if segment.location else None,
                        "estimated_cost": {"amount": segment.estimated_cost.amount, "currency": segment.estimated_cost.currency} if segment.estimated_cost else None,
                        "tags": segment.tags,
                        "evidence_ids": segment.evidence_ids,
                        "note": segment.note,
                        "attention": _segment_attention(segment),
                        "module": segment.module,
                    }
                    for segment in day.segments
                ],
            }
            for day in state.days
        ],
        "pins": [{"pin_id": pin.pin_id, "target_id": pin.target_id, "target_type": pin.target_type} for pin in state.pins],
        "assumptions": [{"assumption_id": assumption.assumption_id, "content": assumption.content, "status": assumption.status.value} for assumption in state.assumptions],
    }


def verification_to_dict(verification) -> Optional[dict]:
    if not verification:
        return None
    return {
        "overall_pass": verification.overall_pass,
        "rule_checks": [{"rule_id": rule.rule_id, "name": rule.name, "result": rule.result, "detail": rule.detail} for rule in verification.rule_checks],
        "semantic_checks": [{"check_id": check.check_id, "result": check.result, "detail": check.detail} for check in verification.semantic_checks],
        "risk_checks": [{"risk_id": risk.risk_id, "risk_type": risk.risk_type, "severity": risk.severity, "detail": risk.detail} for risk in verification.risk_checks],
        "whole_plan_checks": verification.whole_plan_checks,
        "blocking_failures": verification.blocking_failures,
        "warnings": verification.warnings,
        "correction_requests": verification.correction_requests,
    }
