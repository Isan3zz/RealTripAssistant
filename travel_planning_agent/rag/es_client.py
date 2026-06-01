"""
rag/es_client.py — ElasticSearch 客户端封装

管理 ES 连接生命周期，提供索引创建、kNN 检索、批量索引能力。
"""

import logging
from typing import Any

from travel_planning_agent.config import settings

logger = logging.getLogger(__name__)

# ES 索引 Mapping 模板
_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "chunk_id":       {"type": "keyword"},
            "doc_id":         {"type": "keyword"},
            "text":           {"type": "text", "analyzer": "ik_max_word"},
            "embedding":      {"type": "dense_vector", "dims": 1536, "index": True, "similarity": "cosine"},
            "chunk_index":    {"type": "integer"},
            "source_title":   {"type": "text", "analyzer": "ik_smart", "fields": {"raw": {"type": "keyword"}}},
            "source_url":     {"type": "keyword"},
            "category":       {"type": "keyword"},
            "created_at":     {"type": "date"},
            "metadata":       {"type": "object", "enabled": False},
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
        },
    },
}


class ESClientManager:
    """ES 客户端生命周期管理器（惰性连接 + 单例模式）"""

    def __init__(
        self,
        host: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self._host = host or settings.es_host
        self._username = username or settings.es_username
        self._password = password or settings.es_password
        self._client: Any = None

    def _get_client(self):
        """惰性初始化 ES 客户端"""
        if self._client is None:
            from elasticsearch import Elasticsearch
            if self._username:
                self._client = Elasticsearch(
                    self._host,
                    basic_auth=(self._username, self._password),
                )
            else:
                self._client = Elasticsearch(self._host)
            if not self._client.ping():
                raise ConnectionError(f"ES 连接失败: {self._host}")
            logger.info("ES 连接成功: %s", self._host)
        return self._client

    def ensure_index(self, index_name: str | None = None):
        """确保索引存在，不存在则创建"""
        name = index_name or settings.es_index_name
        client = self._get_client()
        if not client.indices.exists(index=name):
            client.indices.create(index=name, body=_INDEX_MAPPING)
            logger.info("ES 索引已创建: %s", name)
        else:
            logger.info("ES 索引已存在: %s", name)

    def delete_index(self, index_name: str | None = None):
        """删除索引（谨慎使用）"""
        name = index_name or settings.es_index_name
        client = self._get_client()
        if client.indices.exists(index=name):
            client.indices.delete(index=name)
            logger.info("ES 索引已删除: %s", name)

    # ES _source 字段列表（检索时不返回 embedding 向量，减小时延）
    _SOURCE_FIELDS = [
        "chunk_id", "doc_id", "text", "chunk_index",
        "source_title", "source_url", "category", "metadata",
    ]

    def knn_search(
        self,
        query_vector: list[float],
        k: int = 10,
        filters: dict | None = None,
        index_name: str | None = None,
        num_candidates: int | None = None,
    ) -> list[dict]:
        """kNN 向量检索（纯语义匹配）"""
        name = index_name or settings.es_index_name
        client = self._get_client()
        nc = num_candidates or (k * 10)

        knn_query: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": k,
            "num_candidates": nc,
        }
        if filters:
            knn_query["filter"] = filters

        body: dict[str, Any] = {
            "knn": knn_query,
            "_source": self._SOURCE_FIELDS,
            "size": k,
        }

        resp = client.search(index=name, body=body)
        return self._parse_hits(resp)

    def bm25_search(
        self,
        query_text: str,
        k: int = 10,
        filters: dict | None = None,
        index_name: str | None = None,
        text_fields: list[str] | None = None,
    ) -> list[dict]:
        """BM25 全文检索（关键词匹配）"""
        name = index_name or settings.es_index_name
        client = self._get_client()
        fields = text_fields or ["text", "source_title"]

        must_clauses: list[dict] = [
            {"multi_match": {"query": query_text, "fields": fields}},
        ]
        filter_clauses: list[dict] = []
        if filters:
            filter_clauses.extend(filters if isinstance(filters, list) else [filters])

        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filter_clauses if filter_clauses else None,
                },
            },
            "_source": self._SOURCE_FIELDS,
            "size": k,
        }
        # 移除空的 filter
        if not filter_clauses:
            del body["query"]["bool"]["filter"]

        resp = client.search(index=name, body=body)
        return self._parse_hits(resp)

    def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 10,
        filters: dict | None = None,
        index_name: str | None = None,
        bm25_weight: float = 1.0,
        knn_weight: float = 1.0,
        rrf_rank_constant: int = 60,
    ) -> list[dict]:
        """BM25 + kNN 混合检索，RRF (Reciprocal Rank Fusion) 融合

        分别执行 BM25 全文检索和 kNN 向量检索（各取 k*2 条），
        再用 RRF 对两个结果列表做加权融合，返回 top-k。

        参数:
            query_text:       BM25 全文检索的查询文本
            query_vector:     kNN 向量检索的向量
            k:                最终返回数量
            bm25_weight:      BM25 结果的 RRF 权重（默认 1.0）
            knn_weight:       kNN 结果的 RRF 权重（默认 1.0）
            rrf_rank_constant: RRF 平滑常数（默认 60）
        """
        fetch_k = k * 2  # 每路多取一些，给 RRF 融合留空间

        # 并行不成立（ES 客户端同步调用），但两个查询独立可分别执行
        bm25_hits = self.bm25_search(query_text, k=fetch_k, filters=filters, index_name=index_name)
        knn_hits = self.knn_search(query_vector, k=fetch_k, filters=filters, index_name=index_name)

        # RRF 融合
        merged = self._rrf_merge(
            bm25_hits, knn_hits,
            bm25_weight=bm25_weight,
            knn_weight=knn_weight,
            rank_constant=rrf_rank_constant,
        )
        return merged[:k]

    # ── 内部方法 ────────────────────────────────────

    @staticmethod
    def _parse_hits(resp: dict) -> list[dict]:
        """解析 ES search 响应为统一格式"""
        results: list[dict] = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            src["_score"] = hit["_score"]
            src["_rank"] = hit.get("_rank", 0)
            results.append(src)
        return results

    @staticmethod
    def _rrf_merge(
        list_a: list[dict],
        list_b: list[dict],
        bm25_weight: float = 1.0,
        knn_weight: float = 1.0,
        rank_constant: int = 60,
    ) -> list[dict]:
        """RRF 融合两个排序列表

        公式: score(d) = Σ w_i / (rank_constant + rank_i(d))

        对相同 chunk_id 的结果（同时在 BM25 和 kNN 中出现），累加两个来源的 RRF 分数。
        """
        # Step 1: 给每个文档按在各自列表中的位置打分
        chunk_scores: dict[str, float] = {}
        chunk_data: dict[str, dict] = {}

        for rank, hit in enumerate(list_a):
            cid = hit["chunk_id"]
            rrf = bm25_weight / (rank_constant + rank + 1)
            chunk_scores[cid] = rrf
            chunk_data[cid] = hit

        for rank, hit in enumerate(list_b):
            cid = hit["chunk_id"]
            rrf = knn_weight / (rank_constant + rank + 1)
            if cid in chunk_scores:
                chunk_scores[cid] += rrf  # 双路命中，累加分数
                # 保留原始分数更高的那个
                if hit["_score"] > chunk_data[cid]["_score"]:
                    chunk_data[cid] = hit
            else:
                chunk_scores[cid] = rrf
                chunk_data[cid] = hit

        # Step 2: 按 RRF 分数降序排列
        sorted_ids = sorted(chunk_scores, key=lambda cid: chunk_scores[cid], reverse=True)
        results: list[dict] = []
        for cid in sorted_ids:
            hit = chunk_data[cid]
            hit["_score"] = chunk_scores[cid]  # 用 RRF 分数替换原始分数
            results.append(hit)

        return results

    def bulk_index(
        self,
        chunks: list[dict],
        index_name: str | None = None,
    ) -> int:
        """批量索引文档块，返回成功索引数量"""
        if not chunks:
            return 0

        name = index_name or settings.es_index_name
        client = self._get_client()

        from elasticsearch.helpers import bulk

        actions = [
            {
                "_index": name,
                "_id": c["chunk_id"],
                "_source": c,
            }
            for c in chunks
        ]

        success, errors = bulk(client, actions, raise_on_error=False)
        if errors:
            logger.warning("ES 批量索引部分失败: %d/%d", len(errors), len(chunks))
        logger.info("ES 批量索引完成: %d/%d 条", success, len(chunks))
        return success
