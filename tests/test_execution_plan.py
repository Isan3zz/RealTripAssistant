from datetime import date
import threading
import time

from travel_planning_agent.core.execution_plan import (
    ExecutionPlan,
    ExecutionTask,
    build_global_execution_plan,
    execution_plan_from_research_tasks,
)
from travel_planning_agent.core.execution_executor import execute_execution_plan
from travel_planning_agent.types import Constraints, ResearchTask, ToolResult, Traveler


def test_build_global_execution_plan_includes_weather_transport_and_must_have():
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_mode="高铁",
        interests=["玄武湖"],
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_global")

    assert plan.plan_id == "exec_global"
    assert [task.task_id for task in plan.tasks] == [
        "global_weather_nanjing_2026-05-18",
        "global_transport_train_hangzhou_nanjing_2026-05-18",
        "global_poi_nanjing_xuanwu_lake",
    ]
    assert plan.tasks[0].tool_name == "get_weather_forecast"
    assert plan.tasks[0].args == {"city": "南京", "date": "2026-05-18", "days": 2}
    assert plan.tasks[1].tool_name == "search_train"
    assert plan.tasks[1].required is True
    assert plan.tasks[2].args["context"] == "玄武湖"


def test_execution_plan_from_research_tasks_preserves_reuse_key_and_priority():
    research_tasks = [
        ResearchTask(
            task_type="ticket_price",
            tool_name="query_ticket_price",
            args={"scenic_name": "玄武湖"},
            reason="核实门票",
            priority=4,
            reuse_key="ticket:玄武湖",
        )
    ]

    plan = execution_plan_from_research_tasks("exec_daily_1", research_tasks)

    assert plan.plan_id == "exec_daily_1"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.task_id == "daily_ticket_price_ticket_xuanwu_lake"
    assert task.task_type == "ticket_price"
    assert task.tool_name == "query_ticket_price"
    assert task.args == {"scenic_name": "玄武湖"}
    assert task.reuse_key == "ticket:玄武湖"
    assert task.priority == 4
    assert task.status == "pending"


def test_execution_plan_to_dict_is_json_safe():
    constraints = Constraints(
        origin="杭州",
        destination="南京",
        start_date=date(2026, 5, 18),
        days=1,
        travelers=[Traveler(age_group="adult")],
        budget=1000,
        interests=[],
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_safe")

    assert plan.to_dict()["created_from"]["start_date"] == "2026-05-18"
    assert plan.to_dict()["tasks"][0]["status"] == "pending"


def test_build_global_execution_plan_stays_pure_and_pending():
    constraints = Constraints(
        origin="\u676d\u5dde",
        destination="\u5357\u4eac",
        start_date=date(2026, 5, 18),
        days=2,
        travelers=[Traveler(age_group="adult")],
        budget=2000,
        pace="slow",
        transport_mode="\u9ad8\u94c1",
        interests=["sample_spot"],
    )

    plan = build_global_execution_plan(constraints, plan_id="exec_pure")

    assert plan.plan_id == "exec_pure"
    assert plan.scope == "global"
    assert all(task.status == "pending" for task in plan.tasks)
    assert all(task.error is None for task in plan.tasks)
    assert all(task.evidence_ids == [] for task in plan.tasks)


def test_execute_execution_plan_runs_tools_and_returns_evidence(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_run",
        scope="global",
        created_from={"destination": "南京"},
        tasks=[
            ExecutionTask(
                task_id="weather",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"city": "南京"},
            )
        ],
    )

    def fake_execute(name, args):
        assert name == "get_weather_forecast"
        assert args == {"city": "南京"}
        return ToolResult(
            status="success",
            data="南京小雨",
            evidence=[{
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    result = execute_execution_plan(plan)

    assert result["status"] == "completed"
    assert result["results"][0].status == "success"
    assert result["evidence"][0]["claim"] == "南京小雨"
    assert result["tasks"][0].status == "completed"
    assert result["tasks"][0].evidence_ids == [result["evidence"][0]["evidence_id"]]


def test_execute_execution_plan_records_failed_required_task(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_failed",
        scope="global",
        created_from={},
        tasks=[
            ExecutionTask(
                task_id="transport",
                task_type="transport",
                tool_name="search_train",
                args={"from_station": "杭州"},
                required=True,
            )
        ],
    )

    def fake_execute(name, args):
        return ToolResult(status="failed", error="查询失败", confidence="low")

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    result = execute_execution_plan(plan)

    assert result["status"] == "completed_with_errors"
    assert result["results"][0].status == "failed"
    assert result["results"][0].error == "查询失败"
    assert result["tasks"][0].status == "failed"


def test_execute_execution_plan_skips_duplicate_tool_call_and_reuses_evidence(monkeypatch):
    plan = ExecutionPlan(
        plan_id="exec_duplicate",
        scope="global",
        created_from={},
        tasks=[
            ExecutionTask(
                task_id="weather_a",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"city": "南京", "date": "2026-05-18", "days": 2},
            ),
            ExecutionTask(
                task_id="weather_b",
                task_type="weather",
                tool_name="get_weather_forecast",
                args={"days": 2, "city": "南京", "date": "2026-05-18"},
            ),
        ],
    )
    calls = []

    def fake_execute(name, args):
        calls.append((name, args))
        return ToolResult(
            status="success",
            data="南京小雨",
            evidence=[{
                "source": "weather_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "南京小雨",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    reuse_context = {}
    result = execute_execution_plan(plan, reuse_context=reuse_context)

    assert len(calls) == 1
    assert result["results"][0].status == "success"
    assert result["results"][1].status == "skipped_duplicate"
    assert result["results"][1].evidence_ids == result["results"][0].evidence_ids
    assert result["tasks"][1].status == "skipped_duplicate"
    assert result["evidence"][0]["claim"] == "南京小雨"
    assert len(result["evidence"]) == 1
    assert result["tool_calls"]


def test_execute_execution_plan_deduplicates_concurrent_same_fingerprint(monkeypatch):
    def make_plan(plan_id):
        return ExecutionPlan(
            plan_id=plan_id,
            scope="daily_research",
            created_from={},
            tasks=[
                ExecutionTask(
                    task_id=f"{plan_id}_ticket",
                    task_type="ticket_price",
                    tool_name="query_ticket_price",
                    args={"scenic_name": "玄武湖"},
                )
            ],
        )

    calls = []
    first_call_entered = threading.Event()

    def fake_execute(name, args):
        calls.append((name, args))
        first_call_entered.set()
        time.sleep(0.1)
        return ToolResult(
            status="success",
            data="玄武湖免费",
            evidence=[{
                "source": "ticket_api",
                "source_type": "api",
                "confidence": "high",
                "claim": "玄武湖免费",
                "retrieved_at": "2026-05-18T00:00:00",
            }],
        )

    monkeypatch.setattr("travel_planning_agent.core.execution_executor.execute_registered_tool", fake_execute)

    registry = {}
    results = []
    first = threading.Thread(target=lambda: results.append(execute_execution_plan(make_plan("exec_a"), reuse_context=registry)))
    second = threading.Thread(target=lambda: results.append(execute_execution_plan(make_plan("exec_b"), reuse_context=registry)))

    first.start()
    assert first_call_entered.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(calls) == 1
    assert sorted(result["results"][0].status for result in results) == ["skipped_duplicate", "success"]
