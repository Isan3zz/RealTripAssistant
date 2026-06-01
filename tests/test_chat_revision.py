from types import SimpleNamespace

from travel_planning_agent.agent.revision import RevisionAgent
from travel_planning_agent.llm import LLMResult
from travel_planning_agent.core.plan_revision import (
    analyze_change_intent,
    apply_change_request_to_plan,
    apply_return_revision_to_plan,
    looks_like_plan_revision,
)


def test_chat_revision_detects_existing_plan_return_request():
    context = {"last_trip_id": "trip_1"}

    assert looks_like_plan_revision("我第二天下午就要回去", context) is True
    assert looks_like_plan_revision("第二天太累了，轻松一点", context) is True
    assert looks_like_plan_revision("第三天下雨的话换成室内", context) is True
    assert looks_like_plan_revision("预算降一点，保留必去景点", context) is True
    assert looks_like_plan_revision("预算多少合适", context) is False
    assert looks_like_plan_revision("我第二天下午就要回去", {}) is False


def test_return_revision_updates_existing_plan_without_new_intake():
    trip = SimpleNamespace(destination="南京", days=2)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = {
        "days": [
            {
                "day_number": 1,
                "theme": "抵达南京",
                "segments": [
                    {"segment_id": "d1a", "type": "activity", "title": "夫子庙", "start_time": "14:00", "end_time": "16:00"},
                    {"segment_id": "d1h", "type": "accommodation", "title": "入住南京金陵饭店", "start_time": "20:00", "end_time": "08:00"},
                ],
            },
            {
                "day_number": 2,
                "theme": "南京现代与历史交融之旅",
                "segments": [
                    {"segment_id": "breakfast", "type": "meal", "title": "早餐", "start_time": "07:00", "end_time": "08:00"},
                    {"segment_id": "activity", "type": "activity", "title": "总统府", "start_time": "09:00", "end_time": "11:00"},
                    {"segment_id": "hotel_return", "type": "transport", "title": "乘坐公交/地铁返回南京金陵饭店", "start_time": "18:10", "end_time": "18:40"},
                    {"segment_id": "old_return", "type": "transport", "title": "乘坐高铁从南京前往杭州（约2小时）", "start_time": "19:00", "end_time": "21:00", "estimated_cost": {"amount": 300, "currency": "CNY"}},
                    {"segment_id": "hotel", "type": "accommodation", "title": "入住杭州西湖国宾馆", "start_time": "22:00", "end_time": "23:00"},
                ],
            },
        ]
    }

    changed = apply_return_revision_to_plan(plan_data, trip, "我第二天下午就要回去", context)

    assert changed is True
    day2_segments = plan_data["days"][1]["segments"]
    titles = [s["title"] for s in day2_segments]
    assert "乘坐公交/地铁返回南京金陵饭店" not in titles
    assert "入住杭州西湖国宾馆" not in titles
    assert titles[-1] == "从南京返回杭州"
    assert day2_segments[-1]["start_time"] == "15:00"
    assert day2_segments[-1]["estimated_cost"]["amount"] == 300


class RecordingLLM:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def generate(self, system_prompt: str, user_message: str, tools=None):
        self.calls.append({"system": system_prompt, "user": user_message, "tools": tools})
        return LLMResult(success=True, data=self.data, text="")

    def generate_with_context(self, system_prompt: str, messages: list[dict], tools=None):
        raise AssertionError("RevisionAgent should use exactly one generate call")


def _sample_plan_data():
    return {
        "days": [
            {
                "day_number": 1,
                "theme": "初探南京",
                "segments": [
                    {"segment_id": "d1a", "type": "activity", "title": "夫子庙", "start_time": "16:00", "end_time": "18:00"},
                    {"segment_id": "d1h", "type": "accommodation", "title": "入住南京金陵饭店", "start_time": "21:30", "end_time": "00:00"},
                ],
            },
            {
                "day_number": 2,
                "theme": "南京现代与历史",
                "segments": [
                    {"segment_id": "breakfast", "type": "meal", "title": "早餐", "start_time": "07:00", "end_time": "08:00"},
                    {"segment_id": "lake", "type": "activity", "title": "玄武湖公园", "start_time": "08:50", "end_time": "11:00"},
                    {"segment_id": "lunch", "type": "meal", "title": "午餐", "start_time": "11:10", "end_time": "12:10"},
                    {"segment_id": "museum", "type": "activity", "title": "南京博物院", "start_time": "12:50", "end_time": "16:00"},
                    {"segment_id": "hotel_return", "type": "transport", "title": "乘坐公交/地铁返回南京金陵饭店", "start_time": "18:10", "end_time": "18:40"},
                    {"segment_id": "old_return", "type": "transport", "title": "乘坐高铁从南京前往杭州（约2小时）", "start_time": "19:00", "end_time": "21:00", "estimated_cost": {"amount": 300, "currency": "CNY"}},
                    {"segment_id": "hotel", "type": "accommodation", "title": "入住杭州西湖国宾馆", "start_time": "22:00", "end_time": "23:00"},
                ],
            },
            {
                "day_number": 3,
                "theme": "多余天",
                "segments": [{"segment_id": "d3a", "type": "activity", "title": "额外活动"}],
            },
        ]
    }


