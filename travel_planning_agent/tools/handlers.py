"""Concrete tool handlers for travel data sources."""

import logging

logger = logging.getLogger(__name__)


def handle_search_poi(destination: str, category: str, context: str = "") -> str:
    from travel_planning_agent.gaode_client import search_poi_text
    from travel_planning_agent.tools.poi_parser import CATEGORY_LABELS, summarize_poi_search

    label = CATEGORY_LABELS.get(category, category)
    keyword = _poi_keyword(destination, label, context)
    result = search_poi_text(keywords=keyword, city=destination, city_limit=True)
    if result:
        return summarize_poi_search(result, destination, category)
    return f"【POI】{destination}{label}: 暂未查到精确结果"


def _poi_keyword(destination: str, label: str, context: str = "") -> str:
    context = (context or "").strip()
    if context and len(context) <= 24 and not any(token in context for token in ("规划", "行程", "推荐", "搜索")):
        return context
    return f"{destination}{label}"


def handle_get_weather(city: str, date: str = "", days: int = 3) -> str:
    from travel_planning_agent.gaode_client import get_weather
    from travel_planning_agent.tools.weather_parser import summarize_weather

    result = get_weather(city)
    if result:
        return summarize_weather(result, city, date, limit=max(int(days or 1), 1))
    return f"【天气】{city}: 暂未查到天气预报"


def handle_query_ticket_price(scenic_name: str) -> str:
    from travel_planning_agent.tuniu_client import query_ticket_price

    result = query_ticket_price(scenic_name)
    if result:
        claim = result[0].get("claim", "")
        return f"【门票】{claim}" if claim else f"【门票】{scenic_name}: 有票价信息"
    return f"【门票】{scenic_name}: 暂未查到票价信息"


def handle_search_hotel(city: str, keyword: str = "", nearby: str = "") -> str:
    from travel_planning_agent.tuniu_client import search_hotel

    search_keyword = nearby or keyword
    results = search_hotel(city, search_keyword)
    if results:
        scope = f"{search_keyword}附近" if search_keyword else city
        lines = [f"【酒店】在 {scope} 找到以下酒店："]
        for r in results[:5]:
            lines.append(f"  - {r.get('claim', '')}")
        return "\n".join(lines)
    scope = f"{city} {search_keyword}附近" if search_keyword else city
    return f"【酒店】{scope}: 暂未查到酒店信息"


def handle_get_hotel_detail(hotel_id: str) -> str:
    from travel_planning_agent.tuniu_client import call_cli

    data = call_cli("hotel", "tuniu_hotel_detail", {"hotel_id": hotel_id})
    return str(data) if data else f"酒店 {hotel_id}: 暂未查到详细信息"


def handle_get_driving_eta(origin: str, destination: str) -> str:
    from travel_planning_agent.gaode_client import get_driving_eta
    from travel_planning_agent.tools.route_parser import summarize_route_duration

    result = get_driving_eta(origin, destination)
    return summarize_route_duration(result, "driving") if result else "驾车: 暂未查到路线用时"


def handle_get_walking_route(origin: str, destination: str) -> str:
    from travel_planning_agent.gaode_client import _call_tool
    from travel_planning_agent.tools.route_parser import summarize_route_duration

    result = _call_tool("maps_direction_walking", {"origin": origin, "destination": destination})
    return summarize_route_duration(result, "walking") if result else "步行: 暂未查到路线用时"


def handle_get_transit_route(origin: str, destination: str, city: str, cityd: str) -> str:
    from travel_planning_agent.gaode_client import get_transit_eta
    from travel_planning_agent.tools.route_parser import summarize_route_duration

    result = get_transit_eta(origin, destination, city, cityd)
    return summarize_route_duration(result, "transit") if result else "公交/地铁: 暂未查到路线用时"


def handle_geo_encode(address: str, city: str = "") -> str:
    from travel_planning_agent.gaode_client import geo_encode

    result = geo_encode(address, city)
    return str(result) if result else "暂未查到坐标信息"


def handle_search_around(location: str, keywords: str, radius: str = "") -> str:
    from travel_planning_agent.gaode_client import search_around

    result = search_around(location, keywords, radius)
    if result and isinstance(result, list):
        lines = ["在附近找到："]
        for poi in result[:8]:
            name = poi.get("name", "") or poi.get("_name", "")
            addr = poi.get("address", "") or poi.get("_address", "")
            lines.append(f"- {name}（{addr}）")
        return "\n".join(lines)
    return "附近暂未查到相关信息"


