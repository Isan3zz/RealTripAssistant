"""
rag/query_expander.py — 多维度查询扩展引擎

纯模板驱动，根据目的地和约束生成多条检索查询。
"""

import re
import logging

from travel_planning_agent.rag.models import QueryDimension

logger = logging.getLogger(__name__)


class QueryExpander:
    """多维度查询扩展器（纯模板，不需要 LLM）"""

    def expand(self, destination: str, constraints=None) -> list[QueryDimension]:
        """生成扩展查询列表

        参数:
            destination: 目的地，如 "杭州"
            constraints:  Constraints 对象或 None

        返回:
            QueryDimension 列表（基础4条 + 最多1条个性化查询）
        """
        queries: list[QueryDimension] = []

        # 1. 基础查询（始终4条）
        queries.extend(self._base_queries(destination))

        # 2. 个性化查询：排除项替代 > 核心兴趣
        if constraints is not None:
            personalized = self._personalized_query(destination, constraints)
            if personalized is not None:
                queries.append(personalized)

        # 3. 去重（相同 query_text 只保留优先级最高的）
        seen: set[str] = set()
        deduped: list[QueryDimension] = []
        for q in queries:
            key = q.query_text
            if key not in seen:
                seen.add(key)
                deduped.append(q)
            else:
                # 保留高优先级
                for i, existing in enumerate(deduped):
                    if existing.query_text == key and q.priority > existing.priority:
                        deduped[i] = q
                        break

        logger.info("查询扩展: %d 条 → 去重后 %d 条", len(queries), len(deduped))
        return deduped

    # ── 基础查询 ──────────────────────────────────

    @staticmethod
    def _base_queries(destination: str) -> list[QueryDimension]:
        d = destination.strip()
        return [
            QueryDimension(dimension="must_visit", query_text=f"{d} 必去景点 游玩时长 开放时间", priority=8),
            QueryDimension(dimension="route", query_text=f"{d} 景点路线 顺路安排 一日游", priority=7),
            QueryDimension(dimension="food", query_text=f"{d} 特色美食 推荐餐厅 商圈", priority=6),
            QueryDimension(dimension="pitfalls", query_text=f"{d} 避坑 排队 预约 门票 交通", priority=7),
        ]

    # ── 偏好查询 ──────────────────────────────────

    def _personalized_query(self, destination: str, constraints) -> QueryDimension | None:
        """生成最多一条个性化查询。"""
        exclusion = self._first_exclusion_item(constraints)
        d = destination.strip()
        if exclusion:
            return QueryDimension(
                dimension="exclusion",
                query_text=f"{d} {exclusion} 替代景点 小众路线",
                priority=9,
            )

        interest = self._first_interest_item(constraints)
        if interest:
            return QueryDimension(
                dimension="interest",
                query_text=f"{d} {interest} 景点 推荐 游玩时长",
                priority=8,
            )
        return None

    @staticmethod
    def _first_interest_item(constraints) -> str:
        """从 constraints.interests 取第一个有效核心兴趣。"""
        interests = getattr(constraints, "interests", None)
        if not interests:
            return ""

        for interest in interests:
            item = interest.strip()
            if item and len(item) >= 2:
                return item
        return ""

    @staticmethod
    def _first_exclusion_item(constraints) -> str:
        """从 constraints.preferences_detail 提取第一个排除项。

        匹配模式: 不去X / 避开X / 不喜欢X / 不想去X / 讨厌X
        只提取 X 中长度 >= 2 的名词
        """
        pref = getattr(constraints, "preferences_detail", "")
        if not pref:
            return []

        # 提取排除项
        patterns = [
            r"不去\s*(.+?)(?:[，。,\.\s、]|$)",
            r"避开\s*(.+?)(?:[，。,\.\s、]|$)",
            r"不喜欢\s*(.+?)(?:[，。,\.\s、]|$)",
            r"不想去\s*(.+?)(?:[，。,\.\s、]|$)",
            r"讨厌\s*(.+?)(?:[，。,\.\s、]|$)",
        ]
        matches: list[tuple[int, str]] = []
        for p in patterns:
            for match in re.finditer(p, pref):
                item = match.group(1).strip()
                # 过滤过短或过长、纯标点
                if len(item) >= 2 and len(item) < 20 and not item.startswith("的"):
                    matches.append((match.start(), item))

        if not matches:
            return ""
        matches.sort(key=lambda x: x[0])
        return matches[0][1]
