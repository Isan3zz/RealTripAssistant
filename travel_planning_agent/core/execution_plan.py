"""Structured Plan-and-Execute task models and builders."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from travel_planning_agent.types import Constraints, ResearchTask


@dataclass
class ExecutionTask:
    task_id: str
    task_type: str
    tool_name: str | None
    args: dict[str, Any]
    required: bool = True
    reason: str = ""
    priority: int = 5
    reuse_key: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    evidence_ids: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionResult:
    task_id: str
    status: str
    output: Any = None
    evidence_ids: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionPlan:
    plan_id: str
    scope: str
    created_from: dict[str, Any]
    tasks: list[ExecutionTask] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "scope": self.scope,
            "created_from": _jsonable(self.created_from),
            "created_at": self.created_at,
            "tasks": [_jsonable(asdict(task)) for task in self.tasks],
        }


def build_global_execution_plan(constraints: Constraints, plan_id: str) -> ExecutionPlan:
    start_date = constraints.start_date.isoformat()
    destination = constraints.destination
    tasks = [
        ExecutionTask(
            task_id=f"global_weather_{_slug(destination)}_{start_date}",
            task_type="weather",
            tool_name="get_weather_forecast",
            args={"city": destination, "date": start_date, "days": constraints.days},
            required=True,
            reason="出发前需要确认天气，影响室内/户外安排",
            priority=1,
            reuse_key=f"weather:{destination}:{start_date}:{constraints.days}",
        )
    ]
    if constraints.origin and _prefers_train(constraints.transport_mode):
        tasks.append(
            ExecutionTask(
                task_id=f"global_transport_train_{_slug(constraints.origin)}_{_slug(destination)}_{start_date}",
                task_type="transport",
                tool_name="search_train",
                args={
                    "from_station": constraints.origin,
                    "to_station": destination,
                    "date": start_date,
                },
                required=True,
                reason="用户指定或偏好高铁/火车，需要确认可行交通",
                priority=2,
                reuse_key=f"transport:train:{constraints.origin}->{destination}:{start_date}",
            )
        )
    for item in constraints.interests or []:
        if not item:
            continue
        tasks.append(
            ExecutionTask(
                task_id=f"global_poi_{_slug(destination)}_{_slug(item)}",
                task_type="poi_detail",
                tool_name="search_poi",
                args={"destination": destination, "category": "cultural", "context": item},
                required=True,
                reason=f"用户明确要求包含 {item}",
                priority=3,
                reuse_key=f"poi:{destination}:{item}",
            )
        )
    return ExecutionPlan(
        plan_id=plan_id,
        scope="global",
        created_from=_constraints_summary(constraints),
        tasks=_dedupe_execution_tasks(tasks),
    )


def execution_plan_from_research_tasks(plan_id: str, research_tasks: list[ResearchTask]) -> ExecutionPlan:
    tasks = []
    for task in research_tasks:
        tasks.append(
            ExecutionTask(
                task_id=f"daily_{task.task_type}_{_slug(task.reuse_key or task.tool_name)}",
                task_type=task.task_type,
                tool_name=task.tool_name,
                args=dict(task.args),
                required=True,
                reason=task.reason,
                priority=task.priority,
                reuse_key=task.reuse_key,
            )
        )
    return ExecutionPlan(
        plan_id=plan_id,
        scope="daily_research",
        created_from={"research_task_count": len(research_tasks)},
        tasks=_dedupe_execution_tasks(tasks),
    )


def _constraints_summary(constraints: Constraints) -> dict:
    return {
        "origin": constraints.origin,
        "destination": constraints.destination,
        "start_date": constraints.start_date,
        "days": constraints.days,
        "budget": constraints.budget,
        "pace": constraints.pace,
        "transport_mode": constraints.transport_mode,
        "interests": list(constraints.interests or []),
    }


def _dedupe_execution_tasks(tasks: list[ExecutionTask]) -> list[ExecutionTask]:
    seen = set()
    result = []
    for task in sorted(tasks, key=lambda item: item.priority):
        key = task.reuse_key or f"{task.tool_name}:{task.args}"
        if key in seen:
            continue
        seen.add(key)
        result.append(task)
    return result


def _prefers_train(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in ("高铁", "火车", "动车", "train", "rail"))


def _slug(value: str) -> str:
    mapping = {
        "杭州": "hangzhou",
        "南京": "nanjing",
        "玄武湖": "xuanwu_lake",
    }
    text = str(value or "").strip()
    if text in mapping:
        return mapping[text]
    for source, target in mapping.items():
        text = text.replace(source, target)
    text = re.sub(r"[^0-9A-Za-z]+", "_", text)
    return text.strip("_").lower() or "unknown"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