def test_revision_agent_uses_one_llm_call_without_tools():
    llm = RecordingLLM({
        "day_number": 2,
        "theme": "返程日前半日",
        "segments": [
            {"segment_id": "breakfast", "type": "meal", "title": "早餐", "start_time": "07:30", "end_time": "08:30"},
            {"segment_id": "return", "type": "transport", "title": "从南京返回杭州", "start_time": "15:00", "end_time": "17:00"},
        ],
    })
    agent = RevisionAgent(llm)

    result = agent.revise_day(
        plan_data=_sample_plan_data(),
        trip_info={"destination": "南京", "origin": "杭州"},
        intent={"type": "return_time_change", "target_day": 2, "return_start": "15:00", "return_end": "17:00"},
        evidence=[],
    )

    assert result["day_number"] == 2
    assert len(llm.calls) == 1
    assert llm.calls[0]["tools"] is None


def test_change_request_return_uses_llm_replacement_instead_of_cropping():
    trip = SimpleNamespace(destination="南京", days=3)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = _sample_plan_data()
    llm = RecordingLLM({
        "day_number": 2,
        "theme": "南京返程前轻量游",
        "segments": [
            {"segment_id": "breakfast_new", "type": "meal", "title": "酒店早餐", "start_time": "07:30", "end_time": "08:30"},
            {"segment_id": "activity_new", "type": "activity", "title": "南京大屠杀纪念馆", "start_time": "09:00", "end_time": "11:30"},
            {"segment_id": "lunch_new", "type": "meal", "title": "简餐", "start_time": "12:00", "end_time": "13:00"},
            {"segment_id": "return_new", "type": "transport", "title": "从南京返回杭州", "start_time": "15:00", "end_time": "17:00", "estimated_cost": {"amount": 300, "currency": "CNY"}},
        ],
    })

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "我第二天下午就要回去",
        context,
        RevisionAgent(llm),
    )

    assert changed is True
    assert [d["day_number"] for d in plan_data["days"]] == [1, 2]
    day2 = plan_data["days"][1]
    titles = [s["title"] for s in day2["segments"]]
    assert titles == ["酒店早餐", "南京大屠杀纪念馆", "简餐", "从南京返回杭州"]
    assert titles[-1] == "从南京返回杭州"
    assert "南京博物院" not in titles


def test_parsed_scope_return_revision_preserves_requested_time_window():
    trip = SimpleNamespace(destination="南京", days=2)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = _sample_plan_data()

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "我第二天18点回去",
        context,
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "target_day": 2,
            "change_type": "return_time_change",
            "scope_type": "day",
            "return_start": "18:00",
            "return_end": "20:00",
        },
    )

    assert changed is True
    day2_segments = plan_data["days"][1]["segments"]
    return_segments = [seg for seg in day2_segments if "return" in (seg.get("tags") or [])]
    assert return_segments[-1]["start_time"] == "18:00"
    assert return_segments[-1]["end_time"] == "20:00"


def test_analyze_change_intent_preserves_parsed_return_time_window():
    intent = analyze_change_intent(
        "我第二天18点回去",
        {"days": [{"day_number": 1}, {"day_number": 2}]},
        parsed_scope={
            "matched": True,
            "target_day": 2,
            "change_type": "return_time_change",
            "scope_type": "day",
            "return_start": "18:00",
            "return_end": "20:00",
        },
    )

    assert intent["return_start"] == "18:00"
    assert intent["return_end"] == "20:00"


def test_change_request_replace_activity_uses_controlled_research_tool():
    trip = SimpleNamespace(destination="南京", days=2)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = _sample_plan_data()
    calls = []

    def fake_tool(name, args):
        calls.append((name, args))
        return SimpleNamespace(status="success", data="南京大屠杀纪念馆：开放时间 08:30-17:00，免费", evidence=[{"claim": "纪念馆信息"}])

    llm = RecordingLLM({
        "day_number": 2,
        "theme": "南京历史记忆",
        "segments": [
            {"segment_id": "breakfast", "type": "meal", "title": "早餐", "start_time": "07:30", "end_time": "08:30"},
            {"segment_id": "memorial", "type": "activity", "title": "南京大屠杀纪念馆", "start_time": "09:00", "end_time": "11:30"},
            {"segment_id": "lunch", "type": "meal", "title": "午餐", "start_time": "12:00", "end_time": "13:00"},
        ],
    })

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "第二天别去玄武湖了，换成南京大屠杀纪念馆",
        context,
        RevisionAgent(llm),
        tool_executor=fake_tool,
    )

    assert changed is True
    assert calls == [("search_poi", {"destination": "南京", "category": "cultural", "context": "南京大屠杀纪念馆"})]
    assert any("南京大屠杀纪念馆" in s["title"] for s in plan_data["days"][1]["segments"])


def test_analyze_change_intent_detects_lighter_day():
    intent = analyze_change_intent("第二天太累了，轻松一点", {"days": [{"day_number": 1}, {"day_number": 2}]})

    assert intent["type"] == "lighten_day"
    assert intent["target_day"] == 2
    assert intent["requires_tools"] is False


