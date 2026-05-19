from src.api.models import RAGStrategy

BASE_SYSTEM = """You are an enterprise knowledge assistant. Answer based only on the provided context.
If the context does not contain enough information, say "I don't have enough information in the knowledge base."
Be concise, accurate, and cite sources when relevant."""

STRATEGY_HINTS = {
    RAGStrategy.naive: "Answer directly from the retrieved passages.",
    RAGStrategy.advanced: "The context has been reranked for relevance. Focus on the highest-scored passages.",
    RAGStrategy.hybrid: "Context combines keyword and semantic search. Synthesise across all passages.",
    RAGStrategy.graph: "Context was retrieved via entity relationships. Pay attention to how concepts connect.",
    RAGStrategy.agentic: "Context was gathered iteratively by a search agent. Integrate all gathered information.",
}


def build_prompt(query: str, context_chunks: list, strategy: RAGStrategy) -> str:
    context = "\n\n---\n\n".join(
        f"[Source {i+1}] {c.text}" for i, c in enumerate(context_chunks)
    )
    hint = STRATEGY_HINTS.get(strategy, "")
    return (
        f"System: {BASE_SYSTEM}\n\n"
        f"Strategy note: {hint}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer:"
    )
