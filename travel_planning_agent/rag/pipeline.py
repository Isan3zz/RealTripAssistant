"""
rag/pipeline.py — RAG 完整查询流水线

编排：查询扩展 → 并行检索 → 去重 → Rerank → 返回结果
"""

import logging

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import (
    QueryDimension,
    RAGResponse,
    RAGPlanResponse,
)
from travel_planning_agent.rag.hybrid_retriever import HybridRetriever
from travel_planning_agent.rag.deduplicator import JaccardDeduplicator
from travel_planning_agent.rag.reranker import Reranker

logger = logging.getLogger(__name__)


class RAGPipeline:
    """RAG 查询流水线

    使用示例:
        pipeline = create_rag_pipeline(openai_client)
        # 单条查询
        r = pipeline.query("杭州西湖有什么好玩的？")
        # 旅行规划检索
        r = pipeline.query_for_planning("杭州", constraints)
    """

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        deduplicator: JaccardDeduplicator,
        reranker: Reranker,
    ):
        self._retriever = hybrid_retriever
        self._deduplicator = deduplicator
        self._reranker = reranker
        self.indexer = None  # 由 create_rag_pipeline 挂载

    # ── 单条查询（简单入口） ───────────────────────

    def query(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict | None = None,
    ) -> RAGResponse:
        """单条查询入口"""
        top_k = top_k or settings.final_top_k

        q = QueryDimension(dimension="direct", query_text=query, priority=5)
        results = self._retriever.retrieve_multi([q], filters=filters)

        deduped = self._deduplicator.deduplicate(results)
        ranked = self._reranker.rerank(query, deduped, top_k=top_k)

        return RAGResponse(
            query=query,
            results=ranked,
            total_candidates=len(results),
            total_after_dedup=len(deduped),
        )

    # ── 旅行规划检索（核心入口） ───────────────────

    def query_for_planning(
        self,
        destination: str,
        constraints=None,
        top_k: int | None = None,
    ) -> RAGPlanResponse:
        """旅行规划前多维度检索

        参数:
            destination:  目的地，如 "杭州"
            constraints:  Constraints 对象（可选）
            top_k:        最终返回数量

        返回:
            RAGPlanResponse 含维度覆盖信息和 rerank 结果
        """
        from travel_planning_agent.rag.query_expander import QueryExpander

        top_k = top_k or settings.final_top_k

        # Step 1: 查询扩展
        expander = QueryExpander()
        queries = expander.expand(destination, constraints)
        logger.info("查询扩展: %d 条", len(queries))

        # Step 2: N 路并行检索
        results = self._retriever.retrieve_multi(queries)
        logger.info("并行检索: %d 条候选", len(results))

        # Step 3: 去重
        deduped = self._deduplicator.deduplicate(results)
        logger.info("去重: %d -> %d", len(results), len(deduped))

        # Step 4: Rerank（用维度覆盖最广的 query 文本）
        rerank_query = _build_planning_rerank_query(destination, constraints)
        ranked = self._reranker.rerank(rerank_query, deduped, top_k=top_k)
        logger.info("Rerank: top-%d", len(ranked))

        return RAGPlanResponse(
            destination=destination,
            queries_used=[q.query_text for q in queries],
            dimensions_covered=[q.dimension for q in queries],
            results=ranked,
            total_candidates=len(results),
            total_after_dedup=len(deduped),
        )


def _build_planning_rerank_query(destination: str, constraints=None) -> str:
    """构造贴近本次旅行意图的 rerank query。"""
    parts = [f"为{destination}旅行规划筛选可靠参考信息"]
    if constraints is None:
        return "，".join(parts)

    days = getattr(constraints, "days", None)
    if days:
        parts.append(f"{days}天")

    interests = getattr(constraints, "interests", None)
    if interests:
        parts.append("偏好：" + "、".join(str(item) for item in interests if item))

    pace = getattr(constraints, "pace", None)
    if pace:
        parts.append(f"节奏：{pace}")

    travelers = getattr(constraints, "travelers", None)
    if travelers:
        groups = [
            str(getattr(traveler, "age_group", ""))
            for traveler in travelers
            if getattr(traveler, "age_group", "")
        ]
        if groups:
            parts.append("出行人群：" + "、".join(groups))

    preferences = getattr(constraints, "preferences_detail", None)
    if preferences:
        parts.append(f"限制：{preferences}")

    return "，".join(parts)
