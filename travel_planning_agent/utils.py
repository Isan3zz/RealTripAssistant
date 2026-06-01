"""
utils.py — 通用工具函数（非 CLI 特定）

从 cli.py 中提取的可复用函数，供 API 层和测试使用。
"""

import hashlib
import re
from travel_planning_agent.types import Traveler


def parse_travelers(text: str) -> list[Traveler]:
    """
    解析人员描述文本。

    示例输入：
      "4人，其中2位老人" → [adult, adult, elderly, elderly]
      "2位成人" → [adult, adult]
      "2大1小" → [adult, adult, child]

    参数：
      text: 人员描述字符串

    返回：
      Traveler 列表
    """
    travelers: list[Traveler] = []
    text_clean = text.replace("，", ",").replace(" ", "")

    # 解析老人数量
    elderly_match = re.search(r"(\d+)\s*位\s*老人", text_clean)
    elderly_count = int(elderly_match.group(1)) if elderly_match else 0

    # 解析小孩数量
    child_match = (
        re.search(r"(\d+)\s*位\s*小孩", text_clean)
        or re.search(r"(\d+)\s*位\s*儿童", text_clean)
        or re.search(r"(\d+)\s*位\s*孩子", text_clean)
    )
    child_count = int(child_match.group(1)) if child_match else 0

    # 解析总人数
    total_match = re.search(r"(\d+)\s*人", text_clean)
    total_count = int(total_match.group(1)) if total_match else 0

    # 计算成人数量
    adult_count = max(0, total_count - elderly_count - child_count)

    # 如果总人数为0但有"2位成人"模式
    if total_count == 0:
        adult_match = re.search(r"(\d+)\s*位\s*成人", text_clean) or re.search(r"(\d+)\s*个\s*成人", text_clean)
        if adult_match:
            adult_count = int(adult_match.group(1))

    # 如果还是解析不出来，默认2位成人
    if total_count == 0 and adult_count == 0:
        adult_count = 2

    for _ in range(adult_count):
        travelers.append(Traveler(age_group="adult"))
    for _ in range(elderly_count):
        travelers.append(Traveler(age_group="elderly"))
    for _ in range(child_count):
        travelers.append(Traveler(age_group="child"))

    return travelers


def make_segment_id(trip_id: str, title: str, start_time: str, end_time: str, day_number: int) -> str:
    """
    基于内容生成确定性段 ID。

    相同的内容（标题+时间+天数）在同一次旅行中生成相同的 ID，
    跨运行也相同，使得 diff、pin、locked 跨运行有效。
    """
    raw = f"{trip_id}|{title}|{start_time}|{end_time}|{day_number}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"s_{h}"
