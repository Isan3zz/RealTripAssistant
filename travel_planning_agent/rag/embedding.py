"""
rag/embedding.py — OpenAI Embedding 服务封装

复用项目已有的 openai 依赖，调用 text-embedding-3-small 模型。
"""

import logging
from typing import Any

from travel_planning_agent.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """OpenAI Embedding 服务，不依赖 LLMClient 协议，直接使用 openai.OpenAI 实例"""

    def __init__(
        self,
        client: Any = None,           # openai.OpenAI 实例
        model: str | None = None,
        batch_size: int | None = None,
    ):
        self._client = client
        self._model = model or settings.embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size

    def _get_client(self):
        """惰性获取 OpenAI 客户端"""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
            )
        return self._client

    def embed_single(self, text: str) -> list[float]:
        """单文本 embedding"""
        result = self.embed_batch([text])
        return result[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量 embedding，自动分批"""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        client = self._get_client()

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            try:
                resp = client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                for item in resp.data:
                    all_embeddings.append(item.embedding)
            except Exception as e:
                logger.error("Embedding 批次 %d-%d 失败: %s", i, i + len(batch), e)
                raise

        return all_embeddings
