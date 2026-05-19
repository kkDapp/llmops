import asyncio
import logging
import google.generativeai as genai
from src.generation.prompts import build_prompt
from src.api.models import RAGStrategy, Source
from src.model_router.router import get_router, ModelTier
from config.settings import settings

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)


class GeminiClient:
    def __init__(self):
        self.flash = genai.GenerativeModel(settings.llm_model_flash)
        self.pro = genai.GenerativeModel(settings.llm_model_pro)
        self.router = get_router()

    async def generate(
        self,
        query: str,
        chunks: list[Source],
        strategy: RAGStrategy,
        force_tier: str = None,
    ) -> tuple[str, int, str]:
        """
        Generate an answer from retrieved chunks.
        Returns (answer, tokens_used, model_tier_used).
        """
        routing = self.router.route(query)
        tier = ModelTier(force_tier) if force_tier else routing.tier

        model = self._select_model(tier)
        prompt = build_prompt(query, chunks, strategy)
        config = genai.types.GenerationConfig(temperature=0.2, max_output_tokens=1024)

        response = await asyncio.to_thread(
            model.generate_content, prompt, generation_config=config
        )
        text = response.text
        tokens = response.usage_metadata.total_token_count if response.usage_metadata else 0
        logger.debug(
            f"Gemini: tier={tier.value}, strategy={strategy}, "
            f"tokens={tokens}, reason='{routing.reason}'"
        )
        return text, tokens, tier.value

    def _select_model(self, tier: ModelTier) -> genai.GenerativeModel:
        if tier == ModelTier.pro:
            return self.pro
        return self.flash

    async def generate_raw(self, prompt: str, max_tokens: int = 512) -> tuple[str, int]:
        """Direct prompt without context building — used internally by retrievers."""
        config = genai.types.GenerationConfig(temperature=0.1, max_output_tokens=max_tokens)
        response = await asyncio.to_thread(
            self.flash.generate_content, prompt, generation_config=config
        )
        tokens = response.usage_metadata.total_token_count if response.usage_metadata else 0
        return response.text, tokens
