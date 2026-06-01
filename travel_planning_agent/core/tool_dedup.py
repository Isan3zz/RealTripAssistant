"""Exact tool-call deduplication helpers."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, MutableMapping
from datetime import date, datetime
from typing import Any


REGISTRY_KEY = "_tool_calls"
_LOCK_GUARD = threading.Lock()
_FINGERPRINT_LOCKS: dict[tuple[int, str], threading.RLock] = {}


def normalize_tool_args(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): normalize_tool_args(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
            if value[key] is not None
        }
    if isinstance(value, list):
        return [normalize_tool_args(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_tool_args(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def tool_call_fingerprint(tool_name: str, args: Mapping[str, Any] | None) -> str:
    payload = {
        "tool": tool_name,
        "args": normalize_tool_args(args or {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_tool_call_lock(
    registry: Mapping[str, dict] | None,
    tool_name: str,
    args: Mapping[str, Any] | None,
) -> threading.RLock:
    fingerprint = tool_call_fingerprint(tool_name, args)
    key = (id(registry), fingerprint)
    with _LOCK_GUARD:
        lock = _FINGERPRINT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _FINGERPRINT_LOCKS[key] = lock
        return lock


def get_tool_call_registry(context: MutableMapping[str, Any] | None) -> MutableMapping[str, dict]:
    if context is None:
        return {}
    registry = context.setdefault(REGISTRY_KEY, {})
    if not isinstance(registry, dict):
        registry = {}
        context[REGISTRY_KEY] = registry
    return registry


def find_tool_call(
    registry: Mapping[str, dict] | None,
    tool_name: str,
    args: Mapping[str, Any] | None,
) -> dict | None:
    if not registry:
        return None
    fingerprint = tool_call_fingerprint(tool_name, args)
    item = registry.get(fingerprint)
    if not isinstance(item, dict):
        return None
    if item.get("status") != "success":
        return None
    if not item.get("evidence_ids"):
        return None
    return item


def remember_tool_call(
    registry: MutableMapping[str, dict],
    tool_name: str,
    args: Mapping[str, Any] | None,
    *,
    status: str,
    evidence_ids: list[str] | None = None,
    task_id: str | None = None,
) -> str:
    fingerprint = tool_call_fingerprint(tool_name, args)
    registry[fingerprint] = {
        "fingerprint": fingerprint,
        "tool": tool_name,
        "args": normalize_tool_args(args or {}),
        "status": status,
        "evidence_ids": list(evidence_ids or []),
        "task_id": task_id,
        "updated_at": datetime.now().isoformat(),
    }
    return fingerprint
