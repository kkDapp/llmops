"""
Agentic RAG — the LLM drives the retrieval loop.

Instead of a fixed pipeline, the agent:
  1. Analyses the query
  2. Decides which tools to call (search, summarize, filter, web)
  3. Reflects on results — retrieves again if insufficient
  4. Synthesises the final answer

Tools available to the agent:
  - search_documents(query, top_k) → chunks
  - get_document_summary(doc_id) → summary
  - filter_by_date(chunks, after) → chunks
  - refine_query(original, context) → better_query
"""
import asyncio
import json
import logging
from src.retrieval.base import BaseRetriever
from src.retrieval.vector_store import VectorStore
from src.ingestion.embedder import VertexEmbedder
from src.generation.gemini import GeminiClient
from src.api.models import Source

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 4

AGENT_SYSTEM_PROMPT = """You are a RAG retrieval agent. You have tools to search documents.
At each step, decide which tool to call or produce a FINAL answer.
Respond in JSON: {"action": "tool_name", "args": {...}} or {"action": "final", "answer": "..."}.

Available tools:
- search_documents: {"query": str, "top_k": int}
- refine_query: {"original": str, "context": str}
- filter_relevant: {"chunks": [str], "criterion": str}
"""


class AgenticRetriever(BaseRetriever):
    def __init__(self, namespace: str = "default"):
        super().__init__(namespace)
        self.vector_store = VectorStore()
        self.embedder = VertexEmbedder()
        self.gemini = GeminiClient()
        self._collected_chunks: list[Source] = []

    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        self._collected_chunks = []
        context = ""
        current_query = query

        for iteration in range(MAX_ITERATIONS):
            prompt = (
                f"{AGENT_SYSTEM_PROMPT}\n\n"
                f"User query: {query}\n"
                f"Current search query: {current_query}\n"
                f"Context so far: {context[:500]}\n"
                f"Iteration: {iteration + 1}/{MAX_ITERATIONS}\n"
                f"Decide next action:"
            )
            raw, _ = await self.gemini.generate_raw(prompt, max_tokens=300)

            try:
                action = json.loads(raw.strip())
            except json.JSONDecodeError:
                logger.warning(f"Agentic: invalid JSON response, falling back")
                break

            if action.get("action") == "final":
                break
            elif action.get("action") == "search_documents":
                args = action.get("args", {})
                search_q = args.get("query", current_query)
                k = min(args.get("top_k", 5), 10)
                chunks = await self._search(search_q, k)
                self._collected_chunks.extend(chunks)
                context = " | ".join(c.text[:100] for c in chunks)
                logger.debug(f"Agentic iter {iteration+1}: searched '{search_q}', got {len(chunks)} chunks")
            elif action.get("action") == "refine_query":
                args = action.get("args", {})
                current_query = args.get("original", current_query)
            else:
                break

        # Deduplicate and rank by score
        seen = set()
        unique = []
        for c in self._collected_chunks:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                unique.append(c)

        unique.sort(key=lambda x: x.score, reverse=True)
        logger.debug(f"Agentic: final {len(unique)} unique chunks after {iteration+1} iterations")
        return unique[:top_k]

    async def _search(self, query: str, top_k: int) -> list[Source]:
        emb = await asyncio.to_thread(self.embedder._embed_batch, [query])
        return await self.vector_store.search(emb[0], top_k, self.namespace)
