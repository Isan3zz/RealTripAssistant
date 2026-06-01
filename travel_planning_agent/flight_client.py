"""
flight_client.py — 航班查询 MCP 客户端

连接 ModelScope 部署的 Airline-flight-inquiry MCP 服务。
"""

import json
import logging
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_MCP_URL = "https://mcp.api-inference.modelscope.net/b89b4f8382b741/mcp"
_REQUEST_TIMEOUT = 20

# 常见城市 → IATA 三字码映射
_CITY_IATA = {
    "北京": "BJS", "北京首都": "PEK", "北京大兴": "PKX",
    "上海": "SHA", "上海虹桥": "SHA", "上海浦东": "PVG",
    "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "成都天府": "TFU",
    "杭州": "HGH", "南京": "NKG",
    "重庆": "CKG", "西安": "XIY",
    "昆明": "KMG", "武汉": "WUH",
    "长沙": "CSX", "厦门": "XMN",
    "青岛": "TAO", "大连": "DLC",
    "三亚": "SYX", "海口": "HAK",
    "哈尔滨": "HRB", "沈阳": "SHE",
    "贵阳": "KWE", "南宁": "NNG",
    "郑州": "CGO", "济南": "TNA",
    "福州": "FOC", "兰州": "LHW",
    "乌鲁木齐": "URC", "拉萨": "LXA",
    "天津": "TSN", "石家庄": "SJW",
    "太原": "TYN", "合肥": "HFE",
    "南昌": "KHN", "呼和浩特": "HET",
}


def _city_to_iata(city: str) -> str:
    """城市名转 IATA 三字码，找不到返回原值。"""
    # 先精确匹配
    if city in _CITY_IATA:
        return _CITY_IATA[city]
    # 模糊匹配：取前两个字
    for key, code in _CITY_IATA.items():
        if city[:2] in key or key[:2] in city:
            return code
    return city


def _call_tool(tool_name: str, params: dict = None) -> Optional[dict]:
    """调用 MCP 工具。"""
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
            logger.warning("Flight MCP 返回错误: %s", data.get("error", data))
            return None
    except URLError as e:
        logger.warning("Flight MCP 请求失败: %s", e)
        return None
    except Exception as e:
        logger.warning("Flight MCP 异常: %s", e)
        return None


def search_flight_mcp(from_city: str, to_city: str, date: str) -> Optional[list]:
    """
    通过 MCP 查询航班。

    参数：
        from_city: 出发城市
        to_city: 到达城市
        date: 日期 YYYY-MM-DD

    返回航班列表，失败返回 None。
    """
    dep_iata = _city_to_iata(from_city)
    arr_iata = _city_to_iata(to_city)

    result = _call_tool("search_flight_by_route", {
        "departure": dep_iata,
        "arrival": arr_iata,
        "departureDate": date,
        "maxSegments": "1",  # 只需直飞
    })

    if result:
        content = result.get("content", [])
        for c in content:
            if isinstance(c, dict):
                text = c.get("text", "")
                if text:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    # 标准 MCP 返回路径: result.flightInfo
                    if isinstance(parsed, dict):
                        inner = parsed.get("result") or parsed
                        if isinstance(inner, dict):
                            flights = inner.get("flightInfo")
                            if isinstance(flights, list):
                                return flights
                        flights = (parsed.get("data") or parsed.get("flights")
                                   or parsed.get("list"))
                        if isinstance(flights, list) and flights:
                            return flights
                    elif isinstance(parsed, list):
                        return parsed

    return None
