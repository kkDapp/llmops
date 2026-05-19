"""
Naive RAG — embed query → top-k cosine similarity → return chunks.
Baseline strategy. Fast, simple, no query manipulation.
"""
import asyncio
import logging
from src.retrieval.base import BaseRetriever
from src.retrieval.vector_store import VectorStore
from src.ingestion.embedder import VertexEmbedder
from src.api.models import Source

logger = logging.getLogger(__name__)


class NaiveRetriever(BaseRetriever):
    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.vector_store = VectorStore()
        self.embedder = VertexEmbedder()

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        query_embedding = await asyncio.to_thread(
            self.embedder._embed_batch, [query]
        )
        results = await self.vector_store.search(
            query_embedding=query_embedding[0],
            top_k=top_k,
            namespace=self.namespace,
        )
        logger.debug(f"Naive: retrieved {len(results)} chunks for query='{query[:50]}'")
        return results
