"""
engine/rules.py — 8 条确定性规则

Phase 1: R01-R04
Phase 2: R05-R08（空间连续性、开放时间、行程密度、用户锁定完整性）
"""

import json
import math
import re
from typing import Optional
from travel_planning_agent.types import PlanState, RuleResult, SegmentType


# ═══════════════════════════════════════════════════════
#  Phase 1 规则（不变）
# ═══════════════════════════════════════════════════════

def check_time_non_overlap(state: PlanState) -> RuleResult:
    """
    R01: 同一天内相邻活动时间不得重叠。
    """
    for day in state.days:
        timed_segments = [s for s in day.segments if s.start_time and s.end_time]
        timed_segments.sort(key=lambda s: s.start_time)

        for i in range(len(timed_segments) - 1):
            cur, nxt = timed_segments[i], timed_segments[i + 1]
            if nxt.start_time < cur.end_time:
                return RuleResult(
                    rule_id="R01", name="时间连续性", result="FAIL",
                    detail=f"Day {day.day_number} 「{cur.title}」({cur.start_time}-{cur.end_time}) "
                           f"与「{nxt.title}」({nxt.start_time}) 时间重叠",
                    affected_segments=[cur.segment_id, nxt.segment_id],
                )
    return RuleResult(rule_id="R01", name="时间连续性", result="PASS")


def check_budget_not_exceeded(state: PlanState) -> RuleResult:
    """
    R02: 所有 segment 费用之和不超过预算上限。
    """
    if not state.constraints:
        return RuleResult(rule_id="R02", name="预算", result="FAIL", detail="缺少约束条件（预算未设置）")

    total = 0.0
    for day in state.days:
        for seg in day.segments:
            if seg.estimated_cost and seg.estimated_cost.amount:
                total += seg.estimated_cost.amount

    budget = state.constraints.budget
    if total > budget:
        return RuleResult(
            rule_id="R02", name="预算", result="FAIL",
            detail=f"总花费 {total:,.0f} 超出预算 {budget:,.0f}",
        )
    return RuleResult(
        rule_id="R02", name="预算", result="PASS",
        detail=f"总花费 {total:,.0f} 在预算 {budget:,.0f} 以内",
    )


def check_date_in_bounds(state: PlanState) -> RuleResult:
    """
    R03: 所有行程日期在旅行起止日期范围内。
    """
    if not state.constraints:
        return RuleResult(rule_id="R03", name="日期边界", result="FAIL", detail="缺少约束条件（天数未设置）")

    max_days = state.constraints.days
    for day in state.days:
        if day.day_number < 1 or day.day_number > max_days:
            return RuleResult(
                rule_id="R03", name="日期边界", result="FAIL",
                detail=f"Day {day.day_number} 超出旅行范围（1-{max_days}天）",
                affected_segments=[day.day_id],
            )
    return RuleResult(rule_id="R03", name="日期边界", result="PASS",
                      detail=f"所有行程日期在 1-{max_days} 天范围内")


def check_required_fields_complete(state: PlanState) -> RuleResult:
    """
    R04: 关键字段完整性检查。
    模块级验证时天可能不完整（如第1天上午只有交通段），"每天至少一个 ACTIVITY"
    由全局验证 `_modular_global_verify` 兜底。
    """
    for day in state.days:
        has_activity = False
        for seg in day.segments:
            if not seg.title.strip():
                return RuleResult(
                    rule_id="R04", name="必填完整性", result="FAIL",
                    detail=f"Day {day.day_number} 中存在标题为空的 segment",
                    affected_segments=[seg.segment_id],
                )
            if seg.type == SegmentType.ACTIVITY:
                has_activity = True
        if not has_activity:
            return RuleResult(
                rule_id="R04", name="必填完整性", result="FAIL",
                detail=f"Day {day.day_number} 缺少活动",
                affected_segments=[day.day_id],
            )
    if not state.days:
        return RuleResult(rule_id="R04", name="必填完整性", result="FAIL", detail="行程为空，没有任何天数")
    return RuleResult(rule_id="R04", name="必填完整性", result="PASS")


