"""
agents/entity_agent.py

Agent 2 — Entity Extraction Agent
Purpose : extract artists and entities
Input   : user query (str)
Output  : list[str] of artist names, VALIDATED against Neo4j

Two-stage design:
  1. Candidate extraction — Ollama pulls artist-name-shaped phrases out
     of free-form text (handles typos, partial names, "the guy who
     sang X" style references better than substring matching).
  2. Validation/resolution — every candidate is checked against the
     live Neo4j graph (exact case-insensitive match first, then a
     fuzzy match over the current artist roster). Nothing is ever
     hardcoded — get_all_artists() is queried fresh from Neo4j.

If the LLM step fails, we fall back to a deterministic substring match
against the live (not hardcoded) artist list, so the agent still works
offline.

TOKEN USAGE NOTE: same as agents/intent_agent.py — with_structured_output()
is built with include_raw=True so the raw AIMessage (and its token
counts) is reachable, and self.last_usage_metadata is what
monitoring/langsmith_tracer.py reads to report real token usage for
this agent's step on the Streamlit UI.
"""
from __future__ import annotations

from typing import List

from langsmith import traceable
from pydantic import BaseModel, Field

import config
from core.llm_client import get_ollama_llm
from tools.neo4j_tools import get_all_artists, resolve_artist_name
from utils.logger import logger


class ExtractedEntities(BaseModel):
    candidates: List[str] = Field(
        default_factory=list,
        description="Artist names mentioned in the query, exactly as the user wrote them.",
    )


_SYSTEM_PROMPT = """You are the Entity Extraction Agent in a music graph assistant.
Read the user's query and return every artist name mentioned in it.
Do not include song titles or record labels. Do not guess an artist
that is not actually mentioned. If no artist is mentioned, return an
empty list."""


class EntityAgent:

    def __init__(self):
        self._llm = get_ollama_llm(temperature=0.0)
        self._structured_llm = self._llm.with_structured_output(
            ExtractedEntities, include_raw=True
        )
        # Token usage from the most recent extract_and_validate() call.
        self.last_usage_metadata: dict = {}

    @traceable(name="entity_agent.extract_and_validate")
    def extract_and_validate(self, query: str) -> List[str]:
        candidates = self._extract_candidates(query)

        resolved: List[str] = []
        for candidate in candidates:
            match = resolve_artist_name(candidate, threshold=config.ENTITY_MATCH_THRESHOLD)
            if match and match not in resolved:
                resolved.append(match)

        logger.info(f"[EntityAgent] candidates={candidates} -> resolved(Neo4j-validated)={resolved}")
        return resolved

    def _extract_candidates(self, query: str) -> List[str]:
        self.last_usage_metadata = {}

        try:
            raw_result = self._structured_llm.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ]
            )

            if raw_result.get("parsing_error"):
                raise ValueError(f"structured output parsing failed: {raw_result['parsing_error']}")

            parsed: ExtractedEntities = raw_result["parsed"]
            raw_message = raw_result.get("raw")
            self.last_usage_metadata = getattr(raw_message, "usage_metadata", None) or {}

            return parsed.candidates or []

        except Exception as e:
            logger.warning(
                f"[EntityAgent] LLM extraction failed ({e}); "
                "falling back to substring match against the live graph."
            )
            self.last_usage_metadata = {}  # fallback made no LLM call -> 0 tokens
            known_artists = get_all_artists()  # still dynamic, never hardcoded
            q = query.lower()
            return [a for a in known_artists if a.lower() in q]