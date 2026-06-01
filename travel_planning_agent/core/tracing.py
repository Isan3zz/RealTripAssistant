"""JSON-file tracing for backend auditability."""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from travel_planning_agent.config import settings

_MAX_STRING_LENGTH = 4000
_MAX_LIST_ITEMS = 50
_MAX_DICT_ITEMS = 80

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_trace_session_id: ContextVar[Optional[str]] = ContextVar("trace_session_id", default=None)
_trace_trip_id: ContextVar[Optional[str]] = ContextVar("trace_trip_id", default=None)
_trace_run_id: ContextVar[Optional[str]] = ContextVar("trace_run_id", default=None)


def create_trace_id() -> str:
    return f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def set_trace_context(
    trace_id: str,
    *,
    session_id: str | None = None,
    trip_id: str | None = None,
    run_id: str | None = None,
) -> None:
    _trace_id.set(trace_id)
    if session_id is not None:
        _trace_session_id.set(session_id)
    if trip_id is not None:
        _trace_trip_id.set(trip_id)
    if run_id is not None:
        _trace_run_id.set(run_id)


def clear_trace_context() -> None:
    _trace_id.set(None)
    _trace_session_id.set(None)
    _trace_trip_id.set(None)
    _trace_run_id.set(None)


def current_trace_id() -> str | None:
    return _trace_id.get()


def record_trace_event(
    event_type: str,
    stage: str,
    data: dict | None = None,
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    trip_id: str | None = None,
    run_id: str | None = None,
) -> None:
    tid = trace_id or _trace_id.get()
    if not tid:
        return

    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "stage": stage,
        "session_id": session_id if session_id is not None else _trace_session_id.get(),
        "trip_id": trip_id if trip_id is not None else _trace_trip_id.get(),
        "run_id": run_id if run_id is not None else _trace_run_id.get(),
        "data": summarize_payload(data or {}),
    }

    path = _trace_file_path(tid)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            trace_doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            trace_doc = _new_trace_doc(tid)
    else:
        trace_doc = _new_trace_doc(tid)

    trace_doc.setdefault("events", []).append(event)
    trace_doc["updated_at"] = event["timestamp"]
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(trace_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def summarize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_DICT_ITEMS:
                result["__truncated__"] = f"dict limited to {_MAX_DICT_ITEMS} keys"
                break
            result[str(key)] = summarize_payload(item)
        return result
    if isinstance(value, list):
        result = [summarize_payload(item) for item in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            result.append({"__truncated__": f"list limited to {_MAX_LIST_ITEMS} items"})
        return result
    if isinstance(value, tuple):
        return summarize_payload(list(value))
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            return value[:_MAX_STRING_LENGTH] + "...<truncated>"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _trace_file_path(trace_id: str) -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    safe_trace_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in trace_id)
    return Path(settings.data_dir) / "traces" / day / f"{safe_trace_id}.json"


def _new_trace_doc(trace_id: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "trace_id": trace_id,
        "created_at": now,
        "updated_at": now,
        "events": [],
    }
