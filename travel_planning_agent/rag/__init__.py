"""
rag/__init__.py — RAG 模块包入口

提供一站式工厂函数 create_rag_pipeline()。

使用示例:
    from travel_planning_agent.rag import create_rag_pipeline

    pipeline = create_rag_pipeline()

    # 索引文档
    pipeline.indexer.index_from_directory("docs/", glob_pattern="*.md")

    # 单条查询
    r = pipeline.query("杭州西湖有什么好玩的？")

    # 旅行规划检索
    from travel_planning_agent.types import Constraints
    r = pipeline.query_for_planning("杭州", constraints)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_rag_pipeline(
    openai_client=None,
    es_host: str | None = None,
    es_username: str | None = None,
    es_password: str | None = None,
    embedding_service: Any = None,
    es_manager: Any = None,
    chunker: Any = None,
    retriever: Any = None,
    deduplicator: Any = None,
    reranker: Any = None,
):
    """工厂函数：创建完整的 RAG 流水线

    参数:
        openai_client: openai.OpenAI 实例（可选），用于 embedding 调用。
                       为 None 时 EmbeddingService 将自行创建。
        es_host:       ES 地址
        es_username:   ES 用户名
        es_password:   ES 密码
        embedding_service/es_manager/chunker/retriever/deduplicator/reranker:
                       可选依赖注入，主要用于测试或替换默认实现。

    返回:
        RAGPipeline 实例，其上挂载了 .indexer
    """
    from travel_planning_agent.rag.embedding import EmbeddingService
    from travel_planning_agent.rag.es_client import ESClientManager
    from travel_planning_agent.rag.chunker import DocumentChunker
    from travel_planning_agent.rag.indexer import DocumentIndexer
    from travel_planning_agent.rag.hybrid_retriever import HybridRetriever
    from travel_planning_agent.rag.deduplicator import JaccardDeduplicator
    from travel_planning_agent.rag.reranker import Reranker
    from travel_planning_agent.rag.pipeline import RAGPipeline

    es = es_manager or ESClientManager(host=es_host, username=es_username, password=es_password)
    emb = embedding_service or EmbeddingService(client=openai_client)
    retriever = retriever or HybridRetriever(es, emb)
    dedup = deduplicator or JaccardDeduplicator()
    reranker = reranker or Reranker()

    chunker = chunker or DocumentChunker()
    indexer = DocumentIndexer(chunker, emb, es)

    pipeline = RAGPipeline(retriever, dedup, reranker)
    pipeline.indexer = indexer  # 挂载 indexer 方便外部使用
    return pipeline
