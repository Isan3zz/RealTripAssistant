"""
gaode_client.py — 高德地图 MCP 客户端（Streamable HTTP 协议）

遵循 MCP Streamable HTTP 规范：
  1. initialize → 协议版本协商 + 获取服务端能力
  2. initialized → 确认初始化
  3. tools/list → 获取可用工具列表
  4. tools/call → 调用具体工具
  5. 连接复用，_MCP_BASE 全局缓存
"""

import json
import logging
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

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

# ── 协议常量 ──

_MCP_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_INFO = {"name": "real-trip-assistant", "version": "0.3.0"}
_REQUEST_TIMEOUT = 15

# ── 全局缓存 ──

_MCP_BASE: Optional[dict] = None  # {"server_info": ..., "capabilities": ..., "tools": [...]}
_MCP_URL: Optional[str] = None


# ═══════════════════════════════════════════════════════
#  内部：JSON-RPC over HTTP
# ═══════════════════════════════════════════════════════

def _json_rpc_request(method: str, params: dict = None, request_id: int = 1) -> Optional[dict]:
    """
    发送 JSON-RPC 请求到 MCP 端点。
    返回 result 字段，失败返回 None。
    """
    global _MCP_URL
    if not _MCP_URL:
        from travel_planning_agent.config import settings
        if not settings.gaode_key:
            logger.warning("高德 API Key 未配置")
            return None
        _MCP_URL = f"https://mcp.amap.com/mcp?key={settings.gaode_key}"

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }).encode()

    try:
        req = Request(_MCP_URL, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            if "result" in data:
                return data["result"]
            logger.warning("MCP 返回错误: %s", data.get("error", data))
            return None
    except URLError as e:
        logger.warning("MCP 请求失败: %s", e)
        return None
    except Exception as e:
        logger.warning("MCP 异常: %s", e)
        return None


def _send_notification(method: str, params: dict = None):
    """
    发送 JSON-RPC 通知（无 id，不等待响应）。
    通知是 fire-and-forget 的，忽略一切错误。
    """
    global _MCP_URL
    if not _MCP_URL:
        return

    body = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }).encode()

    try:
        req = Request(_MCP_URL, data=body, headers={
            "Content-Type": "application/json",
        })
        # 使用短 timeout，不关心响应
        urlopen(req, timeout=3)
    except Exception:
        pass  # 通知可安全忽略


# ═══════════════════════════════════════════════════════
#  初始化 + 工具发现
# ═══════════════════════════════════════════════════════

def ensure_initialized() -> bool:
    """
    确保 MCP 连接已初始化（懒加载，全局缓存）。
    返回 True 表示初始化成功可用。
    """
    global _MCP_BASE
    if _MCP_BASE is not None:
        return True

    # Step 1: initialize → 协议协商 + 获取服务端能力
    init_result = _json_rpc_request("initialize", {
        "protocolVersion": _MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": _CLIENT_INFO,
    })
    if init_result is None:
        return False

    # Step 2: initialized → 通知服务端确认初始化完成（通知无需 id，不需要响应）
    _send_notification("notifications/initialized")

    # Step 3: tools/list → 获取可用工具列表
    tools_result = _json_rpc_request("tools/list")
    tools = []
    if tools_result and "tools" in tools_result:
        tools = tools_result["tools"]
        logger.info("高德 MCP 已初始化，发现 %d 个工具", len(tools))
    else:
        logger.warning("高德 MCP 工具列表获取失败")

    _MCP_BASE = {
        "server_info": init_result.get("serverInfo", {}),
        "capabilities": init_result.get("capabilities", {}),
        "protocol_version": init_result.get("protocolVersion", _MCP_PROTOCOL_VERSION),
        "tools": tools,
    }
    return True


def list_tools() -> list[dict]:
    """
    列出高德 MCP 服务端所有可用工具。
    返回工具定义列表，每个包含 name/description/inputSchema。
    """
    if not ensure_initialized():
        return []
    return _MCP_BASE.get("tools", [])


def get_server_info() -> dict:
    """返回 MCP 服务端信息。"""
    if not ensure_initialized():
        return {}
    return {
        "server_info": _MCP_BASE.get("server_info"),
        "capabilities": _MCP_BASE.get("capabilities"),
        "protocol_version": _MCP_BASE.get("protocol_version"),
    }


# ═══════════════════════════════════════════════════════
#  工具调用
# ═══════════════════════════════════════════════════════

