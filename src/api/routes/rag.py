import asyncio
import time
import logging
from fastapi import APIRouter, HTTPException
from src.api.models import (
    RAGRequest, RAGResponse, RAGStrategy,
    CompareRequest, CompareResponse, StrategyResult,
)
from src.retrieval.naive import NaiveRetriever
from src.retrieval.advanced import AdvancedRetriever
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.graph import GraphRetriever
from src.retrieval.agentic import AgenticRetriever
from src.retrieval.fusion import FusionRetriever
from src.generation.gemini import GeminiClient
from src.cache.semantic_cache import SemanticCache
from src.guardrails.filters import GuardrailFilter
from src.reranking.reranker import CrossEncoderReranker
from src.verification.verifier import AnswerVerifier
from src.llmops.mlflow_tracker import get_tracker
from src.evaluation.bq_logger import BigQueryLogger
from src.metrics import (
    cache_hits, cache_misses, tokens_total, guardrail_blocks,
    reranker_candidates, verification_confidence, verification_unsupported_total,
)
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["RAG"])

gemini = GeminiClient()
cache = SemanticCache()
guardrails = GuardrailFilter()
reranker = CrossEncoderReranker()
verifier = AnswerVerifier()
tracker = get_tracker()
bq_logger = BigQueryLogger()

RETRIEVERS = {
    RAGStrategy.naive:    NaiveRetriever,
    RAGStrategy.advanced: AdvancedRetriever,
    RAGStrategy.hybrid:   HybridRetriever,
    RAGStrategy.graph:    GraphRetriever,
    RAGStrategy.agentic:  AgenticRetriever,
    RAGStrategy.fusion:   FusionRetriever,
}


@router.post("/query", response_model=RAGResponse)
async def rag_query(req: RAGRequest):
    start = time.time()

    # Guardrails: validate input
    if settings.enable_guardrails:
        issue = guardrails.check_input(req.query)
        if issue:
            guardrail_blocks.labels(direction="input").inc()
            raise HTTPException(status_code=400, detail=issue)

    # Semantic cache lookup
    if settings.use_semantic_cache:
        cached = await cache.get(req.query, req.strategy, req.namespace)
        if cached:
            cache_hits.labels(strategy=req.strategy.value).inc()
            cached.cached = True
            return cached
        cache_misses.labels(strategy=req.strategy.value).inc()

    # Select retriever
    retriever_cls = RETRIEVERS.get(req.strategy)
    if not retriever_cls:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    retriever = retriever_cls(namespace=req.namespace)

    # Fetch more candidates when reranker is enabled so it has material to select from
    candidate_k = (
        min(req.top_k * settings.rerank_candidate_multiplier, settings.rerank_max_candidates)
        if settings.enable_reranker else req.top_k
    )
    chunks = await retriever.retrieve(req.query, top_k=candidate_k)

    if not chunks:
        raise HTTPException(status_code=404, detail="No relevant documents found")

    # Cross-encoder reranking: re-scores all candidates jointly with the query.
    # Always run when enabled — cross-encoder reorders by relevance even when
    # len(chunks) == top_k, which produces better results than RRF scores alone.
    if settings.enable_reranker:
        reranker_candidates.observe(len(chunks))
        chunks = await reranker.rerank(req.query, chunks, top_k=req.top_k)
    else:
        chunks = chunks[:req.top_k]

    # Generate answer (model router selects Flash/Pro automatically)
    answer, tokens, model_tier = await gemini.generate(req.query, chunks, req.strategy)

    # Guardrails: validate output
    if settings.enable_guardrails:
        cleaned = guardrails.check_output(answer)
        if cleaned != answer:
            guardrail_blocks.labels(direction="output").inc()
        answer = cleaned

    # Verification: extract claims and check against retrieved context
    confidence_score = None
    unsupported_claims: list[str] = []
    if settings.enable_verification:
        result = await verifier.verify(req.query, answer, chunks)
        confidence_score = result.confidence_score
        unsupported_claims = result.unsupported_claims
        verification_confidence.observe(confidence_score)
        if unsupported_claims:
            verification_unsupported_total.inc(len(unsupported_claims))

    tokens_total.labels(strategy=req.strategy.value, model_tier=model_tier).inc(tokens)
    latency_ms = round((time.time() - start) * 1000, 2)
    response = RAGResponse(
        answer=answer,
        strategy=req.strategy.value,
        sources=chunks,
        latency_ms=latency_ms,
        tokens_used=tokens,
        cached=False,
        confidence_score=confidence_score,
        unsupported_claims=unsupported_claims,
    )

    # Write to cache
    if settings.use_semantic_cache:
        await cache.set(req.query, req.strategy, req.namespace, response)

    # Log to MLflow + BigQuery (fire-and-forget, non-blocking)
    asyncio.create_task(bq_logger.log_query(req.query, req.strategy.value, latency_ms, tokens, False))
    tracker.log_query(
        query=req.query,
        strategy=req.strategy.value,
        namespace=req.namespace,
        latency_ms=latency_ms,
        tokens_used=tokens,
        cached=False,
        model_tier=model_tier,
    )

    return response


@router.post("/compare", response_model=CompareResponse)
async def compare_strategies(req: CompareRequest):
    async def run_strategy(strategy: RAGStrategy) -> StrategyResult:
        start = time.time()
        try:
            retriever = RETRIEVERS[strategy](namespace=req.namespace)
            chunks = await retriever.retrieve(req.query, top_k=5)
            answer, tokens, _tier = await gemini.generate(req.query, chunks, strategy)
            return StrategyResult(
                strategy=strategy.value,
                answer=answer,
                sources_count=len(chunks),
                latency_ms=round((time.time() - start) * 1000, 2),
                tokens_used=tokens,
            )
        except Exception as e:
            logger.error(f"Strategy {strategy} failed: {e}")
            return StrategyResult(
                strategy=strategy.value,
                answer=f"Error: {str(e)}",
                sources_count=0,
                latency_ms=round((time.time() - start) * 1000, 2),
                tokens_used=0,
            )

    results = await asyncio.gather(*[run_strategy(s) for s in req.strategies])
    return CompareResponse(query=req.query, results=list(results))
