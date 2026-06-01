from typing import Optional


PROFILE_META = {
    "relaxed": {
        "label": "轻松慢游",
        "best_for": "不想赶路、希望每天留出休息时间的自由行用户",
        "tradeoffs": ["景点覆盖较少", "体验更从容"],
    },
    "classic": {
        "label": "经典初游",
        "best_for": "第一次到目的地、希望覆盖代表性景点的用户",
        "tradeoffs": ["热门点较多", "步行和换乘可能偏多"],
    },
    "food": {
        "label": "美食深度",
        "best_for": "把吃当地特色放在高优先级的用户",
        "tradeoffs": ["景点密度降低", "餐饮预算占比更高"],
    },
    "economy": {
        "label": "省钱优先",
        "best_for": "希望控制总预算、接受更朴素安排的用户",
        "tradeoffs": ["舒适度略低", "部分体验会被替换为低成本选项"],
    },
}


def build_decision_card(profile_id: str, plan: dict) -> dict:
    meta = PROFILE_META.get(profile_id, PROFILE_META["classic"])
    days = plan.get("days") or []
    segments = [seg for day in days for seg in day.get("segments", [])]
    total_cost = sum(_segment_cost(seg) for seg in segments)
    activity_count = sum(1 for seg in segments if seg.get("type") == "activity")
    daily_activity = activity_count / len(days) if days else 0
    pace_level = "轻松" if daily_activity <= 2 else "适中" if daily_activity <= 4 else "紧凑"
    return {
        "profile_id": profile_id,
        "label": meta["label"],
        "best_for": meta["best_for"],
        "tradeoffs": list(meta["tradeoffs"]),
        "total_cost": total_cost,
        "activity_count": activity_count,
        "day_count": len(days),
        "pace_level": pace_level,
    }


def build_explanation_cards(plan: dict) -> list[dict]:
    cards = []
    profile = (plan or {}).get("profile") or "classic"
    for day in plan.get("days") or []:
        segments = list(day.get("segments", []) or [])
        activity_count = sum(1 for item in segments if item.get("type") == "activity")
        for index, seg in enumerate(segments):
            prev_seg = segments[index - 1] if index > 0 else None
            next_seg = segments[index + 1] if index + 1 < len(segments) else None
            cards.append({
                "segment_id": seg.get("segment_id") or seg.get("title", ""),
                "day_number": day.get("day_number"),
                "title": seg.get("title", ""),
                "type": seg.get("type", ""),
                "sections": {
                    "为什么推荐": _why_recommended(day, seg),
                    "为什么这样安排": _why_scheduled(day, seg, prev_seg, next_seg),
                    "注意事项": _attention_notes(day, seg, prev_seg, next_seg, profile, activity_count),
                },
            })
    return cards


def build_execution_checklist(trip: dict, plan: dict) -> list[dict]:
    items = []
    total_cost = 0.0
    for day in plan.get("days") or []:
        for seg in day.get("segments", []) or []:
            total_cost += _segment_cost(seg)
            if seg.get("type") == "transport":
                items.append(_checklist_item("交通", day, f"确认交通安排：{seg.get('title', '')}"))
            if seg.get("type") == "accommodation":
                items.append(_checklist_item("住宿", day, f"确认入住信息：{seg.get('title', '')}"))
            if "reservation" in (seg.get("tags") or []):
                items.append(_checklist_item("预约", day, f"提前预约或购票：{seg.get('title', '')}"))
    items.append({
        "category": "预算",
        "day_number": None,
        "title": f"预计花费 {total_cost:,.0f} 元，出发前确认是否符合预算",
        "priority": "medium",
        "done": False,
    })
    items.append({
        "category": "天气",
        "day_number": None,
        "title": f"出发前查看 {trip.get('destination', '')} 天气并准备雨具或防晒",
        "priority": "medium",
        "done": False,
    })
    return items


def _segment_cost(segment: dict) -> float:
    cost = segment.get("estimated_cost")
    if isinstance(cost, dict):
        return float(cost.get("amount") or 0)
    if isinstance(cost, (int, float)):
        return float(cost)
    return 0.0


def _checklist_item(category: str, day: dict, title: str) -> dict:
    return {
        "category": category,
        "day_number": day.get("day_number"),
        "title": title,
        "priority": "high" if category in {"交通", "住宿", "预约"} else "medium",
        "done": False,
    }


