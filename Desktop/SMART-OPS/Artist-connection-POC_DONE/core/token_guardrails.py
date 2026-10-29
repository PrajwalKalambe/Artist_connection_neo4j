"""
core/token_guardrails.py

it's now backed by config.py
(which reads from .env) so limits are tunable per environment without
editing code, and adds a couple of small enforcement helpers used by
the monitoring layer and the Explanation Agent.
"""
from config import (
    MAX_TOOL_CALLS,
    MAX_RESPONSE_WORDS,
    ALLOWED_DOMAINS,
)

# Re-exported for backward compatibility with any code/tests that
# imported these names directly from this module.
__all__ = [
    "MAX_TOOL_CALLS",
    "MAX_RESPONSE_WORDS",
    "ALLOWED_DOMAINS",
    "TokenGuardRails",
]


class TokenGuardRails:

    @staticmethod
    def is_within_tool_call_budget(tool_calls_made: int) -> bool:
        return tool_calls_made <= MAX_TOOL_CALLS

    @staticmethod
    def truncate_to_word_limit(text: str, limit: int = MAX_RESPONSE_WORDS) -> str:
        words = text.split()
        if len(words) <= limit:
            return text
        return " ".join(words[:limit]) + " …"

    @staticmethod
    def is_in_domain(query: str) -> bool:
        q = query.lower()
        return any(keyword in q for keyword in ALLOWED_DOMAINS)
