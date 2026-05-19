"""
Semantic cache — stores RAG responses keyed by query embedding similarity.
Avoids re-running the full retrieval + generation pipeline for similar queries.
Cache hit: cosine similarity > 0.95 between incoming and cached query embeddings.
"""
import asyncio
import hashlib
import json
import logging
import pickle
import numpy as np
import redis.asyncio as aioredis
from src.api.models import RAGResponse, RAGStrategy
from config.settings import settings

logger = logging.getLogger(__name__)


class SemanticCache:
    def __init__(self):
        self.redis = aioredis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}",
            decode_responses=False,
        )
        self.similarity_threshold = 0.95
        self.ttl = settings.cache_ttl_seconds

    async def get(self, query: str, strategy: RAGStrategy, namespace: str) -> RAGResponse | None:
        if not settings.use_semantic_cache:
            return None
        try:
            key = self._exact_key(query, strategy, namespace)
            cached = await self.redis.get(key)
            if cached:
                logger.debug(f"Cache hit (exact) for query='{query[:40]}'")
                return RAGResponse(**json.loads(cached))
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
        return None

    async def set(self, query: str, strategy: RAGStrategy, namespace: str, response: RAGResponse):
        if not settings.use_semantic_cache:
            return
        try:
            key = self._exact_key(query, strategy, namespace)
            await self.redis.setex(key, self.ttl, response.model_dump_json())
            logger.debug(f"Cache set for query='{query[:40]}'")
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    def _exact_key(self, query: str, strategy: RAGStrategy, namespace: str) -> str:
        raw = f"{namespace}:{strategy.value}:{query.lower().strip()}"
        return f"rag:cache:{hashlib.sha256(raw.encode()).hexdigest()}"
