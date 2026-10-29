"""
agents/supervisor_agent.py

Supervisor Agent — the only agent app.py / routes talk to directly.

Responsibilities (in order, matching the requirement list exactly):
  1. Call Kill Switch        -> short-circuits everything below if active
  2. Call Intent Agent
  3. Call Entity Agent
  4. Execute Neo4j Tool
  5. Call Explanation Agent
  6. Return final response

Every step is wrapped by LangSmithTracer.trace_step so latency, token
usage, cost, and failures are captured per-step regardless of whether
LangSmith itself is configured.

SESSION TOKEN TRACKING & ENFORCEMENT: in addition to LangSmithTracer's
per-query numbers, self.session_tracker (a SessionTokenTracker)
accumulates token usage across every query this SupervisorAgent
instance handles, for as long as that instance is alive. Before every
graph (Neo4j) execution, every agent execution, and every LLM call,
self.session_tracker.check_token_limit() is called -- once the session
total reaches MAX_SESSION_TOKENS, it raises SessionTokenLimitExceededError,
which handle_query() catches and turns into the required "Session token
limit exceeded" message, WITHOUT running whatever step was about to
happen (or anything after it). See monitoring/session_token_tracker.py
for the tracker itself.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from agents.entity_agent import EntityAgent
from agents.explanation_agent import ExplanationAgent
from agents.intent_agent import IntentAgent
from core.guardrails import GuardRails
from core.kill_switch import KillSwitch, KillSwitchActiveError
from monitoring.langsmith_tracer import LangSmithTracer
from monitoring.session_token_tracker import (
    SessionTokenLimitExceededError,
    SessionTokenTracker,
)
import streamlit as st
from tools import neo4j_tools
from utils.logger import logger

SUPPORTED_QUERIES_MESSAGE = (
    "Unsupported query.\n\nSupported queries are:\n"
    "- How is Artist A connected to Artist B?\n"
    "- Are Artist A and Artist B directly connected?\n"
    "- What song connects Artist A and Artist B?\n"
    "- Show collaboration network of Artist\n"
    "- Show label mates of Artist\n"
    "- Show graph statistics"
)

# intent -> (tool function, number of resolved entities it needs)
_TOOL_MAP = {
    "direct_connection": (neo4j_tools.check_direct_connection, 2),
    # connection_path now pulls a COMBINED bundle (path + direct-collab
    # flag + bridging songs along every hop + shared labels) in one
    # Neo4j session, instead of just the bare shortest-path chain.
    "connection_path": (neo4j_tools.get_connection_bundle, 2),
    "bridging_song": (neo4j_tools.get_bridging_song, 2),
    "collaboration_network": (neo4j_tools.get_collaboration_network, 1),
    "label_mates": (neo4j_tools.get_label_mates, 1),
    "graph_statistics": (neo4j_tools.get_graph_statistics, 0),
}

# Steps in _TOOL_MAP-adjacent pipeline that actually call an LLM -- this
# is the set LangSmithTracer.trace_step results get folded into
# session_tracker after. "neo4j_tool" is deliberately excluded: a
# database call has no tokens.
_LLM_STEP_NAMES = {"intent_agent", "entity_agent", "explanation_agent"}


class _UnsupportedIntentError(Exception):
    pass


class _MissingEntitiesError(Exception):
    pass


class SupervisorAgent:

    def __init__(self):
        self.intent_agent = IntentAgent()
        self.entity_agent = EntityAgent()
        self.explanation_agent = ExplanationAgent()
        # One tracker per SupervisorAgent instance, reused across every
        # query that instance handles -- this is what makes it
        # session-level rather than per-query. See this module's
        # docstring and monitoring/session_token_tracker.py for the
        # current caveat: this only accumulates for as long as THIS
        # instance stays alive (Streamlit UI wiring to persist it across
        # reruns is a separate, later change).
        

        if "token_tracker" not in st.session_state:
            st.session_state.token_tracker = SessionTokenTracker()
        if "conversation_entities" not in st.session_state:
            st.session_state.conversation_entities = []

        if "last_artist" not in st.session_state:
            st.session_state.last_artist = None

        if "last_artists" not in st.session_state:
            st.session_state.last_artists = []

        if "last_query_type" not in st.session_state:
            st.session_state.last_query_type = None

        if "conversation_summary" not in st.session_state:
            st.session_state.conversation_summary = ""

        if "last_collaborators" not in st.session_state:
            st.session_state.last_collaborators = []

        self.session_tracker = st.session_state.token_tracker

    def handle_query(self, query: str) -> Dict[str, Any]:
        tracer = LangSmithTracer()
        start = time.perf_counter()

        # 1. KILL SWITCH — must be checked before any AI processing.
        try:
            KillSwitch.enforce()
        except KillSwitchActiveError as e:
            logger.critical(f"[Supervisor] Blocked by kill switch: {e}")
            return self._build_response(str(e), "blocked", tracer, start)

        # Guardrails (cheap, non-AI validation) — fine to run right after.
        try:
            GuardRails.validate_user_input(query)
        except ValueError as e:
            return self._build_response(str(e), "rejected", tracer, start)

        query = self._resolve_context(query)

        try:
            # 2. INTENT AGENT
            intent_result = self._traced_llm_step(
                tracer, "intent_agent", self.intent_agent.classify, query
            )
            intent = intent_result.intent

            # 3. ENTITY AGENT (Neo4j-validated)
            entities: List[str] = self._traced_llm_step(
                tracer, "entity_agent", self.entity_agent.extract_and_validate, query
            )
            self._update_memory(entities,intent)

            # 4. NEO4J TOOL EXECUTION
            self.session_tracker.check_token_limit()  # before graph execution
            facts = tracer.trace_step(
                "neo4j_tool", self._execute_tool, intent, entities
            )
            if (
    intent == "collaboration_network"
    and isinstance(facts, list)
):
                collaborators = []

                for row in facts:
                    artist = row.get("artist")

                    if artist:
                        collaborators.append(artist)

                st.session_state.last_collaborators = collaborators

            # 5. EXPLANATION AGENT
            explanation = self._traced_llm_step(
                tracer, "explanation_agent",
                self.explanation_agent.explain,
                query, intent, entities, facts,
            )

            # 6. RETURN FINAL RESPONSE
            return self._build_response(
                explanation, "success", tracer, start,
                intent=intent, entities=entities, facts=facts,
            )

        except _UnsupportedIntentError:
            return self._build_response(SUPPORTED_QUERIES_MESSAGE, "unsupported", tracer, start)

        except _MissingEntitiesError as e:
            return self._build_response(str(e), "needs_clarification", tracer, start)

        except SessionTokenLimitExceededError as e:
            logger.critical(
                f"[Supervisor] Session token limit exceeded: "
                f"{e.current_usage}/{e.limit} — stopping before any further "
                "agent/graph/LLM execution."
            )
            return self._build_response(
                self._token_limit_message(e.current_usage, e.limit),
                "token_limit_exceeded", tracer, start,
            )

        except Exception as e:
            logger.exception(f"[Supervisor] Unhandled failure: {e}")
            return self._build_response(
                "Something went wrong while exploring the graph. "
                "Please try rephrasing your question.",
                "error", tracer, start,
            )

    # ------------------------------------------------------------------
    def _traced_llm_step(self, tracer: LangSmithTracer, name: str, fn, *args) -> Any:
        """Runs one LLM-calling pipeline step through the per-query tracer
        (as before), THEN folds that step's token usage into the
        session-level tracker. This is the single hook point for both
        "collect token usage after every LLM call" AND "check the token
        limit before every agent execution / LLM call" -- every agent
        call in the pipeline goes through this method, so neither can be
        skipped. check_token_limit() runs FIRST, before fn() is called at
        all, so once the session is over budget this agent (and its LLM
        call) never runs."""
        self.session_tracker.check_token_limit()  # before agent execution / LLM call
        result = tracer.trace_step(name, fn, *args)

        metric = tracer.metrics[-1]  # the step we just ran, always last
        assert metric.name == name  # sanity check — trace_step appends in order
        self.session_tracker.update_token_usage(
            prompt_tokens=metric.input_tokens,
            completion_tokens=metric.output_tokens,
            total_tokens=metric.total_tokens,
        )
        return result

    def _execute_tool(self, intent: str, entities: List[str]) -> Any:
        tool = _TOOL_MAP.get(intent)
        if not tool:
            raise _UnsupportedIntentError(intent)

        fn, required = tool
        if len(entities) < required:
            recognized = ", ".join(entities) if entities else "none"
            raise _MissingEntitiesError(
                f"I need {required} artist name(s) I can find in the graph to "
                f"answer that (recognized: {recognized}). Could you check the "
                "spelling or try a different artist?"
            )

        args = entities[:required]
        return fn(*args)

    @staticmethod
    def _token_limit_message(current_usage: int, limit: int) -> str:
        return (
            "Session token limit exceeded.\n\n"
            f"Current Usage: {current_usage} / {limit} tokens\n\n"
            "Please start a new chat session or reset the conversation."
        )

    def _build_response(
        self, text: str, status: str, tracer: LangSmithTracer, start: float, **extra
    ) -> Dict[str, Any]:
        return {
            "response": text,
            "status": status,
            "latency_ms": (time.perf_counter() - start) * 1000,
            "trace": tracer.summary(),
            "total_tokens": tracer.total_tokens(),
            "total_cost_usd": tracer.total_cost_usd(),
            "had_failure": tracer.had_failure(),
            # Session-level (cumulative across every query this
            # SupervisorAgent instance has handled), not just this query.
            "session_token_usage": self.session_tracker.get_token_usage(),
            **extra,
        }

    
    def _resolve_context(self, query: str) -> str:

        q = query.lower()

        last_artist = st.session_state.get("last_artist")

        if last_artist:

            replacements = [
                " him ",
                " he ",
                " his ",
                " her ",
                " she ",
                " that artist ",
                " this artist ",
                " previous artist ",
                " previous singer ",
                " that singer "
            ]

            modified = f" {q} "

            for token in replacements:
                modified = modified.replace(
                    token,
                    f" {last_artist} "
                )

            query = modified.strip()

        return query
    def _update_memory(
    self,
    entities,
    intent
):

        if entities:

            st.session_state.last_artist = entities[0]

            st.session_state.last_artists = entities

            existing = st.session_state.conversation_entities

            for entity in entities:
                if entity not in existing:
                    existing.append(entity)

            st.session_state.conversation_entities = existing

        st.session_state.last_query_type = intent