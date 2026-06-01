"""
rag/indexer.py — 文档索引流水线

编排完整的文档索引流程：读取 → 分块 → embedding → 写入 ES
"""

import logging
import pathlib
from typing import Any

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import TextChunk
from travel_planning_agent.rag.chunker import DocumentChunker
from travel_planning_agent.rag.embedding import EmbeddingService
from travel_planning_agent.rag.es_client import ESClientManager

logger = logging.getLogger(__name__)


class DocumentIndexer:
    """文档索引流水线：分块 → embedding → 写入 ES"""

    def __init__(
        self,
        chunker: DocumentChunker,
        embedding_service: EmbeddingService,
        es_manager: ESClientManager,
    ):
        self._chunker = chunker
        self._emb = embedding_service
        self._es = es_manager

    def index_text(
        self,
        text: str,
        doc_id: str | None = None,
        source_title: str = "",
        source_url: str = "",
        category: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """索引单篇文档，返回 chunk 数量"""
        chunks = self._chunker.split_text(
            text=text,
            doc_id=doc_id,
            source_title=source_title,
            source_url=source_url,
            category=category,
            metadata=metadata,
        )
        if not chunks:
            return 0
        return self._index_chunks(chunks)

    def index_documents(self, documents: list[dict]) -> int:
        """批量索引文档

        documents: [{"text":"...", "doc_id":"...", "source_title":"...", ...}, ...]
        """
        all_chunks = self._chunker.split_documents(documents)
        if not all_chunks:
            return 0
        return self._index_chunks(all_chunks)

    def index_from_file(
        self,
        file_path: str,
        doc_id: str | None = None,
        category: str = "",
    ) -> int:
        """从文件读取并索引"""
        fp = pathlib.Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        text = fp.read_text(encoding="utf-8")
        doc_id = doc_id or fp.stem

        # 自动推断 category
        if not category:
            category = _infer_category(file_path)

        return self.index_text(
            text=text,
            doc_id=doc_id,
            source_title=fp.name,
            source_url="",
            category=category,
        )

    def index_from_directory(
        self,
        directory: str,
        glob_pattern: str = "*.md",
        category: str = "",
    ) -> int:
        """从目录批量索引"""
        import glob
        pattern = f"{directory}/**/{glob_pattern}"
        files = glob.glob(pattern, recursive=True)

        total = 0
        for fp in files:
            try:
                n = self.index_from_file(fp, category=category)
                total += n
                logger.info("已索引: %s (%d chunks)", fp, n)
            except Exception as e:
                logger.error("索引失败 %s: %s", fp, e)

        return total

    def _index_chunks(self, chunks: list[TextChunk]) -> int:
        """分块 → embedding → 写入 ES"""
        # Step 1: 批量 embedding
        texts = [c.text for c in chunks]
        embeddings = self._emb.embed_batch(texts)

        # Step 2: 拼装 ES 文档
        es_docs: list[dict] = []
        for chunk, vec in zip(chunks, embeddings):
            es_docs.append({
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "text": chunk.text,
                "embedding": vec,
                "chunk_index": chunk.chunk_index,
                "source_title": chunk.source_title,
                "source_url": chunk.source_url,
                "category": chunk.category,
                "metadata": chunk.metadata,
            })

        # Step 3: 写入 ES
        self._es.ensure_index()
        return self._es.bulk_index(es_docs)


def _infer_category(file_path: str) -> str:
    """根据路径推断文档分类"""
    p = file_path.lower()
    if "architecture" in p:
        return "architecture"
    if "implementation" in p or "phase" in p:
        return "implementation"
    if "product" in p:
        return "product"
    if "superpowers" in p:
        return "plan"
    return "general"
