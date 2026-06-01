"""tool_runtime.py — product-grade tool registry and result envelope."""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from travel_planning_agent.types import ToolResult

logger = logging.getLogger(__name__)
_MAX_LOG_VALUE_LENGTH = 2000


def _preview(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    if len(text) > _MAX_LOG_VALUE_LENGTH:
        return text[:_MAX_LOG_VALUE_LENGTH] + "...<truncated>"
    return text


@dataclass
class ToolSpec:
    name: str
    description: str
    agents: list[str] = field(default_factory=list)
    ttl_seconds: int = 0
    source_type: str = "api"
    default_confidence: str = "high"
    handler: Optional[Callable[[dict], str]] = None
    openai_schema: Optional[dict] = None
    param_aliases: dict[str, str] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def register_openai_tool(
        self,
        schema: dict,
        agents: Optional[list[str]] = None,
        ttl_seconds: int = 0,
        source_type: str = "api",
        default_confidence: str = "high",
        handler: Optional[Callable[[dict], str]] = None,
        param_aliases: Optional[dict[str, str]] = None,
    ) -> None:
        name = schema.get("function", {}).get("name", "")
        if not name:
            return
        existing = self._tools.get(name)
        if existing:
            existing.description = schema.get("function", {}).get("description", existing.description)
            existing.openai_schema = schema
            existing.agents = agents or existing.agents
            existing.ttl_seconds = ttl_seconds or existing.ttl_seconds
            existing.source_type = source_type or existing.source_type
            existing.default_confidence = default_confidence or existing.default_confidence
            existing.handler = handler or existing.handler
            existing.param_aliases = param_aliases or existing.param_aliases
            return
        self.register(ToolSpec(
            name=name,
            description=schema.get("function", {}).get("description", name),
            agents=agents or [],
            ttl_seconds=ttl_seconds,
            source_type=source_type,
            default_confidence=default_confidence,
            handler=handler,
            openai_schema=schema,
            param_aliases=param_aliases or {},
        ))

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_for_agent(self, agent_name: str) -> list[ToolSpec]:
        if agent_name == "*":
            return list(self._tools.values())
        return [
            spec for spec in self._tools.values()
            if not spec.agents or agent_name in spec.agents
        ]

    def openai_tools_for_agent(self, agent_name: str) -> list[dict]:
        return [
            spec.openai_schema for spec in self.list_for_agent(agent_name)
            if spec.openai_schema
        ]

    def execute(self, name: str, args: dict) -> ToolResult:
        started = time.perf_counter()
        spec = self.get(name)
        if not spec:
            logger.warning("Tool call skipped: unknown tool=%s args=%s", name, _preview(args or {}))
            result = ToolResult(
                status="failed",
                error=f"未知工具: {name}",
                retrieved_at=datetime.now().isoformat(),
            )
            _record_tool_trace(name, args or {}, result, started)
            return result

        normalized_args = self._normalize_args(spec, dict(args or {}))
        try:
            if spec.handler:
                logger.info("Tool call: name=%s args=%s", name, _preview(normalized_args))
                text = spec.handler(normalized_args)
            else:
                logger.warning("Tool call skipped: missing executor name=%s args=%s", name, _preview(normalized_args))
                result = ToolResult(
                    status="failed",
                    error=f"工具未注册执行器: {name}",
                    retrieved_at=datetime.now().isoformat(),
                    source_type=spec.source_type,
                    confidence="low",
                )
                _record_tool_trace(name, normalized_args, result, started)
                return result
        except Exception as e:
            logger.exception("Tool call failed: name=%s args=%s", name, _preview(normalized_args))
            result = ToolResult(
                status="failed",
                error=str(e),
                retrieved_at=datetime.now().isoformat(),
                source_type=spec.source_type,
                confidence="low",
            )
            _record_tool_trace(name, normalized_args, result, started)
            return result

        status = "success"
        confidence = spec.default_confidence
        if not text or "查询失败" in text or "暂未查到" in text or text.startswith("错误："):
            status = "degraded"
            confidence = "low"

        logger.info(
            "Tool parsed result: name=%s status=%s confidence=%s data=%s",
            name,
            status,
            confidence,
            _preview(text),
        )

        evidence = []
        if text:
            evidence.append({
                "source": spec.name,
                "source_type": spec.source_type if status == "success" else "model_knowledge",
                "confidence": confidence,
                "claim": text,
                "retrieved_at": datetime.now().isoformat(),
            })

        result = ToolResult(
            status=status,
            data=text,
            evidence=evidence,
            source_type=spec.source_type if status == "success" else "model_knowledge",
            confidence=confidence,
            retrieved_at=datetime.now().isoformat(),
            error=None if status == "success" else text,
            cache_hit=False,
        )
        _record_tool_trace(name, normalized_args, result, started)
        return result

    @staticmethod
    def _normalize_args(spec: ToolSpec, args: dict) -> dict:
        for wrong, correct in spec.param_aliases.items():
            if wrong in args and correct not in args:
                args[correct] = args.pop(wrong)
        return args


registry = ToolRegistry()


def _register_defaults() -> None:
    defaults = [
        ToolSpec("get_current_date", "获取当前日期", ["intake"], 3600, "system", "high"),
        ToolSpec("search_poi", "搜索 POI 信息", ["researcher"], 86400, "api", "high"),
        ToolSpec("get_weather_forecast", "获取天气预报", ["researcher", "planner"], 21600, "api", "high"),
        ToolSpec("query_ticket_price", "查询景点门票价格", ["researcher"], 3600, "api", "high"),
        ToolSpec("search_hotel", "搜索酒店", ["researcher"], 86400, "api", "high"),
        ToolSpec("get_hotel_detail", "查询酒店详情", ["researcher"], 86400, "api", "high"),
        ToolSpec("search_flight", "搜索航班", ["researcher"], 3600, "api", "high"),
        ToolSpec("search_train", "搜索火车", ["researcher"], 3600, "api", "high"),
        ToolSpec("get_driving_eta", "驾车路线 ETA", ["planner"], 43200, "api", "high"),
        ToolSpec("get_walking_route", "步行路线", ["planner"], 43200, "api", "high"),
        ToolSpec("get_transit_route", "公交路线", ["planner"], 43200, "api", "high"),
        ToolSpec("geo_encode", "地址转坐标", ["researcher", "planner"], 86400, "api", "high"),
        ToolSpec("search_around", "周边搜索", ["researcher"], 86400, "api", "high"),
    ]
    for spec in defaults:
        registry.register(spec)


_register_defaults()


def execute_registered_tool(name: str, args: dict) -> ToolResult:
    return registry.execute(name, args)


def _record_tool_trace(name: str, args: dict, result: ToolResult, started: float) -> None:
    try:
        from travel_planning_agent.core.tracing import record_trace_event

        record_trace_event(
            "tool_call",
            "tool",
            {
                "tool": name,
                "input": args,
                "output": {
                    "status": result.status,
                    "data": result.data,
                    "error": result.error,
                    "confidence": result.confidence,
                    "source_type": result.source_type,
                    "cache_hit": result.cache_hit,
                },
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
    except Exception:
        logger.exception("Failed to write tool trace event")


def register_openai_tool(*args, **kwargs) -> None:
    registry.register_openai_tool(*args, **kwargs)


def openai_tools_for_agent(agent_name: str) -> list[dict]:
    return registry.openai_tools_for_agent(agent_name)


# ═══════════════════════════════════════════════════
#  工具注册装配（原 tools/registry.py）
# ═══════════════════════════════════════════════════

# NOTE: HANDLERS and get_all_tool_schemas 在函数内延迟导入，
# 避免 tool_runtime ↔ tools 包之间的循环导入。

PARAM_ALIASES = {
    "query_ticket_price": {"destination": "scenic_name", "name": "scenic_name", "spot": "scenic_name"},
    "search_poi": {"keyword": "context", "name": "context", "query": "context"},
    "get_poi_detail": {"poi_id": "id"},
    "search_hotel": {
        "name": "keyword",
        "hotel": "keyword",
        "near": "nearby",
        "landmark": "nearby",
        "scenic_name": "nearby",
        "spot": "nearby",
        "area": "nearby",
    },
    "search_train": {"start": "from_station", "end": "to_station", "from": "from_station", "to": "to_station"},
    "search_flight": {"start": "from_city", "end": "to_city", "from_city": "from_city", "to_city": "to_city"},
}


def _tool_agents(name: str) -> list[str]:
    if name == "get_current_date":
        return ["intake"]
    if name in {
        "search_poi", "query_ticket_price", "search_hotel", "get_hotel_detail",
        "search_flight", "search_train", "search_around", "geo_encode",
    }:
        return ["researcher"]
    if name == "get_weather_forecast":
        return ["researcher", "planner"]
    if name in {"get_driving_eta", "get_walking_route", "get_transit_route"}:
        return ["planner"]
    return ["__not_exposed_to_agents__"]


def _execute_handler(tool_name: str, tool_input: dict) -> str:
    from travel_planning_agent.tools.handlers import HANDLERS
    handler = HANDLERS.get(tool_name)
    if not handler:
        try:
            from travel_planning_agent.gaode_client import _call_tool, resolve_mcp_tool_name
            result = _call_tool(resolve_mcp_tool_name(tool_name), tool_input)
            return str(result) if result else f"错误：未知工具 '{tool_name}'"
        except Exception:
            return f"错误：未知工具 '{tool_name}'"

    try:
        result = handler(**tool_input)
        logger.info("工具 %s 调用成功", tool_name)
        return result
    except TypeError as e:
        return f"错误：工具 '{tool_name}' 参数不匹配 - {e}"
    except Exception as e:
        logger.warning("工具 %s 异常: %s", tool_name, e)
        return f"{tool_name}: 查询失败，请稍后重试"


def register_all_tools() -> None:
    from travel_planning_agent.tools.schemas import get_all_tool_schemas
    for schema in get_all_tool_schemas():
        name = schema.get("function", {}).get("name", "")
        register_openai_tool(
            schema,
            agents=_tool_agents(name),
            handler=lambda args, _name=name: _execute_handler(_name, args),
            param_aliases=PARAM_ALIASES.get(name, {}),
        )


register_all_tools()

TOOLS_DEFINITION: list = openai_tools_for_agent("*")
EXTRACTION_TOOLS: list = openai_tools_for_agent("intake")
RESEARCHER_TOOLS: list = openai_tools_for_agent("researcher")
PLANNER_TOOLS: list = openai_tools_for_agent("planner")


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """工具执行入口，保持字符串 API 供 Agent 使用。"""
    result = execute_registered_tool(tool_name, tool_input)
    return result.data or result.error or ""