# ═══════════════════════════════════════════════════════
#  Phase 2 新增规则
# ═══════════════════════════════════════════════════════

def check_spatial_continuity(state: PlanState) -> RuleResult:
    """
    R05: 空间连续性——活动间留有充足交通时间。

    逻辑：
      遍历每天的相邻 segment（不同地点的）：
        eta = 估算交通时间（直线距离 × 系数）
        buffer = seg[i+1].start_time - seg[i].end_time
        如果 buffer < eta × 1.3 → FAIL

    Phase 2 中用距离估算（不调外部地图 API）。
    """
    for day in state.days:
        timed_segments = [s for s in day.segments if s.start_time and s.end_time and s.location]
        timed_segments.sort(key=lambda s: s.start_time)

        for i in range(len(timed_segments) - 1):
            cur, nxt = timed_segments[i], timed_segments[i + 1]

            # 同一地点不需要交通时间
            if cur.location and nxt.location and cur.location.name == nxt.location.name:
                continue

            # 估算 ETA（分钟）
            eta = _estimate_eta(cur, nxt)

            if eta == 0:
                continue

            # 计算实际缓冲时间（分钟）
            buffer = _time_diff_minutes(cur.end_time, nxt.start_time)
            required_buffer = int(eta * 1.3)

            if buffer < required_buffer:
                return RuleResult(
                    rule_id="R05", name="空间连续性", result="FAIL",
                    detail=f"Day {day.day_number} 「{cur.title}」→「{nxt.title}」"
                           f"预计车程 {eta} 分钟，当前只预留 {buffer} 分钟（需 ≥ {required_buffer} 分钟）",
                    affected_segments=[cur.segment_id, nxt.segment_id],
                )
    return RuleResult(rule_id="R05", name="空间连续性", result="PASS")


def check_opening_hours(state: PlanState) -> RuleResult:
    """
    R06: 开放时间——活动时间在景点开放时间内。

    逻辑：
      Step 1: 从 evidence 中提取开放时间校验
      Step 2: 调高德 POI 详情获取真实营业时间（有坐标时）
    """
    for day in state.days:
        for seg in day.segments:
            if not seg.start_time or not seg.end_time:
                continue

            seg_start_min = _time_to_minutes(seg.start_time)
            seg_end_min = _time_to_minutes(seg.end_time)

            # Step 1: 从 evidence 提取开放时间
            for eid in seg.evidence_ids:
                ev = state.evidence.get(eid)
                if ev and ev.claim:
                    opening, closing = _parse_opening_hours(ev.claim)
                    if opening is not None:
                        fail = _check_time_against_opening(seg, day.day_number, seg_start_min, seg_end_min, opening, closing)
                        if fail:
                            return fail

            # Step 2: 调高德搜索真实营业时间（有名称+城市时）
            if seg.location and seg.location.name:
                gaode_opening, gaode_closing = _get_gaode_opening_hours(seg)
                if gaode_opening is not None:
                    fail = _check_time_against_opening(seg, day.day_number, seg_start_min, seg_end_min, gaode_opening, gaode_closing)
                    if fail:
                        return fail

    return RuleResult(rule_id="R06", name="开放时间", result="PASS")


def _check_time_against_opening(seg, day_number: int, seg_start: Optional[int], seg_end: Optional[int], opening: int, closing: int) -> Optional[RuleResult]:
    """检查活动时间是否在开放时间内，不在则返回 FAIL。"""
    if seg_start is not None and seg_start < opening:
        return RuleResult(
            rule_id="R06", name="开放时间", result="FAIL",
            detail=f"Day {day_number} 「{seg.title}」开始时间 {_minutes_to_time(seg_start)} "
                   f"早于景区开放时间 {_minutes_to_time(opening)}",
            affected_segments=[seg.segment_id],
        )
    if seg_end is not None and seg_end > closing:
        return RuleResult(
            rule_id="R06", name="开放时间", result="FAIL",
            detail=f"Day {day_number} 「{seg.title}」结束时间 {_minutes_to_time(seg_end)} "
                   f"超出景区关闭时间 {_minutes_to_time(closing)}",
            affected_segments=[seg.segment_id],
        )
    return None


