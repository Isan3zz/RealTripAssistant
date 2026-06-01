from travel_planning_agent.core.context_ledger import (
    build_context_pack,
    compact_plan_for_context,
    record_active_constraints,
    record_initial_constraints,
    record_revision_note,
)


def test_records_initial_constraints_once_and_active_constraints_updates():
    context = {}
    first = {
        "origin": "杭州",
        "destination": "南京",
        "start_date": "2026-05-18",
        "days": 2,
        "budget": 2000,
        "transport_mode": "train",
        "interests": ["玄武湖"],
    }
    updated = dict(first, budget=1500, pace="slow")

    record_initial_constraints(context, first, "明天杭州去南京两天", "trace_first")
    record_active_constraints(context, first, "明天杭州去南京两天", "trace_first")
    record_initial_constraints(context, updated, "预算降到1500", "trace_second")
    record_active_constraints(context, updated, "预算降到1500", "trace_second")

    ledger = context["context_ledger"]
    assert ledger["schema_version"] == 1
    assert ledger["initial_constraints"]["budget"] == 2000
    assert ledger["initial_constraints"]["destination"] == "南京"
    assert ledger["active_constraints"]["budget"] == 1500
    assert ledger["active_constraints"]["pace"] == "slow"
    assert ledger["source_refs"]["initial_trace_id"] == "trace_first"
    assert ledger["source_refs"]["active_trace_id"] == "trace_second"


def test_context_pack_keeps_current_message_initial_constraints_and_full_compact_plan():
    context = {}
    initial = {
        "origin": "杭州",
        "destination": "南京",
        "start_date": "2026-05-18",
        "days": 2,
        "budget": 2000,
        "interests": ["玄武湖"],
    }
    plan_data = {
        "profile": "slow",
        "days": [
            {
                "day_number": 1,
                "theme": "玄武湖与城市初见",
                "segments": [
                    {
                        "segment_id": "seg_train",
                        "type": "transport",
                        "title": "杭州东到南京南",
                        "start_time": "08:00",
                        "end_time": "09:30",
                        "estimated_cost": {"amount": 200, "currency": "CNY"},
                        "note": "高铁",
                    },
                    {
                        "segment_id": "seg_lake",
                        "type": "activity",
                        "title": "玄武湖散步",
                        "start_time": "10:20",
                        "end_time": "12:00",
                        "estimated_cost": {"amount": 0, "currency": "CNY"},
                    },
                ],
            },
            {
                "day_number": 2,
                "theme": "老城慢游",
                "segments": [
                    {
                        "segment_id": "seg_museum",
                        "type": "activity",
                        "title": "南京博物院",
                        "start_time": "09:30",
                        "end_time": "11:30",
                    }
                ],
            },
        ],
    }
    context["messages"] = [
        {"role": "user", "content": "明天杭州去南京两天"},
        {"role": "assistant", "content": "✅ 行程规划完成！\n很长的展示文本", "type": "plan"},
    ]
    context["trace_ids"] = ["trace_first"]
    record_initial_constraints(context, initial, "明天杭州去南京两天", "trace_first")
    record_active_constraints(context, dict(initial, pace="slow"), "轻松一点", "trace_second")

    pack = build_context_pack(
        context,
        current_message="第二天太累了，轻松一点",
        active_plan=plan_data,
        purpose="revision",
    )

    assert pack["current_message"] == "第二天太累了，轻松一点"
    assert pack["initial_constraints"]["budget"] == 2000
    assert pack["active_constraints"]["pace"] == "slow"
    assert len(pack["full_plan_compact"]["days"]) == 2
    assert pack["full_plan_compact"]["days"][0]["segments"][0]["segment_id"] == "seg_train"
    assert pack["full_plan_compact"]["days"][0]["segments"][1]["title"] == "玄武湖散步"
    assert pack["full_plan_compact"]["totals"]["segments"] == 3
    assert pack["recent_messages"][-1]["content"] == "[plan_result omitted; see full_plan_compact]"


def test_context_pack_omits_raw_messages_trace_and_evidence_payloads_by_default():
    context = {
        "messages": [{"role": "user", "content": f"message {i}"} for i in range(20)],
        "trace_ids": [f"trace_{i}" for i in range(30)],
        "evidence": [
            {
                "evidence_id": "ev_1",
                "claim": "玄武湖免费开放",
                "payload": {"raw_tool_output": "large payload should not enter context"},
            }
        ],
    }

    pack = build_context_pack(context, current_message="继续优化", active_plan=None)

    assert [msg["content"] for msg in pack["recent_messages"]] == [f"message {i}" for i in range(14, 20)]
    assert pack["trace_refs"] == [f"trace_{i}" for i in range(20, 30)]
    assert pack["evidence_refs"] == [{"evidence_id": "ev_1", "claim": "玄武湖免费开放"}]
    assert "raw_tool_output" not in str(pack)
    assert pack["omitted"]["messages"] == 14
    assert pack["omitted"]["trace_ids"] == 20


def test_revision_notes_are_bounded_and_ordered():
    context = {}

    for i in range(15):
        record_revision_note(
            context,
            message=f"第{i}次修改",
            trace_id=f"trace_{i}",
            trip_id="trip_1",
            plan_version=i + 1,
        )

    notes = context["context_ledger"]["revision_notes"]
    assert len(notes) == 10
    assert notes[0]["message"] == "第5次修改"
    assert notes[-1]["trace_id"] == "trace_14"


def test_compact_plan_for_context_keeps_cost_shape_and_all_segments():
    plan_data = {
        "plan_id": "plan_1",
        "version": 3,
        "days": [
            {
                "day_number": 1,
                "theme": "第一天",
                "day_note": "小雨",
                "segments": [
                    {
                        "segment_id": "a",
                        "type": "meal",
                        "title": "早餐",
                        "start_time": "08:00",
                        "end_time": "08:30",
                        "estimated_cost": {"amount": 30, "currency": "CNY"},
                        "explanation": {"why": "verbose text should be omitted"},
                    }
                ],
            }
        ],
    }

    compact = compact_plan_for_context(plan_data)

    assert compact == {
        "plan_id": "plan_1",
        "version": 3,
        "profile": None,
        "days": [
            {
                "day_number": 1,
                "theme": "第一天",
                "day_note": "小雨",
                "segments": [
                    {
                        "segment_id": "a",
                        "type": "meal",
                        "title": "早餐",
                        "start_time": "08:00",
                        "end_time": "08:30",
                        "estimated_cost": {"amount": 30, "currency": "CNY"},
                        "note": None,
                        "tags": [],
                    }
                ],
            }
        ],
        "totals": {"days": 1, "segments": 1, "estimated_cost": 30},
    }
