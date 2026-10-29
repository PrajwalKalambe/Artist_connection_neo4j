# Architecture — Artist Connection Explorer (v2, Multi-Agent)



## 2. New component diagram

```
                                   ┌─────────────────────────┐
                                   │        Streamlit UI      │
                                   │         (app.py)         │
                                   └────────────┬──────────────┘
                                                │ query (str)
                                                ▼
                                   ┌─────────────────────────┐
                                   │       ArtistRouter        │
                                   │   (routes/artist_routes)  │
                                   └────────────┬──────────────┘
                                                │
                                                ▼
                          ┌───────────────────────────────────────┐
                          │            SUPERVISOR AGENT             │
                          │        (agents/supervisor_agent)        │
                          │                                          │
                          │  1. KillSwitch.enforce()  ───────────┐   │
                          │  2. GuardRails.validate_user_input()  │  │
                          │  3. IntentAgent.classify()            │  │
                          │  4. EntityAgent.extract_and_validate()│  │
                          │  5. Neo4j tool dispatch                │  │
                          │  6. ExplanationAgent.explain()         │  │
                          │  7. build_response()                   │  │
                          └───────────────┬────────────────────────┘  │
                                          │                            │
        ┌─────────────────────┬──────────┼───────────┬────────────┐   │
        ▼                     ▼          ▼           ▼            │   │
┌───────────────┐   ┌──────────────┐  ┌────────┐ ┌──────────────┐ │   │
│  Kill Switch    │   │ Intent Agent │  │ Entity │ │ Explanation  │ │   │
│ (core/kill_     │   │ (Ollama LLM, │  │ Agent  │ │ Agent        │ │   │
│  switch.py)     │   │ rule fallback│  │(Ollama │ │(Ollama, rich │ │   │
│                 │   │)             │  │+Neo4j  │ │ narration,   │ │   │
│ .env flag OR    │   │              │  │valid.) │ │ Narrator     │ │   │
│ KILL_SWITCH.flag│   └──────────────┘  └───┬────┘ │ fallback)    │ │   │
└─────────────────┘                          │      └──────────────┘ │
                                              ▼                       │
                                     ┌──────────────────┐             │
                                     │  Neo4j Tool Layer │◄────────────┘
                                     │ (tools/neo4j_tools)│  every tool call
                                     └─────────┬──────────┘  and every agent
                                              │             call is wrapped
                                              ▼             by LangSmithTracer
                                     ┌──────────────────┐
                                     │   Neo4j Database   │
                                     └────────────────────┘

Cross-cutting: monitoring/langsmith_tracer.py wraps every step above with
timing + token/cost capture, and (when LANGCHAIN_TRACING_V2=true) every
agent method is also decorated with @traceable so LangSmith gets the
full nested run tree.
```

## 3. The 3 required agents + the Supervisor

| Agent | File | Input | Output | Uses Ollama? |
|---|---|---|---|---|
| Intent Agent | `agents/intent_agent.py` | raw query | `IntentClassification` (intent, confidence, reasoning) | Yes — structured output; rule-based fallback only on LLM failure |
| Entity Extraction Agent | `agents/entity_agent.py` | raw query | `list[str]` of **Neo4j-validated** artist names | Yes — structured output for candidates; validation is 100% Neo4j (fuzzy + exact) |
| Explanation Agent | `agents/explanation_agent.py` | intent + entities + Neo4j facts | rich natural-language explanation | Yes — free-text generation grounded in the facts; deterministic `Narrator` fallback |
| **Supervisor Agent** | `agents/supervisor_agent.py` | raw query | final response dict | Orchestrates the three above; does not call Ollama itself |

This satisfies "minimum 3 agents" with clean single-responsibility
boundaries and a Supervisor that owns orchestration only (no business
logic of its own beyond dispatch).

## 4. Kill Switch design

Two independent activation paths, both fail-closed:
1. **`.env`**: `KILL_SWITCH_ENABLED=true` — re-read on every request
   (not cached at import time), so toggling it takes effect on the
   very next query without a restart.
2. **Runtime flag file**: `KILL_SWITCH.flag` in the project root.
   Lets an operator (or an external monitoring script) trip the
   switch by touching a file — no deploy/`.env` access required. This
   is the common enterprise "big red button" pattern.

`SupervisorAgent.handle_query()` calls `KillSwitch.enforce()` as its
**very first line** — if it's active, no Intent/Entity/Explanation
agent and no Ollama call ever happens for that request.

## 5. LangSmith / monitoring design

Two layers (see `monitoring/langsmith_tracer.py` docstring for the
exact code):
1. `@traceable` decorators on every agent method → full LangSmith run
   tree when `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` is set.
2. `LangSmithTracer` (local) → per-step latency, token usage (read
   from `AIMessage.usage_metadata`), estimated cost, and failure
   status — always available, even with LangSmith unconfigured. Shown
   live in the Streamlit sidebar ("Last Query Monitor").

## 6. Why explanations are richer now

The old `Narrator` only ever printed the raw graph shape
(`Degrees of Separation: 1 / A → B`). Two upgrades fixed this:

**a) Combined data fetch.** `tools/neo4j_tools.get_connection_bundle()`
replaces the bare `find_connection_path()` call for `connection_path`
queries. In one Neo4j session it now also pulls: a direct-collaboration
flag, every bridging song along each hop of the shortest path
(deduplicated, and only for artist pairs actually on the path — not
the whole graph), and any shared record labels. See
`docs/DATA_FLOW.md` for the full query strategy.

**b) ChatGPT-style structured narration.** `utils/narrator.py` turns
that bundle into: a one-line lead paragraph → a "Key Insights:" bullet
list → supporting-data sections (Connection Chain / Songs / Shared
Labels, each only shown if present) → a closing "Summary:". The
`ExplanationAgent`:
1. Always computes that deterministic structured text first — this is
   the ground truth and the required output shape.
2. Passes it, plus the raw JSON facts, to Ollama with an explicit
   instruction to *rewrite* it into more natural language while
   preserving that exact structure and never adding a fact that isn't
   in the JSON.
3. Falls back to step 1's text verbatim if Ollama is unreachable or
   there are no facts to explain — so the required structure is
   guaranteed either way, LLM or no LLM.

## 7. Enterprise-readiness checklist

- ✅ Kill switch (dual-path, fail-closed)
- ✅ Structured, typed agent I/O (Pydantic schemas)
- ✅ Graceful degradation at every LLM call site (never a hard crash)
- ✅ Centralized config (`config.py`) — no scattered `os.getenv` calls
- ✅ Full observability (LangSmith + local tracer) with token/cost/
  latency/failure capture
- ✅ Zero hardcoded artists/songs/labels — everything from Neo4j
- ✅ Unit tests for kill switch, all 3 agents, and the Supervisor,
  fully mocked (no live services needed in CI)
