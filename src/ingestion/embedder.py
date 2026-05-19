import asyncio
import logging
from dataclasses import dataclass
from vertexai.language_models import TextEmbeddingModel
from src.ingestion.chunkers import Chunk
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class EmbeddedChunk:
    chunk_id: str
    document_id: str
    text: str
    embedding: list[float]
    chunk_index: int
    metadata: dict


class VertexEmbedder:
    def __init__(self):
        self.model = TextEmbeddingModel.from_pretrained(settings.embedding_model)
        self.batch_size = 250  # Vertex AI limit per request

    async def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        embedded = []
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            texts = [c.text for c in batch]
            embeddings = await asyncio.to_thread(self._embed_batch, texts)
            for chunk, emb in zip(batch, embeddings):
                embedded.append(
                    EmbeddedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        embedding=emb,
                        chunk_index=chunk.chunk_index,
                        metadata=chunk.metadata,
                    )
                )
        logger.info(f"Embedded {len(embedded)} chunks")
        return embedded

    async def embed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._embed_batch, [query])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        results = self.model.get_embeddings(texts)
        return [r.values for r in results]
