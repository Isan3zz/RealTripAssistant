"""Execute structured execution plans through the product tool runtime."""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from datetime import datetime

from travel_planning_agent.core.execution_plan import ExecutionPlan, ExecutionResult
from travel_planning_agent.core.tool_dedup import (
    find_tool_call,
    get_tool_call_registry,
    get_tool_call_lock,
    remember_tool_call,
)
from travel_planning_agent.tool_runtime import execute_registered_tool


def execute_execution_plan(plan: ExecutionPlan, reuse_context: MutableMapping | None = None) -> dict:
    results: list[ExecutionResult] = []
    evidence: list[dict] = []
    has_required_error = False
    tool_calls = get_tool_call_registry(reuse_context)

    _trace("execution_plan_started", {"plan": plan.to_dict()})
    for task in plan.tasks:
        _trace("execution_task_started", {"plan_id": plan.plan_id, "task": task.__dict__})
        if not task.tool_name:
            task.status = "skipped"
            result = ExecutionResult(task_id=task.task_id, status="skipped", error="No tool_name")
            results.append(result)
            continue

        with get_tool_call_lock(tool_calls, task.tool_name, task.args):
            reused = find_tool_call(tool_calls, task.tool_name, task.args)
            if reused:
                task.status = "skipped_duplicate"
                task.evidence_ids = list(reused.get("evidence_ids") or [])
                result = ExecutionResult(
                    task_id=task.task_id,
                    status="skipped_duplicate",
                    evidence_ids=list(task.evidence_ids),
                )
                results.append(result)
                _trace(
                    "execution_task_skipped_duplicate",
                    {
                        "plan_id": plan.plan_id,
                        "task_id": task.task_id,
                        "tool": task.tool_name,
                        "reused_evidence_ids": list(task.evidence_ids),
                        "fingerprint": reused.get("fingerprint"),
                    },
                )
                continue

            tool_result = execute_registered_tool(task.tool_name, task.args)
            if tool_result.status == "success":
                task.status = "completed"
                task_evidence = [_normalize_evidence(item, task.task_id) for item in tool_result.evidence or []]
                if not task_evidence and tool_result.data:
                    task_evidence = [_normalize_evidence({
                        "source": task.tool_name,
                        "source_type": tool_result.source_type,
                        "confidence": tool_result.confidence,
                        "claim": str(tool_result.data),
                        "retrieved_at": tool_result.retrieved_at or datetime.now().isoformat(),
                    }, task.task_id)]
                evidence.extend(task_evidence)
                task.evidence_ids = [item["evidence_id"] for item in task_evidence]
                result = ExecutionResult(
                    task_id=task.task_id,
                    status="success",
                    output=tool_result.data,
                    evidence_ids=list(task.evidence_ids),
                )
                remember_tool_call(
                    tool_calls,
                    task.tool_name,
                    task.args,
                    status="success",
                    evidence_ids=list(task.evidence_ids),
                    task_id=task.task_id,
                )
            else:
                task.status = "failed"
                task.error = tool_result.error or str(tool_result.data or "")
                has_required_error = has_required_error or task.required
                result = ExecutionResult(
                    task_id=task.task_id,
                    status="failed",
                    output=tool_result.data,
                    error=task.error,
                )
                remember_tool_call(
                    tool_calls,
                    task.tool_name,
                    task.args,
                    status="failed",
                    evidence_ids=[],
                    task_id=task.task_id,
                )
        results.append(result)
        _trace(
            "execution_task_completed" if task.status == "completed" else "execution_task_failed",
            {"plan_id": plan.plan_id, "task_id": task.task_id, "status": task.status, "error": task.error},
        )

    status = "completed_with_errors" if has_required_error else "completed"
    payload = {
        "status": status,
        "plan": plan,
        "tasks": plan.tasks,
        "results": results,
        "evidence": evidence,
        "tool_calls": tool_calls,
    }
    _trace("execution_plan_completed", {"plan_id": plan.plan_id, "status": status})
    return payload


def _normalize_evidence(item: dict, task_id: str) -> dict:
    return {
        "evidence_id": item.get("evidence_id") or f"ev_{task_id}_{uuid.uuid4().hex[:8]}",
        "source": item.get("source", "tool"),
        "source_type": item.get("source_type", "api"),
        "confidence": item.get("confidence", "medium"),
        "claim": item.get("claim", ""),
        "retrieved_at": item.get("retrieved_at") or datetime.now().isoformat(),
    }


def _trace(event_type: str, data: dict) -> None:
    try:
        from travel_planning_agent.core.tracing import record_trace_event

        record_trace_event(event_type, "execution", data)
    except Exception:
        return
