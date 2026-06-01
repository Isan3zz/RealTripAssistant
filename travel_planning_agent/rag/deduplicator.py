"""
rag/deduplicator.py — 检索结果去重器

双重去重策略：
1. chunk_id 精确去重（同一 chunk 被多路检索到）
2. Jaccard 字符 bigram 相似度去重（内容高度重叠的 chunk）
"""

import logging

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class JaccardDeduplicator:
    """基于 Jaccard 相似度的文本块去重器

    算法:
    1. 按 score 降序排列（优先保留高分结果）
    2. 每个候选与已保留结果对比 Jaccard 相似度
    3. 若 Jaccard >= threshold，视为重复；若当前文本更长，替换已保留的
    4. 贪心去重，时间复杂度 O(n*m)，n=候选数，m=保留数
    """

    def __init__(self, threshold: float | None = None):
        self._threshold = threshold or settings.dedup_threshold

    def deduplicate(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """
        双重去重: chunk_id 精确去重 + Jaccard 相似度去重
        """
        if len(results) <= 1:
            return results

        # Step 1: chunk_id 精确去重（保留 score 最高的）
        seen_ids: set[str] = set()
        id_deduped: list[RetrievalResult] = []
        for r in results:
            if r.chunk.chunk_id not in seen_ids:
                seen_ids.add(r.chunk.chunk_id)
                id_deduped.append(r)
            else:
                # 替换为更高分的同 chunk_id 结果
                for i, kept in enumerate(id_deduped):
                    if kept.chunk.chunk_id == r.chunk.chunk_id and r.score > kept.score:
                        id_deduped[i] = r
                        break

        logger.info("chunk_id 去重: %d -> %d", len(results), len(id_deduped))

        # Step 2: Jaccard 相似度去重
        sorted_results = sorted(id_deduped, key=lambda r: r.score, reverse=True)
        kept: list[RetrievalResult] = []
        kept_sets: list[tuple[set[str], int]] = []  # (bigram_set, text_len)

        for r in sorted_results:
            cur_set = self._to_bigram_set(r.chunk.text)
            is_dup = False

            for ks, kept_len in kept_sets:
                jaccard = self._jaccard(cur_set, ks)
                if jaccard >= self._threshold:
                    # 内容高度重叠 → 重复
                    if len(r.chunk.text) > kept_len:
                        # 当前文本更长，替换保留项
                        kept_sets.remove((ks, kept_len))
                        kept = [
                            x for x in kept
                            if self._to_bigram_set(x.chunk.text) != ks
                        ]
                        kept.append(r)
                        kept_sets.append((cur_set, len(r.chunk.text)))
                    is_dup = True
                    break

            if not is_dup:
                kept.append(r)
                kept_sets.append((cur_set, len(r.chunk.text)))

        logger.info("Jaccard 去重: %d -> %d", len(id_deduped), len(kept))
        return kept

    @staticmethod
    def _to_bigram_set(text: str) -> set[str]:
        """将文本转为字符 bigram 集合"""
        clean = text.replace(" ", "").replace("\n", "")
        if len(clean) < 2:
            return {clean}
        return {clean[i:i + 2] for i in range(len(clean) - 1)}

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        """计算 Jaccard 相似度"""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)
