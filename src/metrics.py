"""Shared Prometheus metrics — import from here to avoid duplicate-registration errors."""
from prometheus_client import Counter, Gauge, Histogram

request_count = Counter(
    "rag_requests_total",
    "Total RAG API requests",
    ["method", "endpoint", "strategy", "status"],
)
request_latency = Histogram(
    "rag_request_latency_seconds",
    "RAG request latency",
    ["endpoint", "strategy"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
active_requests = Gauge(
    "rag_active_requests",
    "Number of in-flight RAG requests",
)
cache_hits = Counter(
    "rag_cache_hits_total",
    "Semantic cache hits",
    ["strategy"],
)
cache_misses = Counter(
    "rag_cache_misses_total",
    "Semantic cache misses",
    ["strategy"],
)
tokens_total = Counter(
    "rag_tokens_total",
    "LLM tokens consumed",
    ["strategy", "model_tier"],
)
guardrail_blocks = Counter(
    "rag_guardrail_blocks_total",
    "Requests blocked by guardrails",
    ["direction"],
)
reranker_candidates = Histogram(
    "rag_reranker_candidates",
    "Candidates passed to cross-encoder reranker before reranking",
    buckets=[5, 10, 20, 30, 50],
)
verification_confidence = Histogram(
    "rag_verification_confidence",
    "Answer confidence score from verification layer (fraction of supported claims)",
    buckets=[0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
verification_unsupported_total = Counter(
    "rag_verification_unsupported_claims_total",
    "Total unsupported claims detected by verification layer",
)