def _why_recommended(day: dict, seg: dict) -> str:
    seg_type = seg.get("type")
    title = seg.get("title", "")
    if seg_type == "activity":
        if _is_rainy(day) and _is_outdoor(seg):
            return _activity_reason(seg, rainy=True)
        if _is_rainy(day) and _is_indoor(seg):
            return "这类室内文化点不太受天气影响，雨天放进当天会更稳。"
        if _is_indoor(seg):
            return "这段节奏比较稳，可以在路上或天气不确定时保住当天体验。"
        if _is_outdoor(seg):
            return _activity_reason(seg)
    if seg.get("note"):
        return str(seg["note"])
    if seg_type == "activity":
        return _activity_reason(seg)
    if seg_type == "meal":
        return _meal_reason(seg)
    if seg_type == "transport":
        return _transport_reason(seg)
    if seg_type == "accommodation":
        if any(token in title for token in ("西湖", "景区", "地铁", "商圈", "市中心")):
            return "这晚住在出行方便的位置，晚上收得住，第二天出行也不用重新折返。"
        return "这段主要是把当天行程收住，保证休息和第二天出行便利。"
    return "这段是为了让当天节奏更完整，不必单独作为重点。"


def _why_scheduled(day: dict, seg: dict, prev_seg: Optional[dict] = None, next_seg: Optional[dict] = None) -> str:
    timing_issue = _timing_issue(seg, prev_seg, next_seg)
    if timing_issue:
        return timing_issue
    time_text = "-".join(x for x in [seg.get("start_time"), seg.get("end_time")] if x)
    if time_text:
        return f"安排在 {time_text}，用于承接当天前后项目。"
    return f"安排在 Day {day.get('day_number')}，与当天主题相匹配。"


def _attention_notes(
    day: dict,
    seg: dict,
    prev_seg: Optional[dict] = None,
    next_seg: Optional[dict] = None,
    profile: str = "classic",
    activity_count: int = 0,
) -> str:
    notes = []
    timing_issue = _timing_issue(seg, prev_seg, next_seg)
    if timing_issue:
        notes.append(timing_issue)

    if _is_rainy(day) and _is_outdoor(seg):
        notes.append("如果降雨或雨势变大，可以缩短停留，保留最想看的部分，或直接改去附近室内备选。")
    elif _is_rainy(day) and _is_indoor(seg):
        notes.append("雨天人流可能集中到室内，建议提前确认预约和排队情况。")

    meal_note = _meal_attention(seg)
    if meal_note:
        notes.append(meal_note)

    if _is_relaxed_profile(profile) and activity_count > 2 and seg.get("type") == "activity":
        notes.append(f"当前 Day {day.get('day_number')} 有 {activity_count} 个游玩点，和慢游节奏相比偏紧，可删减或延长休息。")

    if notes:
        return " ".join(notes)

    tags = seg.get("tags") or []
    if "rain" in tags or "indoor" in tags:
        return "适合作为天气不稳定时的备选，不用把当天节奏排得太满。"
    if seg.get("type") == "activity":
        return "出发前看一眼开放时间和预约要求，现场人多就减少停留。"
    if seg.get("type") == "transport":
        return _transport_attention(seg)
    if seg.get("type") == "meal":
        return "餐厅不用卡得太死，排队久就换附近同类型选择。"
    if seg.get("type") == "accommodation":
        return "到店前确认入住时间；如果当天玩得晚，优先保证休息。"
    return "根据当天体力微调就好，不需要硬卡分钟。"


def _activity_reason(seg: dict, rainy: bool = False) -> str:
    title = seg.get("title", "")
    if "表演" in title or "演出" in title or "千古情" in title:
        if rainy:
            return "这段的核心看点是演出，雨天也可以保留表演，把外围夜游当作可加可减的部分。"
        return "这段有明确看点，适合放在晚上作为当天的记忆点。"
    if "湖" in title or "公园" in title:
        if rainy:
            return "这里的景观价值不错，但有降雨时更适合轻量停留，天气好就多走一段。"
        return "这段适合放慢脚步看城市风景，是当天比较值得留时间的体验。"
    if "博物馆" in title or "艺术馆" in title or "美术馆" in title:
        return "这类点能补上目的地的历史和文化背景，节奏也比户外奔走更稳。"
    return "这是当天的主要体验点，适合作为行程里的核心安排。"


