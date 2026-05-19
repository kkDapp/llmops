import asyncio
import logging
import chromadb
from google.cloud.aiplatform.matching_engine import MatchingEngineIndex, MatchingEngineIndexEndpoint
from src.ingestion.embedder import EmbeddedChunk, VertexEmbedder
from src.api.models import Source
from config.settings import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """Unified vector store — Vertex AI Vector Search in prod, ChromaDB locally."""

    def __init__(self):
        self.embedder = VertexEmbedder()
        if settings.use_vertex_vector_search:
            self._backend = VertexVectorSearch()
        else:
            self._backend = ChromaVectorStore()

    async def upsert(self, chunks: list[EmbeddedChunk], namespace: str = "default"):
        await self._backend.upsert(chunks, namespace)

    async def search(self, query_embedding: list[float], top_k: int, namespace: str) -> list[Source]:
        return await self._backend.search(query_embedding, top_k, namespace)

    async def get_all_texts(self, namespace: str) -> list[str]:
        return await self._backend.get_all_texts(namespace)


class ChromaVectorStore:
    def __init__(self):
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

    def _collection(self, namespace: str):
        return self.client.get_or_create_collection(f"{settings.chroma_collection}_{namespace}")

    async def upsert(self, chunks: list[EmbeddedChunk], namespace: str):
        collection = self._collection(namespace)
        await asyncio.to_thread(
            collection.upsert,
            ids=[c.chunk_id for c in chunks],
            embeddings=[c.embedding for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[{**c.metadata, "document_id": c.document_id} for c in chunks],
        )
        logger.info(f"Upserted {len(chunks)} chunks to ChromaDB namespace={namespace}")

    async def search(self, query_embedding: list[float], top_k: int, namespace: str) -> list[Source]:
        collection = self._collection(namespace)
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        sources = []
        for i, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            sources.append(Source(
                document_id=meta.get("document_id", "unknown"),
                chunk_id=results["ids"][0][i],
                text=doc,
                score=round(1 - dist, 4),
                metadata=meta,
            ))
        return sources

    async def get_all_texts(self, namespace: str) -> list[str]:
        collection = self._collection(namespace)
        result = await asyncio.to_thread(collection.get, include=["documents"])
        return result["documents"]


class VertexVectorSearch:
    def __init__(self):
        self.index_endpoint = MatchingEngineIndexEndpoint(
            index_endpoint_name=settings.vector_search_endpoint_id
        )

    async def upsert(self, chunks: list[EmbeddedChunk], namespace: str):
        datapoints = [
            {"id": c.chunk_id, "feature_vector": c.embedding, "restricts": [{"namespace": namespace}]}
            for c in chunks
        ]
        await asyncio.to_thread(
            MatchingEngineIndex(index_name=settings.vector_search_index_id).upsert_datapoints,
            datapoints=datapoints,
        )

    async def search(self, query_embedding: list[float], top_k: int, namespace: str) -> list[Source]:
        response = await asyncio.to_thread(
            self.index_endpoint.find_neighbors,
            deployed_index_id="rag_index",
            queries=[query_embedding],
            num_neighbors=top_k,
        )
        return [
            Source(
                document_id=n.id.split("_")[0],
                chunk_id=n.id,
                text="",  # Fetch text from GCS or BQ by chunk_id
                score=round(n.distance, 4),
            )
            for n in response[0]
        ]

    async def get_all_texts(self, namespace: str) -> list[str]:
        return []
