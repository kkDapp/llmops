"""
Model Router — selects the right LLM tier per query.

Tier 1: Gemini Flash    → simple factual queries   ($0.075/1M tokens)
Tier 2: Gemini Pro      → analytical, multi-step   ($3.50/1M tokens)
Tier 3: Fine-tuned LoRA → domain-specific queries  (self-hosted vLLM)

Routing keeps quality high and cost low — Pro is 46× more expensive than Flash.
Sending every query to Pro would be wasteful; sending complex queries to Flash
degrades quality. The router balances both.
"""
import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    flash = "flash"          # Gemini 1.5 Flash — fast, cheap
    pro = "pro"              # Gemini 1.5 Pro — capable, expensive
    fine_tuned = "fine_tuned"  # LoRA adapter on vLLM — domain-specific


@dataclass
class RoutingDecision:
    tier: ModelTier
    reason: str
    estimated_cost_multiplier: float  # relative to Flash = 1.0


ANALYTICAL_PATTERNS = [
    r"\banalyze\b", r"\banalyse\b", r"\bcompare\b", r"\bexplain why\b",
    r"\bwhat are the implications\b", r"\bsummarize\b", r"\bpros and cons\b",
    r"\bhow does .+ relate\b", r"\bwhat would happen if\b", r"\bcritically\b",
    r"\bbreakdown\b", r"\bbreak down\b", r"\bdiffer\b", r"\bevaluate\b",
]

DOMAIN_KEYWORDS: set[str] = set()  # populated from Prompt Registry at startup


class ModelRouter:
    def __init__(self, domain_keywords: set[str] = None, fine_tuned_available: bool = False):
        self.domain_keywords = domain_keywords or DOMAIN_KEYWORDS
        self.fine_tuned_available = fine_tuned_available

    def route(self, query: str) -> RoutingDecision:
        query_lower = query.lower().strip()

        # Rule 1: domain-specific fine-tuned model (highest priority if available)
        if self.fine_tuned_available and self._is_domain_specific(query_lower):
            return RoutingDecision(
                tier=ModelTier.fine_tuned,
                reason="query matches domain-specific fine-tuned vocabulary",
                estimated_cost_multiplier=0.5,  # self-hosted = cheaper than API
            )

        # Rule 2: analytical/complex → Pro
        if self._is_analytical(query_lower) or self._is_complex(query_lower):
            return RoutingDecision(
                tier=ModelTier.pro,
                reason="analytical or multi-hop query detected",
                estimated_cost_multiplier=46.0,
            )

        # Rule 3: default to Flash
        return RoutingDecision(
            tier=ModelTier.flash,
            reason="simple factual query",
            estimated_cost_multiplier=1.0,
        )

    def _is_analytical(self, query: str) -> bool:
        return any(re.search(p, query, re.IGNORECASE) for p in ANALYTICAL_PATTERNS)

    def _is_complex(self, query: str) -> bool:
        word_count = len(query.split())
        has_multiple_questions = query.count("?") > 1
        has_conjunctions = any(w in query for w in ["and also", "additionally", "furthermore", "moreover"])
        return word_count > 40 or has_multiple_questions or has_conjunctions

    def _is_domain_specific(self, query: str) -> bool:
        if not self.domain_keywords:
            return False
        query_words = set(query.split())
        overlap = query_words & self.domain_keywords
        return len(overlap) >= 2  # at least 2 domain keywords


_router_instance: ModelRouter = None


def get_router() -> ModelRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
