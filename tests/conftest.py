"""
conftest.py — 测试 fixtures
"""

from datetime import date
from typing import Any
import pytest

from travel_planning_agent.types import (
    PlanState,
    Constraints,
    Traveler,
    ItineraryDay,
    Segment,
    SegmentType,
    Location,
    Cost,
    Evidence,
    TripStatus,
    PlanPhase,
)


@pytest.fixture
def base_constraints() -> Constraints:
    """基础约束条件：杭州 4 天家庭游。"""
    return Constraints(
        destination="杭州",
        start_date=date(2026, 5, 1),
        end_date=4,
        travelers=[
            Traveler(age_group="adult"),
            Traveler(age_group="adult"),
            Traveler(age_group="elderly", note="2位老人"),
        ],
        budget=20000,
        pace="slow",
        interests=["文化", "自然"],
    )


@pytest.fixture
def valid_state(base_constraints) -> PlanState:
    """合法状态：所有规则应 PASS。"""
    state = PlanState(
        trip_id="test_trip_001",
        status=TripStatus.PLANNING,
        constraints=base_constraints,
        phase=PlanPhase.PLANNING,
    )

    day1 = ItineraryDay(day_id="day_001", day_number=1, theme="抵达与适应")
    day1.segments = [
        Segment(
            segment_id="seg_001",
            type=SegmentType.ACTIVITY,
            title="西湖漫步",
            start_time="14:00",
            end_time="17:00",
            location=Location(name="西湖", city="杭州"),
            estimated_cost=Cost(amount=0),
            tags=["natural"],
        ),
        Segment(
            segment_id="seg_002",
            type=SegmentType.MEAL,
            title="晚餐",
            start_time="18:00",
            end_time="19:00",
            location=Location(name="餐厅", city="杭州"),
            estimated_cost=Cost(amount=300),
            tags=["food"],
        ),
    ]

    day2 = ItineraryDay(day_id="day_002", day_number=2, theme="文化探索")
    day2.segments = [
        Segment(
            segment_id="seg_003",
            type=SegmentType.ACTIVITY,
            title="灵隐寺",
            start_time="09:00",
            end_time="11:00",
            location=Location(name="灵隐寺", city="杭州"),
            estimated_cost=Cost(amount=75),
            tags=["cultural"],
        ),
    ]

    state.days = [day1, day2]
    return state


@pytest.fixture
def overlapping_state(base_constraints) -> PlanState:
    """时间重叠状态：R01 应 FAIL。"""
    state = PlanState(
        trip_id="test_trip_overlap",
        status=TripStatus.PLANNING,
        constraints=base_constraints,
    )

    day1 = ItineraryDay(day_id="day_001", day_number=1, theme="测试日")
    day1.segments = [
        Segment(
            segment_id="seg_001",
            type=SegmentType.ACTIVITY,
            title="景点A",
            start_time="09:00",
            end_time="11:30",
        ),
        Segment(
            segment_id="seg_002",
            type=SegmentType.ACTIVITY,
            title="景点B",
            start_time="11:00",  # 与 seg_001 重叠（11:00 < 11:30）
            end_time="13:00",
        ),
    ]

    state.days = [day1]
    return state


@pytest.fixture
def budget_exceeded_state(base_constraints) -> PlanState:
    """超预算状态：R02 应 FAIL。"""
    state = PlanState(
        trip_id="test_trip_budget",
        status=TripStatus.PLANNING,
        constraints=base_constraints,
    )

    day1 = ItineraryDay(day_id="day_001", day_number=1, theme="超预算日")
    day1.segments = [
        Segment(
            segment_id="seg_001",
            type=SegmentType.ACTIVITY,
            title="豪华项目",
            estimated_cost=Cost(amount=25000),  # 超过 20000 预算
        ),
    ]

    state.days = [day1]
    return state


@pytest.fixture
def missing_activity_state(base_constraints) -> PlanState:
    """缺少活动状态：R04 应 FAIL。"""
    state = PlanState(
        trip_id="test_trip_no_activity",
        status=TripStatus.PLANNING,
        constraints=base_constraints,
    )

    day1 = ItineraryDay(day_id="day_001", day_number=1, theme="无活动日")
    day1.segments = [
        Segment(
            segment_id="seg_001",
            type=SegmentType.MEAL,
            title="午餐",
        ),
    ]

    state.days = [day1]
    return state


@pytest.fixture
def mock_llm_result_simple():
    """简单的 mock LLM 结果。"""
    return {
        "days": [
            {
                "day_number": 1,
                "theme": "测试日",
                "segments": [
                    {
                        "type": "activity",
                        "title": "测试景点",
                        "start_time": "09:00",
                        "end_time": "11:00",
                        "location": {"name": "景点", "city": "杭州"},
                        "estimated_cost": {"amount": 50, "currency": "CNY"},
                        "tags": ["cultural"],
                        "evidence": [{"source": "模型知识", "claim": "测试"}],
                    },
                ],
            },
        ],
    }
