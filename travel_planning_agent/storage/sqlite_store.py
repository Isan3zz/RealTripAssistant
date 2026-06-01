"""
storage/sqlite_store.py — SQLite 缓存 + 成本日志

cache.db:  工具调用结果缓存（带 TTL），减少重复调用
cost_log.db: LLM 调用成本记录，Phase 3 预算评估用
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from travel_planning_agent.config import settings

logger = logging.getLogger(__name__)

_local = threading.local()


def _get_db_path(db_name: str) -> str:
    """获取数据库文件路径。"""
    data_dir = getattr(settings, 'data_dir', 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, db_name)


def _get_cache_conn() -> sqlite3.Connection:
    """获取 cache.db 连接（线程本地）。"""
    if not hasattr(_local, 'cache_conn') or _local.cache_conn is None:
        path = _get_db_path("cache.db")
        _local.cache_conn = sqlite3.connect(path)
        _local.cache_conn.row_factory = sqlite3.Row
        _init_cache_db(_local.cache_conn)
    return _local.cache_conn


def _get_cost_conn() -> sqlite3.Connection:
    """获取 cost_log.db 连接（线程本地）。"""
    if not hasattr(_local, 'cost_conn') or _local.cost_conn is None:
        path = _get_db_path("cost_log.db")
        _local.cost_conn = sqlite3.connect(path)
        _local.cost_conn.row_factory = sqlite3.Row
        _init_cost_db(_local.cost_conn)
    return _local.cost_conn


def _init_cache_db(conn: sqlite3.Connection):
    """初始化 cache.db 表结构。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_cache (
            cache_key TEXT PRIMARY KEY,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ttl_seconds INTEGER DEFAULT 3600
        )
    """)
    # 清理过期数据
    conn.execute("""
        DELETE FROM tool_cache
        WHERE datetime(created_at, '+' || ttl_seconds || ' seconds') < datetime('now')
    """)
    conn.commit()


def _init_cost_db(conn: sqlite3.Connection):
    """初始化 cost_log.db 表结构。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            estimated_cost REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_log_trip ON cost_log(trip_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_log_created ON cost_log(created_at)
    """)
    conn.commit()


# ── 缓存操作 ──────────────────────────────────────────

def cache_get(cache_key: str) -> Optional[Any]:
    """从缓存中获取结果。"""
    try:
        conn = _get_cache_conn()
        cursor = conn.execute(
            "SELECT result, created_at, ttl_seconds FROM tool_cache WHERE cache_key = ?",
            (cache_key,),
        )
        row = cursor.fetchone()
        if row:
            created = datetime.fromisoformat(row["created_at"])
            ttl = timedelta(seconds=row["ttl_seconds"])
            if datetime.now() - created < ttl:
                return json.loads(row["result"])
            else:
                # 过期删除
                conn.execute("DELETE FROM tool_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()
    except Exception as e:
        logger.warning("缓存读取失败: %s", e)
    return None


def cache_set(cache_key: str, result: Any, ttl_seconds: int = 3600):
    """写入缓存。"""
    try:
        conn = _get_cache_conn()
        conn.execute(
            "INSERT OR REPLACE INTO tool_cache (cache_key, result, created_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (cache_key, json.dumps(result, ensure_ascii=False), datetime.now().isoformat(), ttl_seconds),
        )
        conn.commit()
    except Exception as e:
        logger.warning("缓存写入失败: %s", e)


def build_cache_key(tool_name: str, **params) -> str:
    """构建缓存键。"""
    key_parts = [tool_name]
    for k, v in sorted(params.items()):
        key_parts.append(f"{k}={v}")
    import hashlib
    raw = "&".join(key_parts)
    return hashlib.md5(raw.encode()).hexdigest()


# ── 成本日志 ──────────────────────────────────────────

def log_cost(
    trip_id: str,
    request_id: str,
    agent_name: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
):
    """记录 LLM 调用成本。"""
    try:
        conn = _get_cost_conn()
        conn.execute(
            "INSERT INTO cost_log (trip_id, request_id, agent_name, model_name, input_tokens, output_tokens, estimated_cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (trip_id, request_id, agent_name, model_name, input_tokens, output_tokens, estimated_cost, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.warning("成本日志写入失败: %s", e)


def get_trip_costs(trip_id: str) -> list[dict]:
    """查询单次行程的成本记录。"""
    try:
        conn = _get_cost_conn()
        cursor = conn.execute(
            "SELECT * FROM cost_log WHERE trip_id = ? ORDER BY created_at",
            (trip_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.warning("成本查询失败: %s", e)
        return []


def get_total_costs() -> dict:
    """获取总成本统计。"""
    try:
        conn = _get_cost_conn()
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(input_tokens) as total_input,
                SUM(output_tokens) as total_output,
                SUM(estimated_cost) as total_cost
            FROM cost_log
        """)
        row = cursor.fetchone()
        if row:
            return dict(row)
    except Exception as e:
        logger.warning("成本统计失败: %s", e)
    return {"total_calls": 0, "total_input": 0, "total_output": 0, "total_cost": 0}
