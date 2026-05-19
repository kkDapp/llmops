"""
Cross-encoder reranker — rescores retrieval candidates using query-chunk pair scoring.

Why cross-encoder over bi-encoder (embedding cosine similarity)?

  Bi-encoder (what we use for retrieval):
    - Embeds query and chunk independently
    - Fast: O(1) per candidate at query time
    - Less accurate: query and chunk never "see" each other

  Cross-encoder (this module):
    - Scores (query, chunk) jointly — query attends to chunk tokens
    - Slower: O(n) forward passes for n candidates
    - Much more accurate: the model can reason about relevance in context

The standard pipeline is bi-encoder recall (top-50 cheap) → cross-encoder rerank (top-5 precise).
This is how Cohere Rerank, Voyage, and all enterprise search systems work.

Model: ms-marco-MiniLM-L-6-v2 (~100MB, no GPU required, fast on CPU)
  - Trained on MS MARCO passage re-ranking benchmark
  - Returns raw logit scores (higher = more relevant, no fixed scale)
  - Loaded lazily on first request; startup penalty is one-time per process
"""
import asyncio
import logging
from src.api.models import Source

logger = logging.getLogger(__name__)

_cross_encoder = None


def _load_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
            logger.info("Cross-encoder loaded: ms-marco-MiniLM-L-6-v2")
        except Exception as e:
            logger.warning(f"Cross-encoder unavailable ({e}) — falling back to original ranking")
    return _cross_encoder


class CrossEncoderReranker:
    """
    Reranks a candidate list of retrieved chunks for a given query.

    Usage:
        reranker = CrossEncoderReranker()
        top_chunks = await reranker.rerank(query, candidates, top_k=5)

    The caller should pass more candidates than top_k (e.g. top_k * 10)
    so the reranker has material to select from. Passing only top_k candidates
    degrades to a no-op sort.
    """

    async def rerank(self, query: str, candidates: list[Source], top_k: int) -> list[Source]:
        if not candidates:
            return candidates

        model = await asyncio.to_thread(_load_cross_encoder)

        if model is None:
            # No cross-encoder available — return highest-scoring by original retrieval score
            return sorted(candidates, key=lambda s: s.score, reverse=True)[:top_k]

        pairs = [(query, c.text[:512]) for c in candidates]
        scores = await asyncio.to_thread(model.predict, pairs)

        reranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

        result = []
        for source, score in reranked[:top_k]:
            source = source.model_copy()
            source.score = round(float(score), 4)
            source.metadata = {**source.metadata, "reranked": True, "cross_encoder_score": round(float(score), 4)}
            result.append(source)

        logger.debug(
            f"Reranker: {len(candidates)} candidates → top {top_k} | "
            f"top score={result[0].score:.4f} bottom score={result[-1].score:.4f}"
        )
        return result
