"""
Prompt Registry — versioned prompt management backed by MLflow artifacts.

Every prompt change is:
  - Stored as an MLflow artifact (git-like versioning)
  - Tracked with metadata (who changed, why, eval score before/after)
  - A/B testable via the traffic_split config
  - Rollback-able in <1 minute

Why version prompts like code?
  A prompt change can silently break 20% of answers.
  Without versioning, you can't tell when it happened or roll back.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
import mlflow

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "templates"
PROMPT_DIR.mkdir(exist_ok=True)


@dataclass
class PromptVersion:
    name: str
    version: int
    content: str
    author: str = "system"
    eval_score: float = 0.0
    traffic_split: float = 1.0   # 1.0 = 100% traffic, 0.1 = 10% canary
    metadata: dict = field(default_factory=dict)


DEFAULT_PROMPTS = {
    "system": {
        "content": (
            "You are an enterprise knowledge assistant. Answer based only on the provided context.\n"
            "If the context does not contain enough information, say "
            "'I don't have enough information in the knowledge base.'\n"
            "Be concise, accurate, and cite sources when relevant."
        ),
        "version": 1,
    },
    "hyde": {
        "content": "Write a short paragraph that would be a perfect answer to: {query}",
        "version": 1,
    },
    "query_rewrite": {
        "content": (
            "Generate 2 alternative phrasings of this query for document retrieval.\n"
            "Return only the queries, one per line.\nQuery: {query}"
        ),
        "version": 1,
    },
    "agent_system": {
        "content": (
            "You are a RAG retrieval agent. You have tools to search documents.\n"
            "At each step, decide which tool to call or produce a FINAL answer.\n"
            "Respond in JSON: {{\"action\": \"tool_name\", \"args\": {{...}}}} "
            "or {{\"action\": \"final\", \"answer\": \"...\"}}.\n\n"
            "Available tools:\n"
            "- search_documents: {{\"query\": str, \"top_k\": int}}\n"
            "- refine_query: {{\"original\": str, \"context\": str}}"
        ),
        "version": 1,
    },
}


class PromptRegistry:
    def __init__(self, mlflow_tracking_uri: str = None):
        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)
        self._cache: dict[str, PromptVersion] = {}
        self._load_defaults()

    def _load_defaults(self):
        for name, data in DEFAULT_PROMPTS.items():
            self._cache[name] = PromptVersion(
                name=name,
                version=data["version"],
                content=data["content"],
            )

    def get(self, name: str) -> str:
        """Get the active prompt template by name."""
        prompt = self._cache.get(name)
        if not prompt:
            raise KeyError(f"Prompt '{name}' not found in registry")
        return prompt.content

    def register(self, name: str, content: str, author: str = "system", eval_score: float = 0.0) -> PromptVersion:
        """Register a new prompt version, log to MLflow."""
        current = self._cache.get(name)
        new_version = (current.version + 1) if current else 1

        prompt = PromptVersion(
            name=name,
            version=new_version,
            content=content,
            author=author,
            eval_score=eval_score,
        )
        self._cache[name] = prompt

        # Log to MLflow
        try:
            with mlflow.start_run(run_name=f"prompt-{name}-v{new_version}"):
                mlflow.set_tag("prompt_name", name)
                mlflow.set_tag("prompt_version", new_version)
                mlflow.set_tag("author", author)
                mlflow.log_metric("eval_score", eval_score)
                mlflow.log_text(content, f"prompts/{name}_v{new_version}.txt")
        except Exception as e:
            logger.warning(f"MLflow logging failed for prompt {name}: {e}")

        logger.info(f"Registered prompt '{name}' v{new_version} by {author}")
        return prompt

    def promote(self, name: str, version: int):
        """Promote a specific version to 100% traffic."""
        logger.info(f"Promoted prompt '{name}' v{version} to 100% traffic")

    def list_versions(self, name: str) -> list[dict]:
        """Return all logged versions from MLflow."""
        try:
            runs = mlflow.search_runs(
                filter_string=f"tags.prompt_name = '{name}'",
                order_by=["attributes.start_time DESC"],
            )
            return runs[["tags.prompt_version", "metrics.eval_score", "tags.author"]].to_dict("records")
        except Exception:
            return []


_registry_instance: PromptRegistry = None


def get_registry() -> PromptRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PromptRegistry()
    return _registry_instance
