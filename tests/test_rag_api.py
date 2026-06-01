from types import SimpleNamespace

import pytest

from travel_planning_agent.rag import create_rag_pipeline
from travel_planning_agent.rag.chunker import DocumentChunker
from travel_planning_agent.rag.hybrid_retriever import HybridRetriever
from travel_planning_agent.rag.models import QueryDimension, RerankedResult
from travel_planning_agent.rag.query_expander import QueryExpander


class FakeEmbeddingService:
    def __init__(self):
        self.texts = []

    def embed_batch(self, texts):
        self.texts.extend(texts)
        return [[float(len(text)), 1.0] for text in texts]

    def embed_single(self, text):
        self.texts.append(text)
        return [float(len(text)), 1.0]


class FakeESManager:
    def __init__(self):
        self.docs = []
        self.hybrid_calls = []
        self.ensure_index_called = False

    def ensure_index(self, index_name=None):
        self.ensure_index_called = True

    def bulk_index(self, chunks, index_name=None):
        self.docs.extend(chunks)
        return len(chunks)

    def hybrid_search(self, query_text, query_vector, k=10, filters=None, **kwargs):
        self.hybrid_calls.append(
            {
                "query_text": query_text,
                "query_vector": query_vector,
                "k": k,
                "filters": filters,
                "kwargs": kwargs,
            }
        )
        return [
            {
                "chunk_id": doc["chunk_id"],
                "doc_id": doc["doc_id"],
                "text": doc["text"],
                "chunk_index": doc["chunk_index"],
                "source_title": doc["source_title"],
                "source_url": doc["source_url"],
                "category": doc["category"],
                "metadata": doc["metadata"],
                "_score": 1.0 / (index + 1),
            }
            for index, doc in enumerate(self.docs[:k])
        ]


class RecordingReranker:
    def __init__(self):
        self.queries = []

    def rerank(self, query, results, top_k=None):
        self.queries.append(query)
        ranked = [
            RerankedResult(
                chunk=result.chunk,
                original_score=result.score,
                original_strategy=result.strategy,
                rerank_score=100.0 - index,
            )
            for index, result in enumerate(results)
        ]
        return ranked[:top_k]


def test_create_rag_pipeline_indexes_documents_and_queries_for_planning():
    emb = FakeEmbeddingService()
    es = FakeESManager()
    reranker = RecordingReranker()

    pipeline = create_rag_pipeline(
        embedding_service=emb,
        es_manager=es,
        reranker=reranker,
        chunker=DocumentChunker(chunk_size=200, chunk_overlap=0),
    )

    indexed = pipeline.indexer.index_documents(
        [
            {
                "doc_id": "doc_a",
                "text": "杭州西湖适合散步，傍晚人流较多。",
                "source_title": "杭州攻略",
                "category": "guide",
            },
            {
                "doc_id": "doc_b",
                "text": "灵隐寺建议早到，周末排队时间较长。",
                "source_title": "杭州避坑",
                "category": "guide",
            },
        ]
    )

    response = pipeline.query_for_planning("杭州", top_k=2)

    assert indexed == 2
    assert es.ensure_index_called is True
    assert response.destination == "杭州"
    assert "杭州 必去景点 游玩时长 开放时间" in response.queries_used
    assert response.total_candidates == 8
    assert response.total_after_dedup == 2
    assert [result.chunk.doc_id for result in response.results] == ["doc_a", "doc_b"]


def test_hybrid_retriever_passes_configured_rrf_weights(monkeypatch):
    emb = FakeEmbeddingService()
    es = FakeESManager()
    es.docs.append(
        {
            "chunk_id": "doc_chunk_0000",
            "doc_id": "doc",
            "text": "杭州旅游攻略",
            "chunk_index": 0,
            "source_title": "doc.md",
            "source_url": "",
            "category": "guide",
            "metadata": {},
        }
    )
    monkeypatch.setattr("travel_planning_agent.rag.hybrid_retriever.settings.bm25_weight", 2.5)
    monkeypatch.setattr("travel_planning_agent.rag.hybrid_retriever.settings.knn_weight", 0.7)
    monkeypatch.setattr("travel_planning_agent.rag.hybrid_retriever.settings.rrf_rank_constant", 42)

    retriever = HybridRetriever(es, emb)
    retriever.retrieve_multi(
        [QueryDimension(dimension="guide", query_text="杭州旅游攻略")],
        k=1,
        max_workers=1,
    )

    assert es.hybrid_calls[0]["kwargs"] == {
        "bm25_weight": 2.5,
        "knn_weight": 0.7,
        "rrf_rank_constant": 42,
    }


def test_query_expander_uses_four_planning_focused_default_queries():
    queries = QueryExpander().expand("杭州")

    assert [q.query_text for q in queries] == [
        "杭州 必去景点 游玩时长 开放时间",
        "杭州 景点路线 顺路安排 一日游",
        "杭州 特色美食 推荐餐厅 商圈",
        "杭州 避坑 排队 预约 门票 交通",
    ]


def test_query_expander_adds_at_most_one_personalized_query_with_exclusion_first():
    constraints = SimpleNamespace(
        interests=["亲子", "自然"],
        preferences_detail="不去西湖，避开排队",
    )

    queries = QueryExpander().expand("杭州", constraints)

    assert [q.query_text for q in queries] == [
        "杭州 必去景点 游玩时长 开放时间",
        "杭州 景点路线 顺路安排 一日游",
        "杭州 特色美食 推荐餐厅 商圈",
        "杭州 避坑 排队 预约 门票 交通",
        "杭州 西湖 替代景点 小众路线",
    ]


def test_query_expander_uses_core_interest_when_no_exclusion_exists():
    constraints = SimpleNamespace(
        interests=["亲子", "自然"],
        preferences_detail="",
    )

    queries = QueryExpander().expand("杭州", constraints)

    assert [q.query_text for q in queries] == [
        "杭州 必去景点 游玩时长 开放时间",
        "杭州 景点路线 顺路安排 一日游",
        "杭州 特色美食 推荐餐厅 商圈",
        "杭州 避坑 排队 预约 门票 交通",
        "杭州 亲子 景点 推荐 游玩时长",
    ]


def test_query_for_planning_uses_constraints_in_rerank_query():
    emb = FakeEmbeddingService()
    es = FakeESManager()
    reranker = RecordingReranker()
    pipeline = create_rag_pipeline(
        embedding_service=emb,
        es_manager=es,
        reranker=reranker,
        chunker=DocumentChunker(chunk_size=200, chunk_overlap=0),
    )
    pipeline.indexer.index_text("亲子游建议控制步行距离。", doc_id="doc")
    constraints = SimpleNamespace(
        days=3,
        interests=["亲子", "自然"],
        preferences_detail="不去西湖，避开排队",
        pace="slow",
        travelers=[SimpleNamespace(age_group="child"), SimpleNamespace(age_group="adult")],
    )

    pipeline.query_for_planning("杭州", constraints=constraints, top_k=1)

    rerank_query = reranker.queries[-1]
    assert "杭州" in rerank_query
    assert "3天" in rerank_query
    assert "亲子" in rerank_query
    assert "不去西湖" in rerank_query


def test_chunker_keeps_chunks_within_size_and_rejects_invalid_overlap():
    chunks = DocumentChunker(chunk_size=10, chunk_overlap=2).split_text(
        "abcdefghij.klmnopqrst.uvwxyz",
        doc_id="doc",
    )

    assert chunks
    assert all(len(chunk.text) <= 10 for chunk in chunks)
    with pytest.raises(ValueError, match="chunk_overlap"):
        DocumentChunker(chunk_size=5, chunk_overlap=5)
