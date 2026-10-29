"""
agents/explanation_agent.py

Agent 3 — Explanation Agent
Purpose : generate the final, human-readable explanation
Input   : Neo4j results (+ query/intent/entities for context)
Output  : rich, ChatGPT-style natural-language explanation (str)

Output shape (every section is grounded in the facts passed in — see
_SYSTEM_PROMPT_TEMPLATE below for the exact contract given to the LLM):

    <one short lead-in paragraph>

    Key Insights:
    • ...
    • ...

    <intent-specific supporting data — connection chain / songs / labels / network>

    Summary:
    <one closing paragraph>

Ollama (llama3.1:8b) is prompted with the raw facts PLUS a deterministic
factual summary (from utils/narrator.py) as grounding, and told to
reshape that into the structure above without adding anything that
isn't already present. The deterministic summary is passed in
specifically so the model narrates rather than invents — it already
follows this exact structure, so the model's job is to make it read
more naturally, not to introduce new claims.

If Ollama is unavailable, or there are no facts to explain, the
deterministic Narrator text is returned as-is — it already matches the
required structure, so the app never drops back to a raw data dump.

TOKEN USAGE NOTE: self._llm.invoke(...) returns an AIMessage that DOES
carry .usage_metadata, but explain() only ever returned response.content
(a plain string) to its caller — discarding the AIMessage, and the
token counts along with it. We now stash usage_metadata on
self.last_usage_metadata BEFORE reducing the response down to text, so
monitoring/langsmith_tracer.py can still read it after the call
returns, even though the return value itself is just a str.
"""
from __future__ import annotations

import json
from typing import Any, List

from langsmith import traceable

import config
from core.llm_client import get_ollama_llm
from core.token_guardrails import TokenGuardRails
from utils.logger import logger
from utils.narrator import Narrator

_SYSTEM_PROMPT_TEMPLATE = """You are the Explanation Agent in a music-graph assistant.
You are given the user's question, the classified intent, the resolved
artist names, and FACTS pulled from a Neo4j graph database, plus a
baseline factual summary that already contains every true statement
you are allowed to make.

Rewrite the baseline into a clearer, more natural response, following
this exact structure:

1. Start with ONE short, concise lead-in paragraph (1-2 sentences)
   stating the connection in plain language.
2. Then a "Key Insights:" section with 2-5 bullet points ("• ") for the
   most important facts (degrees of separation, direct collaboration
   yes/no, number of shared songs, shared labels — whichever apply).
3. Then any relevant supporting data as its own labeled section
   (e.g. "Connection Chain:", "Songs Connecting These Artists:",
   "Shared Labels:") — only include a section if the facts contain
   that kind of data.
4. End with a "Summary:" section — one short closing paragraph.

Hard rules:
- Use no more than {max_words} words total.
- ONLY use information present in the FACTS or the baseline summary.
  Never invent, guess, or add an artist, song, year, label, or
  relationship that is not there. If something isn't in the facts,
  don't mention it.
- Do not contradict the baseline summary's facts — you may rephrase
  and reorganize them, not change them.
- If the facts are effectively empty, say plainly that no connection
  or data was found, and stop — don't pad with speculation."""


class ExplanationAgent:

    def __init__(self):
        self._llm = get_ollama_llm(temperature=0.4)
        # Token usage from the most recent explain() call.
        self.last_usage_metadata: dict = {}

    @traceable(name="explanation_agent.explain")
    def explain(
        self,
        query: str,
        intent: str,
        entities: List[str],
        facts: Any,
    ) -> str:
        self.last_usage_metadata = {}
        fallback_text = self._fallback_text(intent, facts, entities)

        if not self._has_data(intent, facts):
            return fallback_text

        try:
            system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
                max_words=config.MAX_RESPONSE_WORDS
            )
            user_content = (
                f"Question: {query}\n"
                f"Intent: {intent}\n"
                f"Artists: {entities}\n"
                f"Facts (JSON, this is the ONLY source of truth): "
                f"{json.dumps(facts, default=str)}\n\n"
                f"Baseline factual summary (rewrite this, don't contradict it):\n{fallback_text}"
            )
            response = self._llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]
            )

            # Capture usage BEFORE reducing the AIMessage down to plain
            # text below — this is the one line that was missing before.
            self.last_usage_metadata = getattr(response, "usage_metadata", None) or {}

            text = (response.content or "").strip()
            if not text:
                return fallback_text
            return TokenGuardRails.truncate_to_word_limit(text)

        except Exception as e:
            logger.warning(
                f"[ExplanationAgent] LLM narration failed ({e}); "
                "using deterministic templated fallback."
            )
            self.last_usage_metadata = {}  # fallback made no LLM call -> 0 tokens
            return fallback_text

    @staticmethod
    def _has_data(intent: str, facts: Any) -> bool:
        if intent == "direct_connection":
            return facts is not None  # facts is a bool here; False is valid data
        return bool(facts)

    @staticmethod
    def _fallback_text(intent: str, facts: Any, entities: List[str]) -> str:
        if intent == "connection_path":
            return Narrator.format_connection_bundle(facts)
        if intent == "bridging_song":
            return Narrator.format_bridging_song(facts)
        if intent == "collaboration_network":
            return Narrator.format_network(facts)
        if intent == "label_mates":
            return Narrator.format_label_mates(facts)
        if intent == "graph_statistics":
            return Narrator.format_graph_statistics(facts)
        if intent == "direct_connection":
            return Narrator.format_direct_connection(facts, entities)
        return "No explanation available for this query."