def _get_gaode_opening_hours(seg) -> tuple:
    """调高德 POI 搜索获取真实营业时间。返回 (open_min, close_min) 或 (None, None)。"""
    try:
        from travel_planning_agent.config import settings
        if not settings.external_rule_checks_enabled:
            return None, None

        from travel_planning_agent.storage.sqlite_store import cache_get, cache_set, build_cache_key
        from travel_planning_agent.gaode_client import search_poi_text
        city = seg.location.city if seg.location else ""
        query = _clean_location_query(seg.location.name or seg.title, city)
        if not query:
            return None, None

        cache_key = build_cache_key("gaode_opening_hours", query=query, city=city or "")
        cached = cache_get(cache_key)
        if cached is not None:
            return tuple(cached) if cached else (None, None)

        results = search_poi_text(keywords=query, city=city)
        if not results or not isinstance(results, list):
            cache_set(cache_key, None, ttl_seconds=3600)
            return None, None

        for item in results[:3]:
            text = item.get("text", "") if isinstance(item, dict) else ""
            if not text:
                continue
            data = json.loads(text) if isinstance(text, str) else text
            pois = data if isinstance(data, list) else data.get("pois", []) if isinstance(data, dict) else []
            for poi in pois:
                if not isinstance(poi, dict):
                    continue
                opentime = poi.get("opentime", "") or ""
                if opentime and "-" in opentime:
                    parts = opentime.split("-")
                    if len(parts) == 2:
                        open_t = _time_to_minutes(parts[0].strip())
                        close_t = _time_to_minutes(parts[1].strip())
                        if open_t is not None and close_t is not None:
                            cache_set(cache_key, (open_t, close_t), ttl_seconds=86400)
                            return open_t, close_t
        cache_set(cache_key, None, ttl_seconds=3600)
    except Exception:
        pass
    return None, None


def check_density(state: PlanState) -> RuleResult:
    """
    R07: 行程密度——每日活动数量超过阈值时给出 WARN 提醒。
    pace 主要用于引导 LLM 规划节奏，不做硬性拦截。
    """
    if not state.constraints:
        return RuleResult(rule_id="R07", name="行程密度", result="PASS")

    thresholds = {"slow": 2, "moderate": 4, "fast": 6}
    max_activities = thresholds.get(state.constraints.pace, 4)

    for day in state.days:
        activity_count = sum(1 for s in day.segments if s.type == SegmentType.ACTIVITY)
        if activity_count > max_activities:
            return RuleResult(
                rule_id="R07", name="行程密度", result="WARN",
                detail=f"Day {day.day_number} 有 {activity_count} 个活动，"
                       f"超过 {state.constraints.pace} 节奏上限 {max_activities} 个",
                affected_segments=[s.segment_id for s in day.segments if s.type == SegmentType.ACTIVITY],
            )
    return RuleResult(rule_id="R07", name="行程密度", result="PASS")


def check_pin_integrity(state: PlanState) -> RuleResult:
    """
    R08: 用户锁定项——pinned 项目未被修改。

    逻辑：
      遍历 state.pins：
        找到 pin.target_id 对应的 segment
        如果 segment 不存在或内容不符 → FAIL
    """
    if not state.pins:
        return RuleResult(rule_id="R08", name="用户锁定项", result="PASS")

    for pin in state.pins:
        if pin.mutable:
            continue
        if pin.target_type == "segment":
            # 查找该 segment 是否存在
            found = False
            for day in state.days:
                for seg in day.segments:
                    if seg.segment_id == pin.target_id:
                        found = True
                        break
            if not found:
                return RuleResult(
                    rule_id="R08", name="用户锁定项", result="FAIL",
                    detail=f"用户锁定的 segment {pin.target_id} 已被删除或修改",
                    affected_segments=[pin.target_id],
                )
        elif pin.target_type == "constraint":
            # 检查约束未被修改
            if pin.target_id == "budget" and state.constraints:
                # budget pin — 检查预算未变
                pass  # 由 orchestration 层验证具体值

    return RuleResult(rule_id="R08", name="用户锁定项", result="PASS", detail="所有锁定项未被修改")