def _transport_reason(seg: dict) -> str:
    title = seg.get("title", "")
    if any(token in title for token in ("返回", "回", "酒店", "入住")):
        return "这段主要是把夜游结束后顺路带回酒店，时间不用卡得太死。"
    if any(token in title for token in ("高铁", "动车", "火车", "航班", "飞机", "G")):
        return "这是进出城的关键段，按票面时间执行，其他安排围着它留余地。"
    if any(token in title for token in ("地铁", "公交", "打车", "步行")):
        return "这段只是连接两个地点，尽量选省心路线，别让换乘消耗太多体力。"
    return "这段用于把前后地点接起来，保持当天动线顺。"


def _meal_reason(seg: dict) -> str:
    start = _time_to_minutes(seg.get("start_time"))
    title = seg.get("title", "")
    if start is not None and start < 9 * 60:
        return "这是出发前的补能安排，避免早班交通或上午游玩时空腹赶路。"
    if start is not None and start < 16 * 60:
        return "这段餐饮用于承接上午活动，顺便补充体力再进入下午行程。"
    if "晚餐" in title or (start is not None and start >= 17 * 60):
        return "安排在当天主要活动后，用来恢复体力，也方便根据实际游玩时间微调。"
    return "这段餐饮用于补充体力，避免连续游玩时间过长。"


def _meal_attention(seg: dict) -> str:
    if seg.get("type") != "meal":
        return ""
    start = _time_to_minutes(seg.get("start_time"))
    title = seg.get("title", "")
    if start is None:
        return ""
    if 14 * 60 <= start < 16 * 60:
        return "午餐偏晚，建议上午备水和小食，或把午餐提前。"
    if ("晚餐" in title or start >= 16 * 60) and start < 17 * 60:
        return "这个时间更像下午加餐，如果作为晚餐可能偏早。"
    if start < 7 * 60:
        return "早餐时间较早，建议提前确认酒店或车站附近是否营业。"
    return ""


def _transport_attention(seg: dict) -> str:
    title = seg.get("title", "")
    if any(token in title for token in ("G", "高铁", "动车", "火车", "航班", "飞机")):
        return "提前确认车次、检票口和到站交通；这类时间最好别临时压缩。"
    if any(token in title for token in ("地铁", "公交", "路")):
        return "出发前看实时班次和换乘站点，晚间回酒店可以按现场情况改打车。"
    if "步行" in title:
        return "步行段看天气和路况，行李多或下雨时直接改打车。"
    return "出发前确认路线，现场交通不顺就换更省心的方式。"


def _timing_issue(seg: dict, prev_seg: Optional[dict], next_seg: Optional[dict]) -> str:
    start = _time_to_minutes(seg.get("start_time"))
    end = _time_to_minutes(seg.get("end_time"))

    if prev_seg and start is not None:
        prev_end = _time_to_minutes(prev_seg.get("end_time"))
        if prev_end is not None:
            gap = start - prev_end
            if gap < 0:
                return (
                    f"上一段预计 {prev_seg.get('end_time')} 结束，本段 {seg.get('start_time')} 开始，"
                    "衔接不足且时间重叠，需要顺延或删减。"
                )

    if next_seg and end is not None:
        next_start = _time_to_minutes(next_seg.get("start_time"))
        if next_start is not None:
            gap = next_start - end
            if gap < 0:
                return (
                    f"本段预计 {seg.get('end_time')} 结束，但下一段 {next_seg.get('start_time')} 开始，"
                    "时间重叠，需要调整顺序或压缩停留。"
                )

    return ""


def _is_rainy(day: dict) -> bool:
    note = day.get("day_note") or ""
    return any(token in note for token in ("雨", "暴雨", "中雨", "小雨", "雷阵雨", "阵雨"))


def _is_indoor(seg: dict) -> bool:
    tags = seg.get("tags") or []
    text = f"{seg.get('title', '')} {' '.join(str(tag) for tag in tags)}"
    return any(token in text for token in ("室内", "博物馆", "展览", "美术馆", "艺术馆", "商场", "indoor", "museum"))


def _is_outdoor(seg: dict) -> bool:
    tags = seg.get("tags") or []
    text = f"{seg.get('title', '')} {' '.join(str(tag) for tag in tags)}"
    if _is_indoor(seg):
        return False
    return any(token in text for token in ("湖", "山", "公园", "景区", "夜游", "步行街", "广场", "户外", "outdoor", "natural"))


def _is_relaxed_profile(profile: str) -> bool:
    return profile in {"relaxed", "slow"}


def _time_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value or ":" not in value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None
