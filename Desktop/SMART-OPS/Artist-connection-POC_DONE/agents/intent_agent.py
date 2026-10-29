"""
agents/intent_agent.py

Agent 1 — Intent Agent
Purpose : determine user intent
Input   : user natural language query (str)
Output  : IntentClassification (structured: intent, confidence, reasoning)

Primary path uses Ollama (llama3.1:8b) via LangChain's structured
output so the model itself does the reasoning, instead of brittle
keyword matching. A deterministic rule-based fallback kicks in only if
the LLM call raises (e.g. Ollama unreachable, kill switch tripped
elsewhere in-process) so the pipeline degrades gracefully rather than
crashing.

TOKEN USAGE NOTE: with_structured_output() normally throws away the
raw LLM response (and its token counts) and only returns the parsed
object. We build it with include_raw=True instead, so invoke() returns
{"raw": AIMessage, "parsed": IntentClassification, "parsing_error": ...}
and we can pull real input/output/total token counts off `raw`. Those
are stashed on self.last_usage_metadata, which
monitoring/langsmith_tracer.py reads after calling this agent — that's
what makes the token counts on the Streamlit UI non-zero.
"""
from __future__ import annotations

from typing import Literal

from langsmith import traceable
from pydantic import BaseModel, Field

from core.llm_client import get_ollama_llm
from utils.logger import logger

IntentLabel = Literal[
    "direct_connection",
    "connection_path",
    "bridging_song",
    "collaboration_network",
    "label_mates",
    "graph_statistics",
    "unknown",
]


class IntentClassification(BaseModel):
    intent: IntentLabel = Field(description="Single best-matching intent label.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification.")
    reasoning: str = Field(description="One short sentence explaining the choice.")


_SYSTEM_PROMPT = """You are the Intent Agent inside a multi-agent music graph assistant.
Classify the user's question into exactly one of these intents:

- direct_connection: asks WHETHER two artists collaborated directly (yes/no question).
- connection_path: asks HOW two artists are connected / the path / degrees of separation.
- bridging_song: asks WHICH SONG connects two artists.
- collaboration_network: asks about one artist's collaborators / network / who they've worked with.
- label_mates: asks about artists on the same record label.
- graph_statistics: asks about the size or totals of the dataset/graph itself.
- unknown: anything else, or a question that isn't about artist relationships.

Base your answer only on the wording of the query. Do not invent artist names."""


class IntentAgent:

    def __init__(self):
        self._llm = get_ollama_llm(temperature=0.0)
        # include_raw=True is what makes the AIMessage (and its token
        # usage) reachable at all — without it, LangChain silently
        # drops the raw response and we can never see token counts.
        self._structured_llm = self._llm.with_structured_output(
            IntentClassification, include_raw=True
        )
        # Token usage from the most recent classify() call. Read by
        # monitoring/langsmith_tracer.py via getattr(fn.__self__, "last_usage_metadata").
        self.last_usage_metadata: dict = {}

    @traceable(name="intent_agent.classify")
    def classify(self, query: str) -> IntentClassification:
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

            parsed: IntentClassification = raw_result["parsed"]
            raw_message = raw_result.get("raw")
            self.last_usage_metadata = getattr(raw_message, "usage_metadata", None) or {}

            logger.info(
                f"[IntentAgent] LLM classified '{query[:60]}...' -> "
                f"{parsed.intent} (confidence={parsed.confidence:.2f}, "
                f"tokens={self.last_usage_metadata.get('total_tokens', 0)})"
            )
            return parsed

        except Exception as e:
            logger.warning(
                f"[IntentAgent] LLM classification failed ({e}); "
                "falling back to rule-based classifier."
            )
            self.last_usage_metadata = {}  # fallback made no LLM call -> 0 tokens
            return self._rule_based_fallback(query)

    @staticmethod
    def _rule_based_fallback(query: str) -> IntentClassification:
        q = query.lower()

        if "label" in q:
            intent: IntentLabel = "label_mates"
        elif "network" in q or ("collaborat" in q and "song" not in q):
            intent = "collaboration_network"
        elif "song" in q:
            intent = "bridging_song"
        elif "direct" in q:
            intent = "direct_connection"
        elif any(k in q for k in ("connected", "connection", "path", "degrees")):
            intent = "connection_path"
        elif any(k in q for k in ("statistics", "graph", "dataset", "how many")):
            intent = "graph_statistics"
        else:
            intent = "unknown"

        return IntentClassification(
            intent=intent,
            confidence=0.4,
            reasoning="rule-based fallback (LLM unavailable)",
        )