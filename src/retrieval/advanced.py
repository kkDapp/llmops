"""
Advanced RAG pipeline:
  1. Query rewriting — HyDE (Hypothetical Document Embedding)
  2. Multi-query expansion — 3 query variants
  3. Dense retrieval
  4. Cross-encoder reranking
  5. Context compression — remove irrelevant sentences

HyDE: instead of embedding the raw query, generate a hypothetical answer
and embed THAT. The answer embedding is closer to real document embeddings.
"""
import asyncio
import logging
from sentence_transformers import CrossEncoder
from src.retrieval.base import BaseRetriever
from src.retrieval.vector_store import VectorStore
from src.ingestion.embedder import VertexEmbedder
from src.generation.gemini import GeminiClient
from src.api.models import Source

logger = logging.getLogger(__name__)


class AdvancedRetriever(BaseRetriever):
    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.vector_store = VectorStore()
        self.embedder = VertexEmbedder()
        self.gemini = GeminiClient()
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        # Step 1: HyDE — generate hypothetical document
        hyde_doc = await self._hypothetical_document(query)

        # Step 2: Multi-query expansion
        queries = await self._expand_queries(query)
        queries.append(hyde_doc)  # include HyDE variant

        # Step 3: Retrieve for each query, merge unique results
        all_chunks: dict[str, Source] = {}
        for q in queries:
            emb = await asyncio.to_thread(self.embedder._embed_batch, [q])
            results = await self.vector_store.search(emb[0], top_k=top_k, namespace=self.namespace)
            for r in results:
                if r.chunk_id not in all_chunks:
                    all_chunks[r.chunk_id] = r

        candidates = list(all_chunks.values())

        # Step 4: Cross-encoder reranking
        reranked = await asyncio.to_thread(self._rerank, query, candidates)

        # Step 5: Context compression — keep only relevant sentences
        compressed = [self._compress(query, chunk) for chunk in reranked[:top_k]]
        logger.debug(f"Advanced: {len(candidates)} candidates → {len(compressed)} after rerank+compress")
        return compressed

    async def _hypothetical_document(self, query: str) -> str:
        prompt = f"Write a short paragraph that would be a perfect answer to: {query}"
        text, _ = await self.gemini.generate_raw(prompt, max_tokens=200)
        return text

    async def _expand_queries(self, query: str) -> list[str]:
        prompt = (
            f"Generate 2 alternative phrasings of this query for document retrieval. "
            f"Return only the queries, one per line.\nQuery: {query}"
        )
        text, _ = await self.gemini.generate_raw(prompt, max_tokens=100)
        return [q.strip() for q in text.strip().split("\n") if q.strip()][:2]

    def _rerank(self, query: str, chunks: list[Source]) -> list[Source]:
        if not chunks:
            return chunks
        pairs = [(query, c.text) for c in chunks]
        scores = self.reranker.predict(pairs)
        ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        for chunk, score in ranked:
            chunk.score = round(float(score), 4)
        return [c for c, _ in ranked]

    def _compress(self, query: str, chunk: Source) -> Source:
        """Keep only sentences that contain query keywords."""
        keywords = set(query.lower().split())
        sentences = chunk.text.split(". ")
        relevant = [s for s in sentences if any(k in s.lower() for k in keywords)]
        if relevant:
            chunk.text = ". ".join(relevant)
        return chunk
