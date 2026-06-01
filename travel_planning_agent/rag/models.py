"""
rag/models.py — RAG 模块数据模型
"""

from pydantic import BaseModel, Field


class TextChunk(BaseModel):
    """文档文本块"""
    chunk_id: str                       # 唯一 ID
    doc_id: str                         # 源文档 ID
    text: str                           # 文本内容
    chunk_index: int = 0                # 在文档中的序号
    source_title: str = ""              # 文档标题
    source_url: str = ""                # 文档来源 URL
    category: str = ""                  # 分类标签
    metadata: dict = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """单条检索结果"""
    chunk: TextChunk
    score: float                        # 原始检索得分 (RRF 融合后)
    strategy: str                       # 检索维度标识


class RerankedResult(BaseModel):
    """Rerank 后的结果"""
    chunk: TextChunk
    original_score: float               # 原始检索得分
    original_strategy: str              # 来源检索维度
    rerank_score: float                 # rerank 得分


class RAGRequest(BaseModel):
    """RAG 查询请求"""
    query: str
    top_k: int = 10
    metadata_filter: dict | None = None


class RAGResponse(BaseModel):
    """RAG 查询响应"""
    query: str
    results: list[RerankedResult]
    total_candidates: int              # 去重前总候选数
    total_after_dedup: int             # 去重后数量


# ── 旅行规划检索专用模型 ──────────────────────────

class QueryDimension(BaseModel):
    """多维度扩展查询"""
    dimension: str                      # 维度名
    query_text: str                     # 检索用文本
    priority: int = 5                   # 优先级 1(低)-10(高)


class RAGPlanResponse(BaseModel):
    """旅行规划 RAG 检索响应"""
    destination: str
    queries_used: list[str]             # 实际生成的 query 文本
    dimensions_covered: list[str]       # 覆盖的维度列表
    results: list[RerankedResult]
    total_candidates: int
    total_after_dedup: int
