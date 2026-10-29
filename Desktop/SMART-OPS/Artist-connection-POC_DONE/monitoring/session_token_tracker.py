"""
monitoring/session_token_tracker.py

Session-level token tracking — separate from monitoring/langsmith_tracer.py
on purpose:

  - LangSmithTracer (existing) is PER-QUERY: a fresh instance is created
    for every call to SupervisorAgent.handle_query(), and its numbers
    reset with it. It answers "how much did THIS query cost".
  - SessionTokenTracker (this file) is PER-SESSION: one instance lives
    for as long as its owning SupervisorAgent instance does, and
    update_token_usage() accumulates into it across every query that
    instance handles. It answers "how much has this whole conversation
    cost so far".

ENFORCEMENT: check_token_limit() raises SessionTokenLimitExceededError
once the session's cumulative total_tokens reaches MAX_SESSION_TOKENS.
agents/supervisor_agent.py calls it before every graph (Neo4j) execution,
every agent execution, and every LLM call — see that file's
_traced_llm_step() and the explicit check before the neo4j_tool step.
Once it raises, nothing further runs for that query: no more agent
calls, no LLM calls, no Neo4j queries.

State shape (as specified):

    token_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

Public API (as specified): update_token_usage(), get_token_usage(),
reset_token_usage(), check_token_limit() — implemented as methods on
SessionTokenTracker rather than bare module-level functions, so each
SupervisorAgent instance (and, in tests, each test case) gets its own
independent session — a bare module-level global would leak token
counts (and false "limit exceeded" errors) between unrelated
sessions/tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, asdict

import config


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class SessionTokenLimitExceededError(RuntimeError):
    """Raised by SessionTokenTracker.check_token_limit() once the
    session's cumulative total_tokens has reached MAX_SESSION_TOKENS.
    Carries the numbers needed to build the required user-facing
    message without the caller having to re-fetch them."""

    def __init__(self, current_usage: int, limit: int):
        self.current_usage = current_usage
        self.limit = limit
        super().__init__(
            f"Session token limit exceeded ({current_usage}/{limit})."
        )


class SessionTokenTracker:
    """Accumulates token usage across an entire chat session.

    Thread-safety note: guarded by a lock so concurrent updates (e.g. a
    Streamlit rerun triggered mid-request in some deployment modes)
    can't interleave and corrupt the running totals. Each Streamlit
    user session gets its own instance (once wired into app.py), so
    this lock only ever protects a single user's own counters, never
    shares state across users.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage = TokenUsage()

    def update_token_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Add one LLM call's token counts onto the running session total.
        Called once per LLM call (see agents/supervisor_agent.py -- right
        after each of the intent/entity/explanation agent steps)."""
        with self._lock:
            self._usage.prompt_tokens += prompt_tokens
            self._usage.completion_tokens += completion_tokens
            self._usage.total_tokens += total_tokens

    def get_token_usage(self) -> dict:
        """Returns a snapshot dict -- a copy, not the live object, so the
        caller can't accidentally mutate internal state."""
        with self._lock:
            return asdict(self._usage)

    def reset_token_usage(self) -> None:
        """Zeroes out the running totals -- e.g. for a 'reset session' action."""
        with self._lock:
            self._usage = TokenUsage()

    def is_over_limit(self) -> bool:
        """Reports whether the session total has reached MAX_SESSION_TOKENS,
        without raising. Used internally by check_token_limit(); also
        handy for UI display logic later (e.g. a progress bar) without
        needing to catch an exception just to check a number."""
        with self._lock:
            return self._usage.total_tokens >= config.MAX_SESSION_TOKENS

    def check_token_limit(self) -> None:
        """Enforcement hook. Raises SessionTokenLimitExceededError if the
        session has reached MAX_SESSION_TOKENS; otherwise returns None
        and execution continues normally. Call this BEFORE — never
        after — any graph execution, agent execution, or LLM call, so a
        session that's already over budget never triggers another one
        of those in the first place."""
        with self._lock:
            total = self._usage.total_tokens
        if total >= config.MAX_SESSION_TOKENS:
            raise SessionTokenLimitExceededError(total, config.MAX_SESSION_TOKENS)