def test_analyze_change_intent_detects_rainy_day():
    intent = analyze_change_intent("第三天下雨的话换成室内", {"days": [{"day_number": 1}, {"day_number": 2}, {"day_number": 3}]})

    assert intent["type"] == "rainy_day_backup"
    assert intent["target_day"] == 3
    assert intent["requires_tools"] is True


def test_rainy_day_revision_collects_indoor_poi_evidence():
    trip = SimpleNamespace(destination="南京", days=3)
    plan_data = _sample_plan_data()
    calls = []

    class RecordingRevisionAgent:
        def __init__(self):
            self.intent = None
            self.evidence = None

        def revise_day(self, plan_data, trip_info, intent, evidence):
            self.intent = intent
            self.evidence = evidence
            return {
                "day_number": 3,
                "theme": "雨天室内备选",
                "segments": [
                    {"segment_id": "indoor", "type": "activity", "title": "南京博物院", "start_time": "09:00", "end_time": "11:30"},
                ],
            }

    def fake_tool(name, args):
        calls.append((name, args))
        return SimpleNamespace(status="success", data="南京博物院：室内展览", evidence=[{"claim": "室内展览"}])

    agent = RecordingRevisionAgent()
    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "第三天下雨的话换成室内",
        {},
        agent,
        tool_executor=fake_tool,
    )

    assert changed is True
    assert agent.intent["type"] == "rainy_day_backup"
    assert calls == [("search_poi", {"destination": "南京", "category": "cultural", "context": "室内 博物馆 展览 商场"})]
    assert agent.evidence[0]["status"] == "success"
def test_change_request_lighten_only_replaces_target_module():
    trip = SimpleNamespace(destination="厦门", days=3)
    context = {"extracted": {"origin": "杭州"}}
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "theme": "厦门深度游",
                "segments": [
                    {"segment_id": "m1", "type": "activity", "title": "南普陀", "start_time": "09:00", "end_time": "11:00", "module": "morning"},
                    {"segment_id": "a1", "type": "activity", "title": "环岛路骑行", "start_time": "13:00", "end_time": "16:00", "module": "afternoon"},
                    {"segment_id": "e1", "type": "meal", "title": "海鲜晚餐", "start_time": "18:00", "end_time": "19:00", "module": "evening"},
                ],
            }
        ]
    }
    llm = RecordingLLM({
        "day_number": 2,
        "theme": "厦门轻松下午",
        "segments": [
            {"segment_id": "a2", "type": "activity", "title": "咖啡馆休息", "start_time": "14:00", "end_time": "15:30", "module": "afternoon"},
        ],
    })

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "第二天下午轻松一点",
        context,
        RevisionAgent(llm),
        parsed_scope={
            "matched": True,
            "target_day": 2,
            "target_module": "afternoon",
            "target_segment": None,
            "change_type": "lighten_day",
            "clarification_needed": False,
            "clarification_question": "",
        },
    )

    assert changed is True
    titles = [seg["title"] for seg in plan_data["days"][0]["segments"]]
    assert titles == ["南普陀", "咖啡馆休息", "海鲜晚餐"]


def test_change_request_remove_unique_segment_only_drops_that_segment():
    trip = SimpleNamespace(destination="厦门", days=2)
    plan_data = {
        "days": [
            {
                "day_number": 2,
                "segments": [
                    {"segment_id": "a1", "type": "activity", "title": "鼓浪屿", "start_time": "09:00", "end_time": "11:00", "module": "morning"},
                    {"segment_id": "a2", "type": "activity", "title": "环岛路", "start_time": "13:00", "end_time": "15:00", "module": "afternoon"},
                ],
            }
        ]
    }

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "把鼓浪屿换掉",
        {},
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "target_day": None,
            "target_module": None,
            "target_segment": "鼓浪屿",
            "change_type": "remove_segment",
            "clarification_needed": False,
            "clarification_question": "",
        },
    )

    assert changed is True
    assert [seg["title"] for seg in plan_data["days"][0]["segments"]] == ["环岛路"]


def test_apply_change_request_to_plan_appends_new_day_when_strategy_is_append():
    trip = SimpleNamespace(destination="厦门", days=2)
    plan_data = {
        "days": [
            {"day_number": 1, "theme": "第一天", "segments": [{"title": "中山路", "type": "activity"}]},
            {"day_number": 2, "theme": "返程日", "segments": [{"title": "从厦门返回杭州", "type": "transport", "tags": ["return"]}]},
        ]
    }
    new_day = {"day_number": 3, "theme": "新增一天", "segments": [{"title": "植物园", "type": "activity"}]}

    changed = apply_change_request_to_plan(
        plan_data,
        trip,
        "我还能多玩一天",
        {},
        revision_agent=None,
        parsed_scope={
            "matched": True,
            "change_type": "append_day",
            "scope_type": "append",
            "impact_level": "high",
        },
        append_day=new_day,
    )

    assert changed is True
    assert [day["day_number"] for day in plan_data["days"]] == [1, 2, 3]
