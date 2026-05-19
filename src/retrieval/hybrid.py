"""
Hybrid RAG — BM25 (sparse) + Vector (dense) with Reciprocal Rank Fusion.

BM25 captures keyword matches. Vector captures semantic similarity.
RRF fusion combines both rankings without needing score normalization.

RRF formula: score(d) = Σ 1 / (k + rank(d))  where k=60 is the smoothing constant.
"""
import asyncio
import logging
from rank_bm25 import BM25Okapi
from src.retrieval.base import BaseRetriever
from src.retrieval.vector_store import VectorStore
from src.ingestion.embedder import VertexEmbedder
from src.api.models import Source

logger = logging.getLogger(__name__)
RRF_K = 60


class HybridRetriever(BaseRetriever):
    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.vector_store = VectorStore()
        self.embedder = VertexEmbedder()

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        # Parallel: dense vector search + BM25 sparse search
        query_emb = await asyncio.to_thread(self.embedder._embed_batch, [query])
        dense_task = self.vector_store.search(query_emb[0], top_k=top_k * 2, namespace=self.namespace)
        sparse_task = self._bm25_search(query, top_k=top_k * 2)

        dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)

        # RRF fusion
        fused = self._reciprocal_rank_fusion(dense_results, sparse_results)
        logger.debug(f"Hybrid: dense={len(dense_results)}, sparse={len(sparse_results)}, fused={len(fused)}")
        return fused[:top_k]

    async def _bm25_search(self, query: str, top_k: int) -> list[Source]:
        all_texts = await self.vector_store.get_all_texts(self.namespace)
        if not all_texts:
            return []

        tokenized = [t.lower().split() for t in all_texts]
        bm25 = BM25Okapi(tokenized)
        query_tokens = query.lower().split()
        scores = bm25.get_scores(query_tokens)

        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            Source(
                document_id=f"bm25_{i}",
                chunk_id=f"bm25_{i}",
                text=all_texts[i],
                score=round(float(scores[i]), 4),
            )
            for i in top_indices
            if scores[i] > 0
        ]

    @staticmethod
    def _reciprocal_rank_fusion(
        dense: list[Source], sparse: list[Source]
    ) -> list[Source]:
        scores: dict[str, float] = {}
        chunks: dict[str, Source] = {}

        for rank, src in enumerate(dense):
            key = src.text[:80]
            scores[key] = scores.get(key, 0) + 1 / (RRF_K + rank + 1)
            chunks[key] = src

        for rank, src in enumerate(sparse):
            key = src.text[:80]
            scores[key] = scores.get(key, 0) + 1 / (RRF_K + rank + 1)
            if key not in chunks:
                chunks[key] = src

        ranked_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
        result = []
        for key in ranked_keys:
            c = chunks[key]
            c.score = round(scores[key], 6)
            result.append(c)
        return result
