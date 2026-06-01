"""
rag/reranker.py — Cross-Encoder Rerank 重排序器

使用 sentence-transformers 的 CrossEncoder 对检索结果进行精排。
Bi-Encoder（embedding）做初筛，Cross-Encoder 做精排。
"""

import logging
from typing import Any

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import RetrievalResult, RerankedResult

logger = logging.getLogger(__name__)


class Reranker:
    """Cross-Encoder 重排序器

    生命周期：
    - 模型惰性加载（首次调用时加载，避免启动耗时）
    - warm_up() 方法供服务启动时预加载
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ):
        self._model_name = model_name or settings.rerank_model_name
        self._device = device or settings.rerank_device
        self._model: Any = None

    def _get_model(self):
        """惰性加载 CrossEncoder 模型"""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info("加载 Rerank 模型: %s (device=%s)", self._model_name, self._device)
            self._model = CrossEncoder(
                self._model_name,
                device=self._device,
            )
        return self._model

    def warm_up(self):
        """预热模型（服务启动时调用）"""
        self._get_model()
        logger.info("Rerank 模型预热完成")

    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int | None = None,
    ) -> list[RerankedResult]:
        """
        对去重后的结果进行 Cross-Encoder 重排序。

        参数:
            query:   原始用户查询
            results: 去重后的 RetrievalResult 列表
            top_k:   返回的最终数量

        返回:
            按 rerank_score 降序排列的 RerankedResult 列表
        """
        if not results:
            return []

        top_k = top_k or settings.final_top_k
        model = self._get_model()

        # 构建 query-doc pairs
        pairs = [(query, r.chunk.text) for r in results]
        scores = model.predict(
            pairs,
            batch_size=settings.rerank_batch_size,
            show_progress_bar=False,
        )

        # 单条结果 → 标量
        if not hasattr(scores, "__iter__"):
            scores = [float(scores)]

        ranked: list[RerankedResult] = []
        for r, score in zip(results, scores):
            ranked.append(RerankedResult(
                chunk=r.chunk,
                original_score=r.score,
                original_strategy=r.strategy,
                rerank_score=float(score),
            ))

        ranked.sort(key=lambda x: x.rerank_score, reverse=True)
        return ranked[:top_k]