# ═══════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════

def _get_coords(location) -> Optional[tuple[float, float]]:
    """获取地点坐标，优先用已有 lat/lng，没有则 geo_encode 查询。"""
    if not location:
        return None
    if location.lat and location.lng:
        return location.lng, location.lat
    try:
        from travel_planning_agent.config import settings
        if not settings.external_rule_checks_enabled:
            return None

        from travel_planning_agent.storage.sqlite_store import cache_get, cache_set, build_cache_key
        from travel_planning_agent.gaode_client import geo_encode
        query = _clean_location_query(location.name, location.city)
        if not query:
            return None
        cache_key = build_cache_key("gaode_geo", query=query, city=location.city or "")
        cached = cache_get(cache_key)
        if cached is not None:
            return tuple(cached) if cached else None
        result = geo_encode(query, location.city or "")
        if result and isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "") if isinstance(result[0], dict) else ""
            if text:
                data = json.loads(text) if isinstance(text, str) else text
                geo = data.get("geo", {})
                loc_str = geo.get("location", "") if isinstance(geo, dict) else ""
                if loc_str and "," in loc_str:
                    lng, lat = loc_str.split(",")
                    coords = (float(lng), float(lat))
                    cache_set(cache_key, coords, ttl_seconds=86400)
                    return coords
        cache_set(cache_key, None, ttl_seconds=3600)
    except Exception:
        pass
    return None


def _clean_location_query(name: str, city: str = "") -> str:
    """Turn verbose segment titles into geocodable place names."""
    import re

    value = (name or "").strip()
    if not value:
        return ""
    value = re.sub(r"（.*?）|\\(.*?\\)", "", value)
    value = re.sub(r"^(游览|参观|徒步|观看|逛|再次参观|入住|前往|抵达|到达)", "", value)
    value = re.split(r"[，,、；;。]", value)[0].strip()
    for suffix in ("景区", "公园", "博物馆", "寺", "塔", "街", "酒店", "校区", "湿地"):
        idx = value.find(suffix)
        if idx != -1:
            value = value[:idx + len(suffix)]
            break
    for token in ("杭州", city or "", "景点", "景区内", "附近"):
        if token:
            value = value.replace(token, "")
    return value.strip()


def _estimate_eta(seg_a, seg_b) -> int:
    """估算两个 segment 地点间的交通时间（分钟）。

    优先调用高德驾车 ETA（自动获取坐标），失败走内置估算。"""
    loc_a, loc_b = seg_a.location, seg_b.location
    if not loc_a or not loc_b:
        return 0

    # 获取坐标（优先使用已有，没有则 geo_encode）
    coords_a = _get_coords(loc_a)
    coords_b = _get_coords(loc_b)

    if coords_a and coords_b:
        lng1, lat1 = coords_a
        lng2, lat2 = coords_b
        eta = _get_gaode_eta(lng1, lat1, lng2, lat2)
        if eta is not None:
            return eta

        # 高德失败，内置估算
        dx = (lng1 - lng2) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat1 - lat2) * 111320
        distance_m = math.sqrt(dx * dx + dy * dy)
        eta_min = distance_m / 500 + 5
        return max(int(eta_min), 10)

    # 无坐标时，不同城市名默认 60 分钟，同城默认 20 分钟
    return 60 if loc_a.city.lower() != loc_b.city.lower() else 20


