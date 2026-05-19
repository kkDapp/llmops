"""
Verification layer — validates the generated answer against retrieved evidence.

Why this matters:
  LLMs hallucinate. Embeddings retrieve plausible but sometimes wrong context.
  Without verification, the system returns confident-sounding answers with no
  indication of how well they're grounded in retrieved documents.

What this does:
  1. Extracts factual claims from the generated answer
  2. Checks each claim against the retrieved chunks (in a single LLM call)
  3. Returns confidence_score (fraction of supported claims) + lists of
     supported and unsupported claims

Confidence score interpretation:
  1.00 → all claims supported by retrieved context
  0.75 → 3 of 4 claims supported, 1 hallucinated or not in context
  0.00 → answer not grounded in retrieved documents at all

Design decisions:
  - Single Gemini Flash call for all claim extraction + checking (not N+1 calls)
  - Graceful degradation: if parsing fails, returns confidence=1.0 (don't block)
  - Runs after generation, before cache store — verified answers are cached
"""
import json
import logging
import re
from dataclasses import dataclass, field
from src.api.models import Source

logger = logging.getLogger(__name__)

VERIFY_PROMPT_TEMPLATE = """You are a fact-checker for a RAG system. Given a question, an answer, and the retrieved context passages, identify which claims in the answer are supported vs unsupported by the context.

Question: {query}

Answer: {answer}

Context passages:
{context}

Instructions:
1. Extract specific factual claims from the answer (skip vague or hedged statements)
2. For each claim, check if it can be directly inferred from the context passages
3. Return ONLY a JSON object with this exact structure, no other text:

{{
  "supported_claims": ["exact claim text", ...],
  "unsupported_claims": ["exact claim text", ...]
}}"""


@dataclass
class VerificationResult:
    confidence_score: float
    supported_claims: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return {
            "confidence_score": self.confidence_score,
            "supported_claims": self.supported_claims,
            "unsupported_claims": self.unsupported_claims,
        }


class AnswerVerifier:
    """
    Verifies a generated answer against retrieved chunks.

    Single LLM call — extracts and checks all claims in one pass.
    Fails open (returns confidence=1.0) on any error so it never blocks
    request delivery.
    """

    def __init__(self):
        # Lazy import to avoid circular dependency at module load time
        self._gemini = None

    def _get_gemini(self):
        if self._gemini is None:
            from src.generation.gemini import GeminiClient
            self._gemini = GeminiClient()
        return self._gemini

    async def verify(self, query: str, answer: str, chunks: list[Source]) -> VerificationResult:
        if not chunks or not answer.strip():
            return VerificationResult(confidence_score=1.0)

        context = "\n---\n".join(
            f"[{i+1}] {c.text[:800]}" for i, c in enumerate(chunks[:8])
        )

        prompt = VERIFY_PROMPT_TEMPLATE.format(
            query=query[:500],
            answer=answer[:800],
            context=context,
        )

        try:
            gemini = self._get_gemini()
            # Gemini 2.5 Flash is a thinking model — internal reasoning tokens count
            # toward max_output_tokens. 8192 gives enough headroom for both.
            text, _ = await gemini.generate_raw(prompt, max_tokens=8192)
            return self._parse_result(text)
        except Exception as e:
            logger.warning(f"Verification failed (returning confidence=1.0): {e}")
            return VerificationResult(confidence_score=1.0)

    def _parse_result(self, text: str) -> VerificationResult:
        try:
            # Gemini often wraps JSON in ```json ... ``` fences — strip them
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```\s*$', '', cleaned).strip()

            # Find the outermost JSON object by scanning for matching braces
            start = cleaned.find('{')
            if start == -1:
                logger.warning(f"Verification: no JSON found | raw={text[:200]}")
                return VerificationResult(confidence_score=1.0)

            depth, end = 0, -1
            for i, ch in enumerate(cleaned[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

            if end == -1:
                logger.warning(f"Verification: JSON truncated by token limit | raw={text[:200]}")
                return VerificationResult(confidence_score=1.0)

            data = json.loads(cleaned[start:end + 1])
            supported = data.get("supported_claims", [])
            unsupported = data.get("unsupported_claims", [])

            total = len(supported) + len(unsupported)
            confidence = len(supported) / total if total > 0 else 1.0

            logger.debug(
                f"Verification: {len(supported)} supported, {len(unsupported)} unsupported, "
                f"confidence={confidence:.2f}"
            )
            return VerificationResult(
                confidence_score=round(confidence, 3),
                supported_claims=supported,
                unsupported_claims=unsupported,
            )
        except Exception as e:
            logger.warning(f"Verification parse failed: {e} | raw={text[:200]}")
            return VerificationResult(confidence_score=1.0)
