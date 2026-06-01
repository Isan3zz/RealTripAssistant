"""
file_store.py — 文件系统存储

职责：
- 创建行程目录
- 读写 state.json（结构化数据）
- 写入 trip.md（人类可读的 Markdown 行程）
- 逐条存储证据文件
- 列出已有行程

核心设计思想（架构总纲）：
- Markdown 是主数据格式，JSON 是辅助索引
- 用户可以直接修改 .md 文件，系统下次运行时读取并保持同步
- 证据从 MVP 阶段就独立存储，包含 URL 可达性标记
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from travel_planning_agent.config import settings
from travel_planning_agent.types import (
    PlanState,
    TripStatus,
    PlanPhase,
    Constraints,
    Traveler,
    ItineraryDay,
    Segment,
    SegmentType,
    Location,
    Cost,
    Evidence,
    RuleResult,
    VerificationReport,
    SemanticCheckResult,
    RiskCheck,
    Pin,
    Assumption,
    AssumptionLevel,
    AssumptionStatus,
    PlanDiff,
    ChangeItem,
)

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────

def _get_data_dir() -> Path:
    """获取数据根目录。"""
    return Path(settings.data_dir)


def _get_trip_dir(trip_id: str) -> Path:
    """获取指定行程的目录路径。"""
    return _get_data_dir() / "trips" / trip_id


def _get_evidence_dir(trip_id: str) -> Path:
    """获取证据目录路径。"""
    return _get_trip_dir(trip_id) / "evidence"


def _ensure_dir(path: Path) -> None:
    """确保目录存在。"""
    path.mkdir(parents=True, exist_ok=True)


# ── 序列化/反序列化辅助 ──────────────────────────────

def _plan_state_to_dict(state: PlanState) -> dict:
    """将 PlanState 序列化为可 JSON 序列化的字典。"""
    result = {
        "trip_id": state.trip_id,
        "status": state.status.value,
        "phase": state.phase.value,
        "constraints": _constraints_to_dict(state.constraints) if state.constraints else None,
        "days": [_day_to_dict(d) for d in state.days],
        "evidence": {k: _evidence_to_dict(v) for k, v in state.evidence.items()},
        "revision_count": state.revision_count,
        "max_revisions": state.max_revisions,
        "error": state.error,
        # Phase 2 新增字段
        "plan_version": state.plan_version,
        "pins": [_pin_to_dict(p) for p in state.pins],
        "assumptions": [_assumption_to_dict(a) for a in state.assumptions],
        "diff_history": [_diff_to_dict(d) for d in state.diff_history],
        "pending_questions": state.pending_questions,
        "degrade_level": state.degrade_level,
        "message_history": state.message_history,
        "tasks": [_task_to_dict(t) for t in state.tasks],
    }
    # Phase 3 模块化规划字段
    result["planning_queue"] = state.planning_queue
    result["module_context"] = state.module_context
    result["current_module"] = state.current_module
    result["current_module_retry_count"] = state.current_module_retry_count
    result["current_module_max_retries"] = state.current_module_max_retries

    if state.validation:
        result["validation"] = _verification_report_to_dict(state.validation)
    return result


def _pin_to_dict(p: Pin) -> dict:
    return {
        "pin_id": p.pin_id,
        "target_type": p.target_type,
        "target_id": p.target_id,
        "scope": p.scope,
        "day_number": p.day_number,
        "mutable": p.mutable,
        "reason": p.reason,
        "created_at": p.created_at,
    }


def _assumption_to_dict(a: Assumption) -> dict:
    return {
        "assumption_id": a.assumption_id,
        "level": a.level.value,
        "content": a.content,
        "status": a.status.value,
        "impact": a.impact,
        "affected_rules": a.affected_rules,
    }


def _diff_to_dict(d: PlanDiff) -> dict:
    return {
        "diff_id": d.diff_id,
        "old_plan_version": d.old_plan_version,
        "new_plan_version": d.new_plan_version,
        "changes": [
            {
                "segment_id": c.segment_id,
                "change_type": c.change_type,
                "field_changes": c.field_changes,
                "reason": c.reason,
                "impact": c.impact,
            }
            for c in d.changes
        ],
        "pin_integrity": d.pin_integrity,
    }


def _verification_report_to_dict(v: VerificationReport) -> dict:
    return {
        "verification_id": v.verification_id,
        "overall_pass": v.overall_pass,
        "rule_checks": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "result": r.result,
                "severity": r.severity,
                "detail": r.detail,
                "affected_segments": r.affected_segments,
            }
            for r in v.rule_checks
        ],
        "semantic_checks": [
            {
                "check_id": s.check_id,
                "result": s.result,
                "detail": s.detail,
                "affected_days": s.affected_days,
            }
            for s in v.semantic_checks
        ],
        "risk_checks": [
            {
                "risk_id": r.risk_id,
                "risk_type": r.risk_type,
                "severity": r.severity,
                "probability": r.probability,
                "detail": r.detail,
                "mitigation": r.mitigation,
            }
            for r in v.risk_checks
        ],
        "correction_requests": v.correction_requests,
        "module_checks": v.module_checks,
        "whole_plan_checks": v.whole_plan_checks,
        "blocking_failures": v.blocking_failures,
        "warnings": v.warnings,
    }


def _constraints_to_dict(c: Constraints) -> dict:
    result = {
        "destination": c.destination,
        "start_date": c.start_date.isoformat(),
        "end_date": c.days,  # 序列化用 end_date 键名
        "travelers": [{"age_group": t.age_group, "note": t.note} for t in c.travelers],
        "budget": c.budget,
        "pace": c.pace,
    }
    if c.origin:
        result["origin"] = c.origin
    if c.interests:
        result["interests"] = c.interests
    if c.transport_mode:
        result["transport_mode"] = c.transport_mode
    if c.preferences_detail:
        result["preferences_detail"] = c.preferences_detail
    return result


def _day_to_dict(d: ItineraryDay) -> dict:
    return {
        "day_id": d.day_id,
        "day_number": d.day_number,
        "theme": d.theme,
        "segments": [_segment_to_dict(s) for s in d.segments],
    }


def _segment_to_dict(s: Segment) -> dict:
    result = {
        "segment_id": s.segment_id,
        "type": s.type.value,
        "title": s.title,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "tags": s.tags,
        "evidence_ids": s.evidence_ids,
        "note": s.note,
    }
    if s.location:
        result["location"] = {"name": s.location.name, "city": s.location.city}
        if s.location.lat is not None:
            result["location"]["lat"] = s.location.lat
        if s.location.lng is not None:
            result["location"]["lng"] = s.location.lng
    if s.module:
        result["module"] = s.module
    if s.estimated_cost:
        result["estimated_cost"] = {"amount": s.estimated_cost.amount, "currency": s.estimated_cost.currency}
    return result


def _evidence_to_dict(e: Evidence) -> dict:
    return {
        "evidence_id": e.evidence_id,
        "source": e.source,
        "url": e.url,
        "retrieved_at": e.retrieved_at,
        "url_reachable": e.url_reachable,
        "url_checked_at": e.url_checked_at,
        "claim": e.claim,
        "confidence": e.confidence,
        "source_type": e.source_type,
    }


def _task_to_dict(t) -> dict:
    return {
        "task_id": t.task_id,
        "desc": t.desc,
        "status": t.status.value,
        "acceptance": t.acceptance,
        "depends_on": t.depends_on,
    }


def _dict_to_plan_state(data: dict) -> PlanState:
    """从字典反序列化为 PlanState。"""
    state = PlanState(trip_id=data["trip_id"])
    state.status = TripStatus(data.get("status", "draft"))
    state.phase = PlanPhase(data.get("phase", "init"))
    state.revision_count = data.get("revision_count", 0)
    state.max_revisions = data.get("max_revisions", 3)
    state.error = data.get("error")
    state.plan_version = data.get("plan_version", 1)
    state.pending_questions = data.get("pending_questions", [])
    state.degrade_level = data.get("degrade_level")

    # 反序列化 constraints
    if data.get("constraints"):
        c = data["constraints"]
        from datetime import date
        state.constraints = Constraints(
            destination=c["destination"],
            start_date=date.fromisoformat(c["start_date"]),
            days=c["end_date"],  # 反序列化用 days 字段
            travelers=[Traveler(**t) for t in c.get("travelers", [])],
            budget=c["budget"],
            origin=c.get("origin", ""),
            pace=c.get("pace", "moderate"),
            preferences_detail=c.get("preferences_detail", ""),
            transport_mode=c.get("transport_mode", ""),
            interests=c.get("interests", []),
        )

    # 反序列化 days
    for d in data.get("days", []):
        day = ItineraryDay(
            day_id=d["day_id"],
            day_number=d["day_number"],
            theme=d.get("theme", ""),
        )
        for s in d.get("segments", []):
            segment = Segment(
                segment_id=s["segment_id"],
                type=SegmentType(s.get("type", "activity")),
                title=s.get("title", ""),
                start_time=s.get("start_time"),
                end_time=s.get("end_time"),
                tags=s.get("tags", []),
                evidence_ids=s.get("evidence_ids", []),
                note=s.get("note", ""),
            )
            if s.get("location"):
                segment.location = Location(**s["location"])
            if s.get("estimated_cost"):
                segment.estimated_cost = Cost(**s["estimated_cost"])
            if s.get("module"):
                segment.module = s["module"]
            day.segments.append(segment)
        state.days.append(day)

    # 反序列化 evidence
    for eid, e in data.get("evidence", {}).items():
        state.evidence[eid] = Evidence(**e)

    # 反序列化 pins
    for p in data.get("pins", []):
        state.pins.append(Pin(**p))

    # 反序列化 assumptions
    for a in data.get("assumptions", []):
        from travel_planning_agent.types import AssumptionLevel, AssumptionStatus
        state.assumptions.append(Assumption(
            assumption_id=a["assumption_id"],
            level=AssumptionLevel(a["level"]),
            content=a["content"],
            status=AssumptionStatus(a.get("status", "pending_confirmation")),
            impact=a.get("impact", "high"),
            affected_rules=a.get("affected_rules", []),
        ))

    # 反序列化 diff_history
    for d in data.get("diff_history", []):
        changes = []
        for c in d.get("changes", []):
            from travel_planning_agent.types import ChangeItem
            changes.append(ChangeItem(**c))
        from travel_planning_agent.types import PlanDiff
        state.diff_history.append(PlanDiff(
            diff_id=d["diff_id"],
            old_plan_version=d["old_plan_version"],
            new_plan_version=d["new_plan_version"],
            changes=changes,
            pin_integrity=d.get("pin_integrity", {}),
        ))

    # 反序列化 validation
    if data.get("validation"):
        v = data["validation"]
        if "rule_checks" in v:
            rules = [RuleResult(**r) for r in v.get("rule_checks", [])]
            from travel_planning_agent.types import SemanticCheckResult, RiskCheck
            semantic = [SemanticCheckResult(**s) for s in v.get("semantic_checks", [])]
            risks = [RiskCheck(**r) for r in v.get("risk_checks", [])]
            state.validation = VerificationReport(
                verification_id=v.get("verification_id", ""),
                overall_pass=v["overall_pass"],
                rule_checks=rules,
                semantic_checks=semantic,
                risk_checks=risks,
                correction_requests=v.get("correction_requests", []),
                module_checks=v.get("module_checks", []),
                whole_plan_checks=v.get("whole_plan_checks", []),
                blocking_failures=v.get("blocking_failures", []),
                warnings=v.get("warnings", []),
            )

    # 反序列化 message_history
    state.message_history = data.get("message_history", [])

    # 反序列化 tasks
    for t in data.get("tasks", []):
        from travel_planning_agent.types import Task, TaskStatus
        state.tasks.append(Task(
            task_id=t["task_id"],
            desc=t.get("desc", ""),
            status=TaskStatus(t.get("status", "pending")),
            acceptance=t.get("acceptance", ""),
            depends_on=t.get("depends_on", []),
        ))

    # 反序列化模块化规划字段
    state.planning_queue = data.get("planning_queue", [])
    state.module_context = data.get("module_context", {})
    state.current_module = data.get("current_module")
    state.current_module_retry_count = data.get("current_module_retry_count", 0)
    state.current_module_max_retries = data.get("current_module_max_retries", 2)

    return state


# ── 公开接口 ──────────────────────────────────────────

def init_trip_dir(trip_id: str) -> str:
    """
    创建 data/trips/{trip_id}/ 目录，返回路径。
    """
    trip_dir = _get_trip_dir(trip_id)
    evidence_dir = _get_evidence_dir(trip_id)
    _ensure_dir(trip_dir)
    _ensure_dir(evidence_dir)
    logger.info("创建行程目录: %s", trip_dir)
    return str(trip_dir)


def save_state(state: PlanState) -> str:
    """
    将 PlanState 序列化为 JSON，写入 data/trips/{trip_id}/state.json。
    """
    trip_dir = _get_trip_dir(state.trip_id)
    _ensure_dir(trip_dir)

    filepath = trip_dir / "state.json"
    data = _plan_state_to_dict(state)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("状态已保存: %s", filepath)
    return str(filepath)


def load_state(trip_id: str) -> Optional[PlanState]:
    """
    从 data/trips/{trip_id}/state.json 读取并反序列化。
    如果文件不存在返回 None。
    """
    filepath = _get_trip_dir(trip_id) / "state.json"
    if not filepath.exists():
        logger.warning("状态文件不存在: %s", filepath)
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    state = _dict_to_plan_state(data)
    logger.info("状态已加载: %s", filepath)
    return state


def save_trip_md(state: PlanState) -> str:
    """
    将行程渲染为 Markdown，写入 data/trips/{trip_id}/trip.md。
    同时保存多版本文件 plan_v{version}.md。

    Phase 2 新增：多版本支持、Pins 标注、Assumption 状态、校验报告
    """
    trip_dir = _get_trip_dir(state.trip_id)
    _ensure_dir(trip_dir)

    lines: list[str] = []
    c = state.constraints

    # ── YAML 前头 ──
    lines.append("---")
    if c:
        lines.append(f"destination: {c.destination}")
        lines.append(f"dates: {c.start_date} ~ {c.start_date.isoformat()}")
        travelers_desc = "、".join(
            f"{len([t for t in c.travelers if t.age_group == g])}位{ {'adult': '成人', 'elderly': '老人', 'child': '小孩'}.get(g, g) }"
            for g in ["adult", "elderly", "child"]
            if any(t.age_group == g for t in c.travelers)
        )
        lines.append(f"travelers: {travelers_desc}")
        lines.append(f"budget: {c.budget} CNY")
        lines.append(f"pace: {c.pace}")
    lines.append(f"status: {state.status.value}")
    lines.append("---")
    lines.append("")

    # ── 校验状态 ──
    if state.validation:
        if state.validation.overall_pass:
            lines.append("> ✅ 所有校验通过")
        else:
            rules = getattr(state.validation, 'rule_checks', None) or getattr(state.validation, 'rules', [])
            fail_count = sum(1 for r in rules if r.result == "FAIL")
            lines.append(f"> ⚠️ 部分校验未通过（{fail_count} 项失败）")
        lines.append("")

    # ── 每日行程 ──
    _cat_map = {
        SegmentType.TRANSPORT: "路程",
        SegmentType.ACTIVITY: "游玩",
        SegmentType.MEAL: "用餐",
        SegmentType.ACCOMMODATION: "住宿",
    }
    for day in state.days:
        lines.append(f"## Day {day.day_number} — {day.theme}")
        lines.append("")

        if day.day_note:
            lines.append(f"> {day.day_note}")
            lines.append("")

        prev_type = None
        for seg in day.segments:
            # 添加分类小标题
            if seg.type != prev_type:
                cat_name = _cat_map.get(seg.type)
                if cat_name:
                    lines.append(f"### {cat_name}")
                prev_type = seg.type

            time_str = ""
            if seg.start_time and seg.end_time:
                time_str = f"{seg.start_time}-{seg.end_time}  "

            cost_str = ""
            if seg.estimated_cost and seg.estimated_cost.amount > 0:
                cost_str = f" (¥{seg.estimated_cost.amount:,.0f})"

            tags_str = ""
            if seg.tags:
                tag_labels = [t.replace("_", " ") for t in seg.tags]
                tags_str = f"  [{', '.join(tag_labels)}]"

            note_str = f" _{seg.note}_" if seg.note else ""
            lines.append(f"- {time_str}{seg.title}{cost_str}{tags_str}{note_str}")

            # 证据来源
            for eid in seg.evidence_ids:
                evidence = state.evidence.get(eid)
                if evidence and evidence.claim:
                    lines.append(f"  - 来源: {evidence.source} — {evidence.claim}")
                    if evidence.url:
                        lines.append(f"    URL: {evidence.url}")

        lines.append("")

    # ── 修订信息 ──
    if state.revision_count > 0:
        lines.append(f"---")
        lines.append(f"*已修订 {state.revision_count} 次*")
        lines.append("")

    # ── Pins 信息 ──
    if state.pins:
        lines.append("### 锁定项")
        for pin in state.pins:
            status = "🔒 已锁定" if not pin.mutable else ""
            lines.append(f"- {pin.target_id} ({pin.target_type}) {status}")
        lines.append("")

    # ── Assumptions ──
    if state.assumptions:
        confirmed = [a for a in state.assumptions if a.status.value == "confirmed"]
        if confirmed:
            lines.append("### 已确认假设")
            for a in confirmed:
                lines.append(f"- {a.content}")
            lines.append("")

    filepath = trip_dir / "trip.md"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 多版本保存
    if state.plan_version > 0:
        version_path = trip_dir / f"plan_v{state.plan_version}.md"
        with open(version_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    logger.info("Markdown 行程已保存: %s", filepath)
    return str(filepath)


def save_evidence(state: PlanState) -> list[str]:
    """
    将 evidence 字典逐条写入 data/trips/{trip_id}/evidence/ev_{id}.json。
    返回写入的文件路径列表。
    """
    evidence_dir = _get_evidence_dir(state.trip_id)
    _ensure_dir(evidence_dir)

    saved_paths: list[str] = []
    for eid, ev in state.evidence.items():
        filepath = evidence_dir / f"{eid}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(_evidence_to_dict(ev), f, ensure_ascii=False, indent=2)
        saved_paths.append(str(filepath))

    logger.info("已保存 %d 条证据到 %s", len(saved_paths), evidence_dir)
    return saved_paths


def list_trips() -> list[str]:
    """
    列出 data/trips/ 下所有 trip_id。
    返回 trip_id 列表，按目录修改时间降序排列。
    """
    trips_dir = _get_data_dir() / "trips"
    if not trips_dir.exists():
        return []

    trips = []
    for entry in trips_dir.iterdir():
        if entry.is_dir() and (entry / "state.json").exists():
            trips.append(entry.name)

    # 按修改时间降序排列
    trips.sort(key=lambda t: (trips_dir / t).stat().st_mtime, reverse=True)
    return trips