def _call_tool(tool_name: str, arguments: dict) -> Optional[Any]:
    """调用 MCP 工具，返回 content 部分。"""
    if not ensure_initialized():
        return None
    logger.debug("Gaode MCP call: name=%s args=%s", tool_name, _preview(arguments or {}))
    result = _json_rpc_request("tools/call", {"name": tool_name, "arguments": arguments})
    logger.debug("Gaode MCP raw result: name=%s raw=%s", tool_name, _preview(result))
    if result and "content" in result:
        logger.debug("Gaode MCP raw content: name=%s content=%s", tool_name, _preview(result["content"]))
        return result["content"]
    return None


# ═══════════════════════════════════════════════════════
#  对外接口
# ═══════════════════════════════════════════════════════

def search_poi_text(keywords: str, city: str = "", city_limit: bool = False) -> Optional[list]:
    """关键字搜索 POI（MCP 工具: maps_text_search）。"""
    args = {"keywords": keywords}
    if city:
        args["city"] = city
    if city_limit:
        args["citylimit"] = True
    return _call_tool("maps_text_search", args)


def search_around(location: str, keywords: str, radius: str = "") -> Optional[list]:
    """周边搜索（MCP 工具: maps_around_search）。"""
    args = {"keywords": keywords, "location": location}
    if radius:
        args["radius"] = radius
    return _call_tool("maps_around_search", args)


def get_weather(city: str) -> Optional[Any]:
    """获取天气预报（MCP 工具: maps_weather）。"""
    return _call_tool("maps_weather", {"city": city})


def get_driving_eta(origin: str, destination: str) -> Optional[Any]:
    """驾车路线规划（MCP 工具: maps_direction_driving）。"""
    return _call_tool("maps_direction_driving", {
        "origin": origin,
        "destination": destination,
    })


def get_transit_eta(origin: str, destination: str, city: str, cityd: str) -> Optional[Any]:
    """公交路线规划（MCP 工具: maps_direction_transit_integrated）。"""
    return _call_tool("maps_direction_transit_integrated", {
        "origin": origin, "destination": destination,
        "city": city, "cityd": cityd,
    })


def geo_encode(address: str, city: str = "") -> Optional[Any]:
    """地理编码——地址转坐标（MCP 工具: maps_geo）。"""
    args = {"address": address}
    if city:
        args["city"] = city
    return _call_tool("maps_geo", args)


def get_poi_detail(poi_id: str) -> Optional[Any]:
    """POI 详情查询（MCP 工具: maps_search_detail）。"""
    return _call_tool("maps_search_detail", {"id": poi_id})


# 我们的工具名 → MCP 工具名映射（MCP 用 maps_ 前缀，我们用英文名）
_GAODE_TOOL_ALIAS: dict[str, str] = {
    "get_driving_eta": "maps_direction_driving",
    "get_walking_route": "maps_direction_walking",
    "get_transit_route": "maps_direction_transit_integrated",
    "geo_encode": "maps_geo",
    "search_around": "maps_around_search",
    "get_weather_forecast": "maps_weather",
    "search_poi": "maps_text_search",
    "get_poi_detail": "maps_search_detail",
}
# 反向映射：MCP 名 → 我们的名
_MCP_TO_OUR_NAME = {v: k for k, v in _GAODE_TOOL_ALIAS.items()}


def resolve_mcp_tool_name(tool_name: str) -> str:
    """Return the MCP-native tool name for an internal/public tool alias."""
    return _GAODE_TOOL_ALIAS.get(tool_name, tool_name)


def get_openai_tools() -> list[dict]:
    """
    从高德 MCP 服务端动态获取工具列表，转换为 OpenAI function-calling 格式。
    失败时返回空列表。
    """
    if not ensure_initialized():
        return []
    mcp_tools = list_tools()
    result = []
    for mt in mcp_tools:
        name = mt.get("name", "")
        # 通过别名映射或直接用 MCP 原生名
        openai_name = _MCP_TO_OUR_NAME.get(name, name)
        schema = mt.get("inputSchema", {})
        result.append({
            "type": "function",
            "function": {
                "name": openai_name,
                "description": mt.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        })
    return result


def reset():
    """重置客户端缓存（主要用于测试）。"""
    global _MCP_BASE, _MCP_URL
    _MCP_BASE = None
    _MCP_URL = None
