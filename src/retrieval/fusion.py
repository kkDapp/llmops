"""
Fusion RAG — parallel retrieval across hybrid (vector+BM25) and graph with RRF merging.

Why fusion instead of picking one strategy?

  Each retriever has a different recall failure mode:
    Hybrid (vector+BM25): misses multi-hop entity connections
    Graph:                misses queries without clear named entities

  Running both in parallel and fusing with RRF captures what each one misses.
  Total latency = max(slowest retriever), NOT the sum — parallel execution.

RRF formula: score(d) = Σ 1 / (k + rank_i(d))   k=60 smoothing constant
Chunks appearing in multiple result sets receive a higher fused score.
Chunks unique to one retriever are still included but ranked lower.

When to use fusion vs hybrid:
  hybrid  → most queries (fast, good quality, ~6.5s avg from MLflow)
  fusion  → high-stakes queries where missing a relevant document is costly
            (analyst reports, compliance queries, root-cause analysis)
            Expect +2–4s latency vs hybrid due to graph traversal.
"""
import asyncio
import logging
from src.retrieval.base import BaseRetriever
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.graph import GraphRetriever
from src.api.models import Source

logger = logging.getLogger(__name__)
RRF_K = 60


class FusionRetriever(BaseRetriever):
    """
    Retrieval orchestrator: runs hybrid and graph retrievers in parallel,
    merges results with Reciprocal Rank Fusion, returns unified top-K.

    Individual retriever failures are caught and logged — fusion degrades
    gracefully to whichever sources succeed.
    """

    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.hybrid = HybridRetriever(namespace)
        self.graph = GraphRetriever(namespace)

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        tasks = {
            "hybrid": self.hybrid.retrieve(query, top_k=top_k),
            "graph":  self.graph.retrieve(query, top_k=top_k),
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        source_results: list[list[Source]] = []

        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Fusion: {name} retriever failed: {result}")
            else:
                source_results.append(result)
                logger.debug(f"Fusion: {name} returned {len(result)} candidates")

        if not source_results:
            # All retrievers failed — hard fallback to hybrid only
            logger.error("Fusion: all retrievers failed, retrying hybrid only")
            return await self.hybrid.retrieve(query, top_k=top_k)

        if len(source_results) == 1:
            # Only one source succeeded — RRF is a no-op, just return it
            return source_results[0][:top_k]

        fused = self._rrf_merge(source_results)
        logger.info(
            f"Fusion: merged {sum(len(l) for l in source_results)} candidates "
            f"({len(source_results)} sources) → {len(fused)} unique → top_k={top_k}"
        )
        return fused[:top_k]

    @staticmethod
    def _rrf_merge(result_lists: list[list[Source]]) -> list[Source]:
        scores: dict[str, float] = {}
        chunks: dict[str, Source] = {}

        for ranked_list in result_lists:
            for rank, source in enumerate(ranked_list):
                key = source.text[:80]
                rrf_score = 1 / (RRF_K + rank + 1)
                scores[key] = scores.get(key, 0) + rrf_score
                if key not in chunks:
                    chunks[key] = source

        ranked_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
        result = []
        for key in ranked_keys:
            src = chunks[key]
            src = src.model_copy()
            src.score = round(scores[key], 6)
            src.metadata = {**src.metadata, "retriever": "fusion", "fusion_rrf_score": src.score}
            result.append(src)
        return result
