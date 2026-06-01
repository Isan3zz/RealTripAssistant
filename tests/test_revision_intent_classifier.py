from travel_planning_agent.core.revision_intent_classifier import classify_revision_intent
from travel_planning_agent.llm import MockLLMClient


def _plan_data():
    return {
        "days": [
            {
                "day_number": 1,
                "theme": "到达日",
                "segments": [{"title": "西湖漫步", "type": "activity"}],
            },
            {
                "day_number": 2,
                "theme": "经典日",
                "segments": [
                    {"title": "雷峰塔", "type": "activity"},
                    {"title": "南宋御街", "type": "activity"},
                ],
            },
        ]
    }


def test_llm_classify_lighten_day():
    """LLM 可用时返回结构化 lighten_day intent。"""
    llm = MockLLMClient(mock_data={
        "is_revision": True,
        "intent_type": "lighten_day",
        "target_day": 2,
        "target_module": "afternoon",
        "target_segment": None,
        "scope_type": "day_module",
        "impact_level": "low",
        "confidence": 0.88,
        "clarification_needed": False,
        "clarification_question": "",
        "detail": "用户觉得第二天下午太累，希望减少活动量",
    })

    result = classify_revision_intent(llm, "第二天下午太累了，轻松一点", _plan_data(), {})

    assert result["is_revision"] is True
    assert result["intent_type"] == "lighten_day"
    assert result["target_day"] == 2
    assert result["_source"] == "llm"
    assert result["confidence"] == 0.88
    assert result["clarification_needed"] is False


def test_fallback_when_llm_is_none():
    """llm_client=None 时走规则 fallback。"""
    result = classify_revision_intent(None, "第三天太累了少走路", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"
    assert result["is_revision"] is True


def test_fallback_when_llm_returns_invalid_json():
    """LLM 返回非分类 JSON 时走规则 fallback。"""
    llm = MockLLMClient(mock_data={"days": [{"day_number": 1}]})

    result = classify_revision_intent(llm, "换掉雷峰塔", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"


def test_llm_failure_triggers_fallback():
    """LLM 返回 success=False 时走规则 fallback。"""
    from travel_planning_agent.llm import LLMResult

    class FailingLLM:
        def generate(self, system_prompt, user_message, tools=None):
            return LLMResult(success=False, error="timeout")

    result = classify_revision_intent(FailingLLM(), "不去雷峰塔了", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"


def test_missing_is_revision_triggers_fallback():
    """LLM 返回的 JSON 不含 is_revision → fallback。"""
    llm = MockLLMClient(mock_data={"some": "garbage"})

    result = classify_revision_intent(llm, "少走点路", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"


def test_is_revision_true_without_intent_type_triggers_fallback():
    """is_revision=true 但无 intent_type → fallback。"""
    llm = MockLLMClient(mock_data={"is_revision": True})

    result = classify_revision_intent(llm, "改一下", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"


def test_low_confidence_sets_classification_failed():
    """LLM 返回置信度 < 0.5 → classification_failed=True。"""
    llm = MockLLMClient(mock_data={
        "is_revision": True,
        "intent_type": None,
        "target_day": None,
        "target_module": None,
        "target_segment": None,
        "scope_type": "unknown",
        "impact_level": "high",
        "confidence": 0.45,
        "clarification_needed": True,
        "clarification_question": "你想改哪一天？",
        "detail": "",
    })

    result = classify_revision_intent(llm, "改一下", _plan_data(), {"last_trip_id": "t1"})

    assert result["classification_failed"] is True


def test_non_revision_message_returns_false():
    """纯聊天 → is_revision=false。"""
    llm = MockLLMClient(mock_data={
        "is_revision": False,
        "intent_type": None,
        "target_day": None,
        "target_module": None,
        "target_segment": None,
        "scope_type": "unknown",
        "impact_level": "high",
        "confidence": 0.95,
        "clarification_needed": False,
        "clarification_question": "",
        "detail": "",
    })

    result = classify_revision_intent(llm, "杭州天气怎么样", _plan_data(), {})

    assert result["is_revision"] is False


def test_change_return_time_alias_mapped():
    """规则 fallback 中 change_return_time → return_time_change。"""
    result = classify_revision_intent(None, "晚一点回去", _plan_data(), {"last_trip_id": "t1"})

    assert result["_source"] == "rules"
    if result["is_revision"]:
        assert result["intent_type"] != "change_return_time"
