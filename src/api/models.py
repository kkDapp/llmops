from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RAGStrategy(str, Enum):
    naive = "naive"
    advanced = "advanced"
    hybrid = "hybrid"
    graph = "graph"
    agentic = "agentic"
    fusion = "fusion"   # parallel hybrid+graph with RRF merge + cross-encoder reranking


class RAGRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    strategy: RAGStrategy = RAGStrategy.hybrid
    top_k: int = Field(default=5, ge=1, le=20)
    namespace: str = Field(default="default", description="Tenant namespace")
    stream: bool = False


class Source(BaseModel):
    document_id: str
    chunk_id: str
    text: str
    score: float
    metadata: dict = {}


class RAGResponse(BaseModel):
    answer: str
    strategy: str
    sources: list[Source]
    latency_ms: float
    tokens_used: int
    cached: bool = False
    # Verification layer output — None when verification is disabled
    confidence_score: Optional[float] = None
    unsupported_claims: list[str] = []


class IngestRequest(BaseModel):
    gcs_uri: str = Field(..., description="gs://bucket/path/to/document.pdf")
    namespace: str = "default"
    metadata: dict = {}


class IngestResponse(BaseModel):
    document_id: str
    chunks_created: int
    status: str
    message: str


class EvalRequest(BaseModel):
    strategy: RAGStrategy = RAGStrategy.hybrid
    namespace: str = "default"
    test_dataset_path: Optional[str] = None


class EvalMetrics(BaseModel):
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    answer_correctness: float


class EvalResponse(BaseModel):
    strategy: str
    metrics: EvalMetrics
    num_questions: int
    run_id: str


class CompareRequest(BaseModel):
    query: str
    strategies: list[RAGStrategy] = [
        RAGStrategy.naive,
        RAGStrategy.advanced,
        RAGStrategy.hybrid,
    ]
    namespace: str = "default"


class StrategyResult(BaseModel):
    strategy: str
    answer: str
    sources_count: int
    latency_ms: float
    tokens_used: int


class CompareResponse(BaseModel):
    query: str
    results: list[StrategyResult]
