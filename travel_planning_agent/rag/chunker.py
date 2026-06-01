"""
rag/chunker.py — 递归字符分割器

按分隔符优先级递归切分文本：段落 > 句子 > 逗号 > 硬截断。
保证每个 chunk 不超过 chunk_size，并在相邻 chunk 之间保留 overlap。
"""

import logging
import uuid
from typing import Any

from travel_planning_agent.config import settings
from travel_planning_agent.rag.models import TextChunk

logger = logging.getLogger(__name__)

# 默认分隔符优先级（中文优先）
_DEFAULT_SEPARATORS = ["\n\n", "\n", "。", ".", "！", "？", "，", ",", " "]


class DocumentChunker:
    """递归字符分割器"""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        separators: list[str] | None = None,
    ):
        self._chunk_size = settings.chunk_size if chunk_size is None else chunk_size
        self._chunk_overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
        if self._chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if self._chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if self._chunk_overlap >= self._chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self._separators = separators or _DEFAULT_SEPARATORS

    def split_text(
        self,
        text: str,
        doc_id: str | None = None,
        source_title: str = "",
        source_url: str = "",
        category: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """将单篇文本切分为多个 TextChunk"""
        if not text or not text.strip():
            return []

        doc_id = doc_id or str(uuid.uuid4())[:8]
        segments = self._split_recursive(text.strip(), self._separators.copy())
        if self._chunk_overlap > 0:
            segments = self._add_overlap(segments)

        chunks: list[TextChunk] = []
        for i, seg in enumerate(segments):
            chunks.append(TextChunk(
                chunk_id=f"{doc_id}_chunk_{i:04d}",
                doc_id=doc_id,
                text=seg,
                chunk_index=i,
                source_title=source_title,
                source_url=source_url,
                category=category,
                metadata=metadata or {},
            ))

        return chunks

    def split_documents(
        self,
        documents: list[dict],
    ) -> list[TextChunk]:
        """批量切分文档

        documents: [{"text": "...", "doc_id": "...", "source_title": "...", ...}, ...]
        """
        all_chunks: list[TextChunk] = []
        for doc in documents:
            chunks = self.split_text(
                text=doc["text"],
                doc_id=doc.get("doc_id"),
                source_title=doc.get("source_title", ""),
                source_url=doc.get("source_url", ""),
                category=doc.get("category", ""),
                metadata=doc.get("metadata"),
            )
            all_chunks.extend(chunks)
        return all_chunks

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """递归分割核心：依次尝试每种分隔符，超过 chunk_size 则继续切分"""
        if not separators:
            # 无分隔符可用，硬截断
            return self._hard_split(text)

        sep = separators.pop(0)
        if sep not in text:
            return self._split_recursive(text, separators)

        # 按当前分隔符切分
        parts = text.split(sep)

        # 把分隔符附加回每个 part（除了最后一个），保持语义完整
        merged: list[str] = []
        for i, part in enumerate(parts):
            if merged and len(merged[-1]) + len(sep) + len(part) <= self._chunk_size:
                merged[-1] += sep + part
            else:
                if i > 0 and merged:
                    merged[-1] += sep
                merged.append(part)

        # 对每个仍超长的片段继续递归
        result: list[str] = []
        for m in merged:
            if len(m) <= self._chunk_size:
                if m.strip():
                    result.append(m.strip())
            else:
                # 用剩余分隔符继续切分
                sub = self._split_recursive(m, separators.copy())
                result.extend(sub)

        return result

    def _hard_split(self, text: str) -> list[str]:
        """无分隔符时的硬截断"""
        chunks: list[str] = []
        for i in range(0, len(text), self._chunk_size - self._chunk_overlap):
            chunk = text[i:i + self._chunk_size].strip()
            if chunk:
                chunks.append(chunk)
        return chunks

    def _add_overlap(self, segments: list[str]) -> list[str]:
        """在相邻 segment 之间添加重叠"""
        if len(segments) <= 1:
            return segments

        result = [segments[0]]
        for i in range(1, len(segments)):
            prev = segments[i - 1]
            curr = segments[i]
            # 取前一段尾部 overlap 字符加到当前段开头
            overlap_text = prev[-self._chunk_overlap:] if len(prev) > self._chunk_overlap else prev
            combined = overlap_text + curr
            result.append(combined[-self._chunk_size:])
        return result
