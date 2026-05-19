"""
Graph RAG — extract entities → build knowledge graph → traverse for retrieval.

Standard vector search finds similar text. Graph RAG finds CONNECTED information.
Example: "What did CEO X say about product Y in Q3?"
  Vector: returns chunks that mention all three terms (rare).
  Graph:  X → (spoke_about) → Y → (in) → Q3 earnings call → retrieves those chunks.
"""
import asyncio
import logging
import re
import networkx as nx
from src.retrieval.base import BaseRetriever
from src.retrieval.vector_store import VectorStore
from src.ingestion.embedder import VertexEmbedder
from src.generation.gemini import GeminiClient
from src.api.models import Source

logger = logging.getLogger(__name__)

# Module-level graph cache (rebuilt on each ingest — for demo purposes)
_graph_cache: dict[str, nx.DiGraph] = {}


class GraphRetriever(BaseRetriever):
    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.vector_store = VectorStore()
        self.embedder = VertexEmbedder()
        self.gemini = GeminiClient()

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        graph = await self._get_or_build_graph()

        # Extract query entities
        query_entities = await self._extract_entities(query)
        logger.debug(f"Graph: query entities={query_entities}")

        if not query_entities or graph.number_of_nodes() == 0:
            # Fall back to vector search
            emb = await asyncio.to_thread(self.embedder._embed_batch, [query])
            return await self.vector_store.search(emb[0], top_k, self.namespace)

        # Find nodes matching query entities
        matched_nodes = [
            n for n in graph.nodes
            if any(e.lower() in str(n).lower() for e in query_entities)
        ]

        # BFS to expand neighborhood
        candidate_texts = set()
        for node in matched_nodes[:3]:
            for neighbor in nx.ego_graph(graph, node, radius=2).nodes:
                text = graph.nodes[neighbor].get("text", "")
                if text:
                    candidate_texts.add(text)

        if not candidate_texts:
            emb = await asyncio.to_thread(self.embedder._embed_batch, [query])
            return await self.vector_store.search(emb[0], top_k, self.namespace)

        # Score candidates by relevance to query
        query_tokens = set(query.lower().split())
        scored = []
        for text in candidate_texts:
            text_tokens = set(text.lower().split())
            score = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
            scored.append((text, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            Source(
                document_id="graph",
                chunk_id=f"graph_{i}",
                text=text,
                score=round(score, 4),
                metadata={"retriever": "graph"},
            )
            for i, (text, score) in enumerate(scored[:top_k])
        ]

    async def _get_or_build_graph(self) -> nx.DiGraph:
        if self.namespace in _graph_cache:
            return _graph_cache[self.namespace]
        graph = await self._build_graph()
        _graph_cache[self.namespace] = graph
        return graph

    async def _build_graph(self) -> nx.DiGraph:
        G = nx.DiGraph()
        texts = await self.vector_store.get_all_texts(self.namespace)
        for text in texts[:200]:  # cap for demo
            entities = await self._extract_entities(text)
            for e in entities:
                if not G.has_node(e):
                    G.add_node(e, text=text)
            for i, e1 in enumerate(entities):
                for e2 in entities[i + 1 :]:
                    G.add_edge(e1, e2, relation="co_occurs")
        logger.info(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return G

    async def _extract_entities(self, text: str) -> list[str]:
        # Simple noun-phrase extraction (replace with spaCy NER for production)
        words = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", text)
        return list(set(words))[:10]
