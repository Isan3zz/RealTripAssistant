"""
Application configuration.

Settings are loaded from environment variables and the local .env file.
SQLite remains the default runtime store for local development.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings."""

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Logging
    log_level: str = "INFO"

    # Storage
    data_dir: str = "data"
    db_url: str = "sqlite:///data/realtrip.db"

    # External providers
    tuniu_api_key: str = ""
    gaode_key: str = ""

    # Final rule validation should not call external tools by default.
    external_rule_checks_enabled: bool = False

    # ── RAG 模块配置 ────────────────────────────────

    # ElasticSearch
    es_host: str = "http://localhost:9200"
    es_index_name: str = "realtrip_knowledge"
    es_username: str = ""
    es_password: str = ""

    # Embedding (OpenAI)
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 20

    # 文档分块
    chunk_size: int = 500       # 每个 chunk 的字符数
    chunk_overlap: int = 50     # 相邻 chunk 重叠字符数

    # 检索
    top_k_per_query: int = 10      # 每条查询返回的 top-K
    final_top_k: int = 10          # rerank 后最终返回的 top-K
    rag_retrieval_max_workers: int = 6  # 并行检索最大线程数
    bm25_weight: float = 1.0       # BM25 在 RRF 融合中的权重
    knn_weight: float = 1.0        # kNN 在 RRF 融合中的权重
    rrf_rank_constant: int = 60    # RRF 平滑常数

    # 去重
    dedup_threshold: float = 0.85  # Jaccard 相似度阈值

    # Rerank
    rerank_model_name: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cpu"
    rerank_batch_size: int = 16

    # Query 重写
    query_rewrite_temperature: float = 0.3

    # HyDE
    hyde_temperature: float = 0.7
    hyde_word_count: int = 200

    # PostgreSQL fields kept for later migration; SQLite is still the default.
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "realtrip"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def effective_db_url(self) -> str:
        """Return the configured database URL."""
        if self.db_url.startswith("sqlite"):
            return self.db_url
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
