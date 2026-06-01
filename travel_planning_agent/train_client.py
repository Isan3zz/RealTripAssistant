"""
train_client.py — 火车票查询 MCP 客户端

连接 ModelScope 部署的 Train-ticket-inquiry MCP 服务。
"""

import json
import logging
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_MCP_URL = "https://mcp.api-inference.modelscope.net/45adc70f5a6148/mcp"
_REQUEST_TIMEOUT = 20


def _call_tool(tool_name: str, params: dict = None) -> Optional[dict]:
    """调用 MCP 工具，返回 result。"""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params or {},
        },
    }).encode()

    try:
        req = Request(_MCP_URL, data=body, headers={
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            if "result" in data:
                return data["result"]
            logger.warning("Train MCP 返回错误: %s", data.get("error", data))
            return None
    except URLError as e:
        logger.warning("Train MCP 请求失败: %s", e)
        return None
    except Exception as e:
        logger.warning("Train MCP 异常: %s", e)
        return None


def _list_tools() -> list[dict]:
    """获取 MCP 可用工具列表。"""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
    }).encode()

    try:
        req = Request(_MCP_URL, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return (data.get("result") or {}).get("tools", [])
    except Exception:
        return []


def search_train_mcp(from_station: str, to_station: str, date: str, is_high_speed: bool = False) -> Optional[list]:
    """
    通过 MCP 查询火车票。

    参数：
        from_station: 出发站（如"南京"）
        to_station: 到达站（如"杭州"）
        date: 日期 YYYY-MM-DD
        is_high_speed: 是否只查高铁/动车

    返回车次列表，失败返回 None。
    """
    result = _call_tool("train_query_ticket", {
        "start": from_station,
        "end": to_station,
        "date": date,
        "ishigh": "1" if is_high_speed else "0",
    })

    if result:
        # MCP 返回 content 数组，每项 text 是 JSON
        content = result.get("content", [])
        for c in content:
            if isinstance(c, dict):
                text = c.get("text", "")
                if text:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    # 从嵌套结构中提取车次列表
                    if isinstance(parsed, dict):
                        data = parsed.get("data") or parsed
                        if isinstance(data, dict):
                            train_list = data.get("list") or data.get("trains") or data.get("results")
                            if isinstance(train_list, list) and train_list:
                                return train_list
                        elif isinstance(data, list):
                            return data
                    elif isinstance(parsed, list):
                        return parsed

        # 也可能是平铺字段
        data = result.get("data") or result.get("trains")
        if isinstance(data, list):
            return data

    return None