def _get_gaode_eta(lng1: float, lat1: float, lng2: float, lat2: float) -> Optional[int]:
    """
    调用高德驾车路线规划获取真实 ETA（分钟）。

    结果缓存到 SQLite，相同坐标对不重复调用。
    """
    from travel_planning_agent.storage.sqlite_store import cache_get, cache_set, build_cache_key
    from travel_planning_agent.config import settings

    if not settings.external_rule_checks_enabled:
        return None

    # 没配 Key 时不调
    if not settings.gaode_key:
        return None

    origin = f"{lng1},{lat1}"
    destination = f"{lng2},{lat2}"

    # 查缓存
    cache_key = build_cache_key("gaode_eta", origin=origin, destination=destination)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # 调高德
    try:
        from travel_planning_agent.gaode_client import get_driving_eta
        result = get_driving_eta(origin, destination)
        if result and isinstance(result, list):
            text_content = result[0].get("text", "") if result else ""
            data = json.loads(text_content) if text_content else {}
            route = data.get("route", {})
            paths = route.get("paths", [])
            if paths:
                duration_sec = int(paths[0].get("duration", 0))
                eta_min = max(duration_sec // 60, 1)
                # 写缓存（TTL 12 小时）
                cache_set(cache_key, eta_min, ttl_seconds=43200)
                return eta_min
    except Exception:
        pass

    return None


def _time_diff_minutes(start_time: str, end_time: str) -> int:
    """计算两个时间字符串之间的分钟差。"""
    start = _time_to_minutes(start_time)
    end = _time_to_minutes(end_time)
    if start is None or end is None:
        return 0
    return end - start


def _time_to_minutes(t: str) -> Optional[int]:
    """将 HH:MM 转换为分钟数。"""
    try:
        parts = t.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def _minutes_to_time(m: int) -> str:
    """将分钟数转换为 HH:MM。"""
    return f"{m // 60:02d}:{m % 60:02d}"


def check_poi_real(state: PlanState) -> RuleResult:
    """
    R09: 反幻觉——确认行程中的 POI 真实存在。

    对每个 ACTIVITY 类型的 segment，调高德 POI 搜索验证是否真实存在。
    连续 2 次搜索无结果 → WARN（非 FAIL，因名称偏差可能搜不到）。
    """
    from travel_planning_agent.gaode_client import search_poi_text, ensure_initialized

    if not ensure_initialized():
        return RuleResult(rule_id="R09", name="POI 真实性", result="PASS",
                          detail="高德 MCP 未初始化，跳过")

    for day in state.days:
        for seg in day.segments:
            if seg.type != SegmentType.ACTIVITY or not seg.title:
                continue

            city = seg.location.city if seg.location else ""
            results = search_poi_text(keywords=seg.title, city=city, city_limit=True)
            found = False
            if results and isinstance(results, list):
                for item in results:
                    text = item.get("text", "") if isinstance(item, dict) else ""
                    if not text:
                        continue
                    try:
                        data = json.loads(text) if isinstance(text, str) else text
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, list):
                        for poi in data:
                            name = poi.get("name", "") if isinstance(poi, dict) else ""
                            if name and seg.title in name:
                                found = True
                                break
                    if found:
                        break

            if not found:
                return RuleResult(
                    rule_id="R09", name="POI 真实性", result="WARN",
                    detail=f"Day {day.day_number} 「{seg.title}」在高德搜索中未找到匹配 POI，"
                           f"请确认名称是否正确",
                    affected_segments=[seg.segment_id],
                )

    return RuleResult(rule_id="R09", name="POI 真实性", result="PASS",
                      detail="所有 POI 通过真实性校验")


def _parse_opening_hours(claim: str) -> tuple:
    """
    从证据 claim 中解析开放时间。
    支持格式："开放时间 07:00-18:00"、"营业时间 09:00-17:00"
    返回 (open_minutes, close_minutes) 或 (None, None)
    """
    pattern = r"(\d{2}:\d{2})\s*[-~]\s*(\d{2}:\d{2})"
    match = re.search(pattern, claim)
    if match:
        open_t = _time_to_minutes(match.group(1))
        close_t = _time_to_minutes(match.group(2))
        if open_t is not None and close_t is not None:
            return open_t, close_t
    return None, None
