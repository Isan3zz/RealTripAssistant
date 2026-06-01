"""Bounded ReAct-style tool loop for travel research."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from travel_planning_agent.tool_runtime import execute_registered_tool


@dataclass
class ReActDecision:
    kind: str
    rationale_summary: str = ""
    tool: str | None = None
    args: dict = field(default_factory=dict)
    final: dict | None = None
    error: str | None = None


@dataclass
class ReActStep:
    step_index: int
    rationale_summary: str
    tool: str
    args: dict
    observation_status: str
    observation: str


@dataclass
class ReActRunResult:
    status: str
    final: dict = field(default_factory=dict)
    steps: list[ReActStep] = field(default_factory=list)
    tokens_used: int = 0
    error: str | None = None


def parse_react_decision(text: str) -> ReActDecision:
    try:
        data = json.loads((text or "").strip())
    except json.JSONDecodeError as exc:
        return ReActDecision(kind="error", error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return ReActDecision(kind="error", error="Decision must be a JSON object")

    rationale = str(data.get("rationale_summary") or "").strip()
    action = data.get("action")
    final = data.get("final")

    if isinstance(action, dict):
        tool = action.get("tool")
        args = action.get("args") or {}
        if not isinstance(tool, str) or not tool:
            return ReActDecision(kind="error", rationale_summary=rationale, error="Action tool is required")
        if not isinstance(args, dict):
            return ReActDecision(kind="error", rationale_summary=rationale, error="Action args must be an object")
        return ReActDecision(
            kind="action",
            rationale_summary=rationale,
            tool=tool,
            args=args,
        )

    if isinstance(final, dict):
        return ReActDecision(kind="final", rationale_summary=rationale, final=final)

    return ReActDecision(
        kind="error",
        rationale_summary=rationale,
        error="Decision must contain either action or final",
    )


REACT_SYSTEM_PROMPT = """You are a travel research tool-use agent.
Return only JSON.
At each step, choose exactly one of:
1. {"rationale_summary": "...", "action": {"tool": "...", "args": {...}}}
2. {"rationale_summary": "...", "final": {...}}

Rules:
- Use only allowed tools.
- Keep rationale_summary short and audit-friendly.
- Do not include hidden chain-of-thought.
- Final must contain findings and covered_items.
"""


def run_react_loop(
    llm_client,
    *,
    task: str,
    context: dict,
    allowed_tools: list[str],
    max_steps: int = 5,
) -> ReActRunResult:
    steps: list[ReActStep] = []
    tokens_used = 0
    observations: list[str] = []

    for step_index in range(1, max_steps + 1):
        user_message = _build_react_user_message(task, context, allowed_tools, observations)
        llm_result = llm_client.generate(REACT_SYSTEM_PROMPT, user_message, tools=None)
        tokens_used += llm_result.tokens_used or 0

        if not llm_result.success:
            error = llm_result.error or "LLM call failed"
            _record_react_trace("react_error", {"error": error, "step_index": step_index})
            return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)

        decision = parse_react_decision(llm_result.text or "")
        _record_react_trace(
            "react_decision",
            {
                "step_index": step_index,
                "kind": decision.kind,
                "rationale_summary": decision.rationale_summary,
                "tool": decision.tool,
                "args": decision.args,
                "error": decision.error,
            },
        )

        if decision.kind == "error":
            return ReActRunResult(
                status="failed",
                steps=steps,
                tokens_used=tokens_used,
                error=decision.error,
            )

        if decision.kind == "final":
            final = decision.final or {}
            _record_react_trace("react_final", {"step_index": step_index, "final": final})
            return ReActRunResult(
                status="success",
                final=final,
                steps=steps,
                tokens_used=tokens_used,
            )

        assert decision.tool is not None
        if decision.tool not in allowed_tools:
            error = f"Tool not allowed: {decision.tool}"
            _record_react_trace("react_error", {"error": error, "step_index": step_index})
            return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)

        tool_result = execute_registered_tool(decision.tool, decision.args)
        observation = tool_result.data or tool_result.error or ""
        steps.append(
            ReActStep(
                step_index=step_index,
                rationale_summary=decision.rationale_summary,
                tool=decision.tool,
                args=decision.args,
                observation_status=tool_result.status,
                observation=str(observation),
            )
        )
        observations.append(f"Observation {step_index} [{decision.tool}]: {observation}")
        _record_react_trace(
            "react_observation",
            {
                "step_index": step_index,
                "tool": decision.tool,
                "status": tool_result.status,
                "observation": str(observation)[:1000],
            },
        )

    error = "ReAct loop reached max_steps without final answer"
    _record_react_trace("react_error", {"error": error, "max_steps": max_steps})
    return ReActRunResult(status="failed", steps=steps, tokens_used=tokens_used, error=error)


def _build_react_user_message(
    task: str,
    context: dict,
    allowed_tools: list[str],
    observations: list[str],
) -> str:
    return json.dumps(
        {
            "task": task,
            "context": context,
            "allowed_tools": allowed_tools,
            "observations": observations,
        },
        ensure_ascii=False,
        default=str,
    )


def _record_react_trace(event_type: str, data: dict) -> None:
    try:
        from travel_planning_agent.core.tracing import record_trace_event

        record_trace_event(event_type, "react", data)
    except Exception:
        return
