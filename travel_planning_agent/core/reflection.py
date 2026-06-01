"""
core/reflection.py — Reflection Agent（异步偏好提取）

行程完成后异步执行，分析用户行为模式并写入长期偏好。
不阻塞主规划流程。
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from travel_planning_agent.types import PlanState, ItineraryDay, SegmentType

logger = logging.getLogger(__name__)


# ── 提取维度的 key ──

_PACE_KEY = "pace"
_INTERESTS_KEY = "interests"
_BUDGET_KEY = "budget_level"
_STYLE_KEY = "travel_style"

_PREFERENCE_KEYS = [_PACE_KEY, _INTERESTS_KEY, _BUDGET_KEY, _STYLE_KEY]


def run_reflection(state: PlanState, db_session_factory=None) -> list[dict]:
    """
    Reflection Agent 主入口。

    参数:
        state: 已完成的 PlanState
        db_session_factory: 可选的 ORM session factory（无则只返回提取结果不落地）

    返回:
        提取出的偏好信号列表
    """
    if state.status.value != "completed":
        logger.warning("Reflection 跳过：行程状态 %s 不是 completed", state.status.value)
        return []

    signals = _extract_signals(state)
    if not signals:
        logger.info("Reflection 未提取到有效偏好信号")
        return []

    logger.info("Reflection 提取到 %d 条偏好信号", len(signals))

    # 如果有 DB，合并并保存
    if db_session_factory:
        user_id = _resolve_user_id(state.trip_id, db_session_factory)
        if user_id:
            _merge_to_db(signals, user_id, db_session_factory)
        else:
            logger.warning("Reflection 无法确定 trip 所属用户，跳过 DB 写入")
    else:
        logger.info("Reflection 无 DB session，信号仅返回不落地")

    return signals


# ═══════════════════════════════════════════════════════
#  信号提取
# ═══════════════════════════════════════════════════════

def _extract_signals(state: PlanState) -> list[dict]:
    """从完成的行程中提取偏好信号。"""
    signals = []
    c = state.constraints
    if not c or not state.days:
        return signals

    # 1. pace: 从实际行程密度推断
    pace_signal = _extract_pace(state)
    if pace_signal:
        signals.append(pace_signal)

    # 2. interests: 从实际选择的景点类型推断
    interest_signal = _extract_interests(state)
    if interest_signal:
        signals.append(interest_signal)

    # 3. budget: 从预算/实际花费推断
    budget_signal = _extract_budget(state)
    if budget_signal:
        signals.append(budget_signal)

    # 4. travel_style: 行程风格
    style_signal = _extract_style(state)
    if style_signal:
        signals.append(style_signal)

    return signals


def _extract_pace(state: PlanState) -> Optional[dict]:
    """从行程密度推断节奏偏好。"""
    total_activities = 0
    total_days = len(state.days)
    if total_days == 0:
        return None

    for day in state.days:
        for seg in day.segments:
            if seg.type == SegmentType.ACTIVITY:
                total_activities += 1

    avg_per_day = total_activities / total_days
    pace_label = "slow" if avg_per_day < 2 else "moderate" if avg_per_day < 4 else "fast"
    pace_value = state.constraints.pace if state.constraints else "moderate"

    return {
        "key": _PACE_KEY,
        "base_value": pace_value,
        "confidence": _confidence_from_occurrences(total_days, 3),
        "context": _build_context(state),
        "signal_detail": f"日均活动数 {avg_per_day:.1f} → 推断节奏 {pace_label}",
    }


def _extract_interests(state: PlanState) -> Optional[dict]:
    """从实际 segment tag 分布推断兴趣偏好。"""
    tag_counts: dict[str, int] = {}
    for day in state.days:
        for seg in day.segments:
            for tag in seg.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    if not tag_counts:
        return None
    # 按频次排序，取前 3
    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    top_tags = [t for t, _ in sorted_tags[:3]]

    merged = list(dict.fromkeys(top_tags))

    return {
        "key": _INTERESTS_KEY,
        "base_value": {"interests": merged, "top_tags": top_tags},
        "confidence": _confidence_from_occurrences(len(top_tags), 2),
        "context": _build_context(state),
        "signal_detail": f"高频标签: {', '.join(top_tags)}",
    }


def _extract_budget(state: PlanState) -> Optional[dict]:
    """从预算使用率推断预算偏好等级。"""
    c = state.constraints
    if not c or c.budget <= 0:
        return None

    total_spent = 0
    for day in state.days:
        for seg in day.segments:
            if seg.estimated_cost:
                total_spent += seg.estimated_cost.amount

    usage_ratio = total_spent / c.budget
    if usage_ratio < 0.5:
        level = "budget_conscious"
    elif usage_ratio < 0.85:
        level = "mid_range"
    elif usage_ratio <= 1.0:
        level = "full_use"
    else:
        level = "over_budget"

    return {
        "key": _BUDGET_KEY,
        "base_value": {"level": level, "budget_per_day": round(c.budget / c.days) if c.days else 0},
        "confidence": _confidence_from_occurrences(1, 3),
        "context": _build_context(state),
        "signal_detail": f"预算使用率 {usage_ratio:.0%} → {level}",
    }


def _extract_style(state: PlanState) -> Optional[dict]:
    """从行程特征推断整体旅行风格。"""
    c = state.constraints
    if not c or not state.days:
        return None

    features = []
    has_elderly = any(t.age_group == "elderly" for t in c.travelers)
    total_activities = sum(
        1 for d in state.days for s in d.segments if s.type == SegmentType.ACTIVITY
    )

    if has_elderly:
        features.append("senior_friendly")
    if any(s.type == SegmentType.MEAL for d in state.days for s in d.segments):
        features.append("food_oriented")
    if c.pace == "slow":
        features.append("relaxed")
    elif c.pace == "fast":
        features.append("intensive")

    if not features:
        return None

    return {
        "key": _STYLE_KEY,
        "base_value": {"features": features, "activity_count": total_activities},
        "confidence": _confidence_from_occurrences(1, 3),
        "context": _build_context(state),
        "signal_detail": f"风格特征: {', '.join(features)}",
    }


# ═══════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════

def _build_context(state: PlanState) -> dict:
    """构建偏好信号的上下文特征。"""
    c = state.constraints
    if not c:
        return {}
    ctx: dict[str, Any] = {"destination_type": "unknown"}
    has_elderly = any(t.age_group == "elderly" for t in c.travelers)
    has_child = any(t.age_group == "child" for t in c.travelers)
    if has_elderly:
        ctx["has_elderly"] = True
    if has_child:
        ctx["has_child"] = True
    return ctx


def _confidence_from_occurrences(count: int, min_count: int = 2) -> float:
    """
    根据出现次数计算置信度。

    规则:
      count < min_count → 0.3 (低置信度)
      count == min_count → 0.6
      count > min_count → min(0.6 + (count - min_count) * 0.1, 0.95)
    """
    if count < min_count:
        return 0.3
    if count == min_count:
        return 0.6
    return min(0.6 + (count - min_count) * 0.1, 0.95)


def _resolve_user_id(trip_id: str, db_session_factory) -> Optional[str]:
    """通过 ORM 查找 trip 所属的用户。"""
    try:
        from travel_planning_agent.db.models import Trip
        session = db_session_factory()
        trip = session.query(Trip).filter(Trip.trip_id == trip_id).first()
        session.close()
        return trip.user_id if trip else None
    except Exception as e:
        logger.warning("Reflection 无法解析 user_id: %s", e)
        return None


def _merge_to_db(signals: list[dict], user_id: str, db_session_factory):
    """
    将偏好信号写入 user_preferences 表。
    同 key 合并，同 key+同 context 条件更新。
    """
    try:
        from travel_planning_agent.db.models import UserPreference
        session = db_session_factory()

        for sig in signals:
            key = sig["key"]
            base_value = sig["base_value"]
            new_confidence = sig["confidence"]
            context = sig.get("context", {})

            existing = session.query(UserPreference).filter(
                UserPreference.user_id == user_id,
                UserPreference.pref_key == key,
            ).first()

            if existing:
                conditional_vals = existing.conditional_values or []
                merged = False
                for cv in conditional_vals:
                    if cv.get("context") == context:
                        cv["value"] = base_value
                        cv["confidence"] = new_confidence
                        merged = True
                        break

                if not merged:
                    conditional_vals.append({
                        "context": context,
                        "value": base_value,
                        "confidence": new_confidence,
                    })

                existing.conditional_values = conditional_vals
                existing.confidence = max(existing.confidence, new_confidence)
            else:
                pref = UserPreference(
                    user_id=user_id,
                    pref_key=key,
                    base_value=base_value,
                    confidence=new_confidence,
                    conditional_values=[{
                        "context": context,
                        "value": base_value,
                        "confidence": new_confidence,
                    }] if context else None,
                )
                session.add(pref)

        session.commit()
        session.close()
        logger.info("Reflection 已将 %d 条偏好写入 DB", len(signals))

    except Exception as e:
        logger.error("Reflection DB 写入失败: %s", e)
