"""OpenAI-compatible tool schemas."""

from typing import Any


BASE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "获取当天日期，返回 YYYY-MM-DD 格式。当用户说相对日期时调用此工具确定年份",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_poi",
            "description": "搜索目的地的景点/餐厅/活动等 POI 信息，返回名称和地址",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "description": "目的地城市"},
                    "category": {"type": "string", "enum": ["cultural", "natural", "food", "shopping", "accommodation"]},
                    "context": {"type": "string", "description": "搜索背景"},
                },
                "required": ["destination", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_ticket_price",
            "description": "【途牛】查询景点门票类型和价格",
            "parameters": {
                "type": "object",
                "properties": {"scenic_name": {"type": "string", "description": "景点名称，如'灵隐寺'"}},
                "required": ["scenic_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotel",
            "description": "【途牛】搜索目的地酒店，优先按核心景点/商圈附近筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"},
                    "keyword": {"type": "string", "description": "搜索关键词（优先传核心景点/商圈/区域名）"},
                    "nearby": {"type": "string", "description": "希望住宿靠近的景点、商圈或活动区域，如'西湖'、'灵隐寺'"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hotel_detail",
            "description": "【途牛】查看指定酒店的详细信息",
            "parameters": {
                "type": "object",
                "properties": {"hotel_id": {"type": "string", "description": "酒店 ID"}},
                "required": ["hotel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_flight",
            "description": "【途牛】搜索国内航班，支持低价/时段/价格区间查询",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_city": {"type": "string", "description": "出发城市"},
                    "to_city": {"type": "string", "description": "到达城市"},
                    "date": {"type": "string", "description": "出发日期 YYYY-MM-DD"},
                },
                "required": ["from_city", "to_city", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_train",
            "description": "【途牛】查询火车车次列表，到达站请用目的地主城区站名",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_station": {"type": "string", "description": "出发站"},
                    "to_station": {"type": "string", "description": "到达站"},
                    "date": {"type": "string", "description": "出发日期 YYYY-MM-DD"},
                },
                "required": ["from_station", "to_station", "date"],
            },
        },
    },
]


LOCAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "获取目的地天气预报",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD"},
                    "days": {"type": "integer", "description": "从 date 开始需要覆盖的天数"},
                },
                "required": ["city", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_driving_eta",
            "description": "查询两地之间驾车路线和预计时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "起点，地点名或经纬度"},
                    "destination": {"type": "string", "description": "终点，地点名或经纬度"},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_walking_route",
            "description": "查询两地之间步行路线",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "起点，地点名或经纬度"},
                    "destination": {"type": "string", "description": "终点，地点名或经纬度"},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transit_route",
            "description": "查询两地之间公交/地铁路线",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "起点"},
                    "destination": {"type": "string", "description": "终点"},
                    "city": {"type": "string", "description": "起点城市"},
                    "cityd": {"type": "string", "description": "终点城市"},
                },
                "required": ["origin", "destination", "city", "cityd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geo_encode",
            "description": "地址转经纬度坐标",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "地址或地点名"},
                    "city": {"type": "string", "description": "城市"},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_around",
            "description": "搜索坐标或地点周边 POI",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "中心点"},
                    "keywords": {"type": "string", "description": "关键词"},
                    "radius": {"type": "string", "description": "半径，单位米"},
                },
                "required": ["location", "keywords"],
            },
        },
    },
]


def get_all_tool_schemas() -> list[dict[str, Any]]:
    schemas = [*BASE_TOOL_SCHEMAS]
    try:
        from travel_planning_agent.gaode_client import get_openai_tools
        for schema in get_openai_tools() or []:
            name = schema.get("function", {}).get("name", "")
            if name and not any(s.get("function", {}).get("name") == name for s in schemas):
                schemas.append(schema)
    except Exception:
        pass

    for schema in LOCAL_TOOL_SCHEMAS:
        name = schema.get("function", {}).get("name", "")
        if name and not any(s.get("function", {}).get("name") == name for s in schemas):
            schemas.append(schema)
    return schemas
