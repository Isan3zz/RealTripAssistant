"""
rag/hybrid_retriever.py — N 路并行混合检索编排器

使用 ThreadPoolExecutor 对多条查询并行执行 BM25+kNN 混合检索。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import QueryDimension, RetrievalResult, TextChunk
from travel_planning_agent.rag.embedding import EmbeddingService
from travel_planning_agent.rag.es_client import ESClientManager

logger = logging.getLogger(__name__)


class HybridRetriever:
    """N 路并行混合检索

    接收多条 QueryDimension，并行执行 BM25+kNN 检索，
    返回合并后的 RetrievalResult 列表。
    """

    def __init__(self, es_manager: ESClientManager, embedding_service: EmbeddingService):
        self._es = es_manager
        self._emb = embedding_service

    def retrieve_multi(
        self,
        queries: list[QueryDimension],
        k: int | None = None,
        filters: dict | None = None,
        max_workers: int | None = None,
    ) -> list[RetrievalResult]:
        """对多条查询并行执行混合检索

        参数:
            queries:     扩展后的 QueryDimension 列表
            k:           每条查询返回的 top-K
            filters:     ES 过滤条件
            max_workers: 最大并行线程数

        返回:
            合并后的 RetrievalResult 列表（已标记 dimension）
        """
        if not queries:
            return []

        k = k or settings.top_k_per_query
        max_workers = max_workers or settings.rag_retrieval_max_workers
        max_workers = min(max_workers, len(queries))

        all_results: list[RetrievalResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict = {}

            for q in queries:
                future = executor.submit(
                    self._search_one, q, k, filters,
                )
                futures[future] = q

            for future in as_completed(futures):
                q = futures[future]
                try:
                    results = future.result()
                except Exception as e:
                    logger.error("检索失败 [%s] \"%s\": %s", q.dimension, q.query_text[:40], e)
                    continue

                all_results.extend(results)
                logger.info("维度 %s \"%s\": %d 条", q.dimension, q.query_text[:30], len(results))

        return all_results

    def _search_one(
        self, q: QueryDimension, k: int, filters: dict | None,
    ) -> list[RetrievalResult]:
        """单条查询的完整流程: embedding → hybrid_search → RetrievalResult"""
        vec = self._emb.embed_single(q.query_text)
        hits = self._es.hybrid_search(
            query_text=q.query_text,
            query_vector=vec,
            k=k,
            filters=filters,
            bm25_weight=settings.bm25_weight,
            knn_weight=settings.knn_weight,
            rrf_rank_constant=settings.rrf_rank_constant,
        )
        return self._to_results(hits, q.dimension)

    @staticmethod
    def _to_results(es_hits: list[dict], strategy: str) -> list[RetrievalResult]:
        """ES hits → RetrievalResult 列表"""
        results: list[RetrievalResult] = []
        for hit in es_hits:
            chunk = TextChunk(
                chunk_id=hit.get("chunk_id", ""),
                doc_id=hit.get("doc_id", ""),
                text=hit.get("text", ""),
                chunk_index=hit.get("chunk_index", 0),
                source_title=hit.get("source_title", ""),
                source_url=hit.get("source_url", ""),
                category=hit.get("category", ""),
                metadata=hit.get("metadata", {}),
            )
            results.append(RetrievalResult(
                chunk=chunk,
                score=hit.get("_score", 0.0),
                strategy=strategy,
            ))
        return results
