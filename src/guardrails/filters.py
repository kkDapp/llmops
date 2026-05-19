import re
import logging

logger = logging.getLogger(__name__)

BLOCKED_PATTERNS = [
    r"ignore previous instructions",
    r"disregard.*system prompt",
    r"jailbreak",
    r"<script",
    r"DROP TABLE",
    r"rm -rf",
]

PII_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
}


class GuardrailFilter:
    def check_input(self, query: str) -> str | None:
        """Returns error message if query is blocked, else None."""
        lower = query.lower()
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, lower, re.IGNORECASE):
                logger.warning(f"Blocked query pattern: {pattern}")
                return f"Query contains disallowed content."

        if len(query) > 2000:
            return "Query too long (max 2000 characters)."

        return None

    def check_output(self, answer: str) -> str:
        """Redact PII from generated answers."""
        for pii_type, pattern in PII_PATTERNS.items():
            count = len(re.findall(pattern, answer))
            if count > 0:
                answer = re.sub(pattern, f"[REDACTED {pii_type.upper()}]", answer)
                logger.warning(f"Redacted {count} {pii_type} patterns from output")
        return answer
