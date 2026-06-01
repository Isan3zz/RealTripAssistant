"""
tuniu_client.py — 途牛 CLI 客户端封装

通过 subprocess 调用 tuniu CLI，获取真实旅行数据。
调用失败时返回 None，由调用方决定降级策略（L2 知识兜底）。
"""

import json
import logging
import os
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)

import platform

TUNIU_CMD = "tuniu.cmd" if platform.system() == "Windows" else "tuniu"
TIMEOUT_SECONDS = 30


def _npm_bin_dir() -> str:
    """获取 npm 全局 bin 目录，用于 subprocess 找到 tuniu.cmd。"""
    import os
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return os.path.join(appdata, "npm")
    return ""


def _build_env() -> dict:
    """构建带 npm bin 目录的环境变量。"""
    env = os.environ.copy()
    npm_bin = _npm_bin_dir()
    if npm_bin:
        env["PATH"] = npm_bin + os.pathsep + env.get("PATH", "")
    return env


def _decode_stdout(raw: bytes) -> str:
    """尝试多种编码解码子进程输出。"""
    for enc in ("utf-8", "gbk", "gb2312", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def call_cli(server: str, tool: str, args: dict) -> Optional[dict]:
    """
    调用 tuniu CLI 的统一入口。

    API Key 从 config.py 的 tuniu_api_key 读取，自动传给子进程。
    """
    try:
        args_json = json.dumps(args, ensure_ascii=False)

        from travel_planning_agent.config import settings
        env = _build_env()
        if settings.tuniu_api_key:
            env["TUNIU_API_KEY"] = settings.tuniu_api_key

        result = subprocess.run(
            [TUNIU_CMD, "call", server, tool, "-a", args_json, "--output", "json"],
            capture_output=True, timeout=TIMEOUT_SECONDS, env=env,
        )

        if result.returncode != 0:
            stderr = _decode_stdout(result.stderr or b"").strip()
            logger.warning("途牛 CLI 调用失败 [%s.%s]: %s", server, tool, stderr)
            return None

        if not result.stdout or not result.stdout.strip():
            logger.warning("途牛 CLI 返回空结果 [%s.%s]", server, tool)
            return None

        outer = json.loads(_decode_stdout(result.stdout))

        # CLI 的 --output json 会把结果包在 result 的嵌套结构里
        result_data = outer.get("result", {})

        # 格式1: result.structuredContent.result（JSON 字符串）
        structured = result_data.get("structuredContent", {})
        if structured:
            inner = structured.get("result")
            if isinstance(inner, str):
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    pass
            elif isinstance(inner, dict):
                return inner

        # 格式2: result.content[0].text（JSON 字符串）
        content = result_data.get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0].get("text", "")
            if text and text.strip().startswith("{"):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass

        return outer

    except subprocess.TimeoutExpired:
        logger.warning("途牛 CLI 超时 [%s.%s] (%ds)", server, tool, TIMEOUT_SECONDS)
        return None
    except json.JSONDecodeError as e:
        logger.warning("途牛 CLI 返回非 JSON 结果 [%s.%s]: %s", server, tool, e)
        return None
    except FileNotFoundError:
        logger.error("未找到 tuniu 命令，请执行: npm install -g tuniu-cli")
        return None
    except Exception as e:
        logger.warning("途牛 CLI 异常 [%s.%s]: %s", server, tool, e)
        return None


def query_ticket_price(scenic_name: str) -> Optional[list[dict]]:
    """查询景点门票价格。"""
    data = call_cli("ticket", "query_cheapest_tickets", {"scenic_name": scenic_name})
    if not data:
        return None
    tickets = data.get("tickets", [])
    if not tickets:
        return None

    price_parts = []
    for t in tickets:
        ttype = t.get("ticketTypeName", t.get("ticketType", t.get("resName", "")))
        price = t.get("startPrice", t.get("price", "?"))
        price_parts.append(f"{ttype}: ¥{price}")
    claim_text = f"{scenic_name} 门票价格: {'; '.join(price_parts)}"

    return [{
        "title": scenic_name,
        "description": f"{scenic_name} 门票信息",
        "category": "ticket",
        "claim": claim_text,
        "source": "途牛门票",
        "source_type": "api",
        "confidence": "high",
        "detail": tickets,
    }]


def search_hotel(city: str, keyword: str = "", check_in: str = "", check_out: str = "") -> Optional[list[dict]]:
    """搜索酒店。"""
    args = {"cityName": city, "pageNum": 1}
    if keyword:
        args["keyword"] = keyword

    data = call_cli("hotel", "tuniu_hotel_search", args)
    if not data:
        return None

    hotels = data.get("hotels", data.get("list", data.get("data", [])))
    if not hotels or not isinstance(hotels, list):
        return None

    return [
        {
            "title": h.get("hotelName", h.get("name", f"{city}酒店")),
            "description": f"{city} 酒店推荐",
            "category": "hotel",
            "claim": f"{h.get('hotelName', '')} ¥{h.get('lowestPrice', '?')}起 评分{h.get('commentScore', '?')} {h.get('address', '')} {h.get('business', '')}",
            "source": "途牛酒店",
            "source_type": "api",
            "confidence": "high",
            "detail": h,
        }
        for h in hotels[:5]
    ]


def search_poi_by_name(scenic_name: str) -> Optional[list[dict]]:
    """按景点名称搜索 POI 信息（门票价格）。"""
    return query_ticket_price(scenic_name)


def check_available() -> bool:
    """检查 tuniu CLI 是否可用。"""
    try:
        result = subprocess.run(
            [TUNIU_CMD, "--version"],
            capture_output=True, timeout=5, env=_build_env(),
        )
        return result.returncode == 0
    except Exception:
        return False