def handle_search_flight(from_city: str, to_city: str, date: str) -> str:
    try:
        from travel_planning_agent.flight_client import search_flight_mcp
        result = search_flight_mcp(from_city, to_city, date)
        if result:
            lines = ["【航班】找到以下航班："]
            for f in result[:5]:
                fno = f.get("flightNo") or f.get("flightNumber", "?")
                dept = f.get("departureTime") or f.get("departure_time", "?")
                arr = f.get("arrivalTime") or f.get("arrival_time", "?")
                dep_apt = f.get("departureName") or f.get("departureAirport") or f.get("depAirportName", "")
                arr_apt = f.get("arrivalName") or f.get("arrivalAirport") or f.get("arrAirportName", "")
                price = f.get("ticketPrice") or f.get("price") or f.get("basePrice", "?")
                airline = f.get("airlineName") or f.get("airline", "")
                transfer = f.get("transferNum") or 0
                tag = "(中转)" if isinstance(transfer, int) and transfer > 0 else ""
                lines.append(f"  - {fno} {dept}-{arr} {dep_apt}→{arr_apt} ¥{price} {airline}{tag}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("Flight MCP 查询失败，走途牛兜底: %s", e)

    from travel_planning_agent.tuniu_client import call_cli
    data = call_cli("flight", "searchLowestPriceFlight", {
        "departureCityName": from_city, "arrivalCityName": to_city, "departureDate": date,
    })
    flights = data.get("data", []) if data else []
    if flights:
        lines = ["【航班】找到以下航班："]
        for f in flights[:3]:
            lines.append(
                f"  - {f.get('flightNumber','?')} {f.get('departureTime','?')[:5]}-"
                f"{f.get('arrivalTime','?')[:5]} {f.get('departureAirport','')}→"
                f"{f.get('arrivalAirport','')} ¥{f.get('basePrice', '?')}"
            )
        return "\n".join(lines)
    return f"【航班】{from_city}→{to_city}: 查询失败"


def handle_search_train(from_station: str, to_station: str, date: str) -> str:
    try:
        from travel_planning_agent.train_client import search_train_mcp
        result = search_train_mcp(from_station, to_station, date)
        if result:
            lines = ["【火车】找到以下车次："]
            for t in result[:8]:
                num = t.get("trainno") or t.get("trainNum", "?")
                dept = t.get("departuretime") or t.get("departureTime", "?")
                arr = t.get("arrivaltime") or t.get("arrivalTime", "?")
                dep_st = t.get("departstation") or t.get("departStationName", from_station)
                arr_st = t.get("endstation") or t.get("destStationName", to_station)
                price = "?"
                for seat in ("ze", "zy", "edz", "ydz", "dz", "rz", "rw", "yw", "yz"):
                    seat_info = t.get(seat, {}) or {}
                    p = seat_info.get("price", "--") if isinstance(seat_info, dict) else "--"
                    if p and p != "--":
                        price = p
                        break
                lines.append(f"  - {num} {dept[:5]}-{arr[:5]} {dep_st}→{arr_st} ¥{price} {t.get('type', '')}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("Train MCP 查询失败，走途牛兜底: %s", e)

    from travel_planning_agent.tuniu_client import call_cli
    data = call_cli("train", "searchLowestPriceTrain", {
        "departureCityName": from_station, "arrivalCityName": to_station, "departureDate": date,
    })
    trains = data.get("data", []) if data else []
    if trains:
        lines = ["【火车】找到以下车次："]
        for t in trains[:3]:
            prices = t.get("price", {})
            lowest = "?"
            for k in ("gjrwPrice", "rwPrice", "rzPrice", "swzPrice", "tdzPrice", "dzPrice", "ydzPrice", "edzPrice"):
                if prices.get(k):
                    lowest = prices[k]
                    break
            lines.append(
                f"  - {t.get('trainNum','?')} {t.get('departureTime','?')[:5]}-"
                f"{t.get('arrivalTime','?')[:5]} {t.get('departStationName','')}→"
                f"{t.get('destStationName','')} ¥{lowest}"
            )
        return "\n".join(lines)
    return f"【火车】{from_station}→{to_station}: 查询失败"


def handle_get_current_date() -> str:
    from datetime import date
    return date.today().isoformat()


HANDLERS = {
    "get_current_date": handle_get_current_date,
    "search_poi": handle_search_poi,
    "get_weather_forecast": handle_get_weather,
    "query_ticket_price": handle_query_ticket_price,
    "search_hotel": handle_search_hotel,
    "get_hotel_detail": handle_get_hotel_detail,
    "search_flight": handle_search_flight,
    "search_train": handle_search_train,
    "get_driving_eta": handle_get_driving_eta,
    "get_walking_route": handle_get_walking_route,
    "get_transit_route": handle_get_transit_route,
    "geo_encode": handle_geo_encode,
    "search_around": handle_search_around,
}
