# File-by-File Implementation Plan

## Final folder structure

```
Artist-connection-exploror/
├── .env                          # your real config (gitignored)
├── .env.example                  # sanitized template
├── .gitignore
├── readme.md
├── requirements.txt
├── app.py                        # Streamlit UI
├── config.py                     # centralized env-driven config
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py       # orchestrator
│   ├── intent_agent.py           # Agent 1
│   ├── entity_agent.py           # Agent 2
│   └── explanation_agent.py      # Agent 3
├── core/
│   ├── __init__.py
│   ├── kill_switch.py            # enterprise kill switch
│   ├── guardrails.py             # input validation (renamed, typo fixed)
│   ├── token_guardrails.py       # tool-call/response limits (renamed, typo fixed)
│   └── llm_client.py             # shared Ollama client factory
├── tools/
│   ├── __init__.py
│   └── neo4j_tools.py            # the only file that talks to Neo4j
├── monitoring/
│   ├── __init__.py
│   └── langsmith_tracer.py       # LangSmith + local token/latency/cost tracing
├── routes/
│   ├── __init__.py
│   └── artist_routes.py          # thin entry point for app.py
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   └── narrator.py               # deterministic fallback formatter
├── tests/
│   ├── __init__.py
│   ├── test_connection.py        # raw Neo4j smoke test (manual)
│   ├── test_router.py            # full pipeline smoke test (manual, needs live services)
│   ├── test_kill_switch.py       # pytest, mocked, CI-safe
│   ├── test_agents.py            # pytest, mocked, CI-safe
│   └── test_supervisor.py        # pytest, mocked, CI-safe
└── docs/
    ├── ARCHITECTURE.md
    ├── DATA_FLOW.md
    ├── AGENT_INTERACTION.md
    └── FILE_PLAN.md              # this file
```



## Files merged

| Old | New home |
|---|---|
| `utils/artist_resolver.py` (substring-only matcher) | Logic absorbed into `agents/entity_agent.py`'s fallback path (`_extract_candidates`'s except-branch) and `tools/neo4j_tools.resolve_artist_name` for the validated path. Not kept as a standalone file — it had a single responsibility that now lives with the agent that owns it. |

## Files added

| File | Purpose |
|---|---|
| `agents/supervisor_agent.py` | Orchestrator — kill switch, pipeline order, error translation, response assembly. |
| `agents/intent_agent.py` | Agent 1 — LLM intent classification + fallback. |
| `agents/entity_agent.py` | Agent 2 — LLM entity extraction + Neo4j validation. |
| `agents/explanation_agent.py` | Agent 3 — LLM narration grounded in Neo4j facts. |
| `core/kill_switch.py` | Enterprise kill switch (`.env` + runtime flag file). |
| `core/llm_client.py` | Shared, cached `ChatOllama` factory. |
| `monitoring/langsmith_tracer.py` | LangSmith wiring reference + local step tracer (latency/tokens/cost/failures). |
| `.env.example` | Safe-to-commit config template. |
| `.gitignore` | Keeps `venv/`, `.env`, `KILL_SWITCH.flag`, caches out of version control. |
| `tests/test_kill_switch.py`, `tests/test_agents.py`, `tests/test_supervisor.py` | CI-safe, fully mocked unit tests. |
| `docs/*.md` | This documentation set. |

## Files unchanged (kept as-is or with only import-path touch-ups)

- `utils/logger.py` — unchanged.
- `tests/test_connection.py` — unchanged (manual Neo4j smoke test).
- `readme.md` — rewritten to describe the new architecture (content below).

## Per-file purpose / inputs / outputs / dependencies

### `config.py`
- **Purpose**: single source of truth for every `.env`-driven setting.
- **Inputs**: `.env` file (via `python-dotenv`).
- **Outputs**: module-level constants (`OLLAMA_MODEL`, `NEO4J_URI`, `KILL_SWITCH_ENABLED`, etc.).
- **Depends on**: `python-dotenv`.

### `core/kill_switch.py`
- **Purpose**: block all AI processing immediately, from `.env` or a runtime flag file.
- **Inputs**: `.env`'s `KILL_SWITCH_ENABLED`, presence of `KILL_SWITCH.flag`.
- **Outputs**: `KillSwitch.is_active() -> bool`, `KillSwitch.enforce()` raises `KillSwitchActiveError`.
- **Depends on**: `python-dotenv`, `utils/logger.py`.

### `core/guardrails.py`
- **Purpose**: validate raw user input before it reaches any agent.
- **Inputs**: `query: str`.
- **Outputs**: `True` or raises `ValueError`.
- **Depends on**: `config.py`.

### `core/token_guardrails.py`
- **Purpose**: tool-call budget + response length + domain-relevance helpers.
- **Inputs**: various (tool call counts, text, query).
- **Outputs**: bools / truncated text.
- **Depends on**: `config.py`.

### `core/llm_client.py`
- **Purpose**: construct (and cache) the shared `ChatOllama` instance every agent uses.
- **Inputs**: `temperature: float`.
- **Outputs**: `ChatOllama` instance.
- **Depends on**: `langchain-ollama`, `config.py`.

### `tools/neo4j_tools.py`
- **Purpose**: every read against the graph — the only file allowed to hold Cypher.
- **Inputs**: artist name(s).
- **Outputs**: dicts/lists/bools of live graph data; `resolve_artist_name()` for fuzzy validation.
- **Depends on**: `neo4j` driver, `config.py`.

### `monitoring/langsmith_tracer.py`
- **Purpose**: per-step latency/token/cost/failure capture; LangSmith wiring reference.
- **Inputs**: a callable + its args (`trace_step`).
- **Outputs**: `StepMetric` list, aggregate totals.
- **Depends on**: `config.py`, `utils/logger.py`.

### `agents/intent_agent.py`
- See `docs/AGENT_INTERACTION.md` → Intent Agent contract.
- **Depends on**: `core/llm_client.py`, `langsmith`, `pydantic`.

### `agents/entity_agent.py`
- See `docs/AGENT_INTERACTION.md` → Entity Extraction Agent contract.
- **Depends on**: `core/llm_client.py`, `tools/neo4j_tools.py`, `config.py`, `langsmith`, `pydantic`.

### `agents/explanation_agent.py`
- See `docs/AGENT_INTERACTION.md` → Explanation Agent contract.
- **Depends on**: `core/llm_client.py`, `core/token_guardrails.py`, `utils/narrator.py`, `config.py`, `langsmith`.

### `agents/supervisor_agent.py`
- See `docs/AGENT_INTERACTION.md` → Supervisor Agent contract.
- **Depends on**: all three agents above, `core/kill_switch.py`, `core/guardrails.py`, `tools/neo4j_tools.py`, `monitoring/langsmith_tracer.py`.

### `routes/artist_routes.py`
- **Purpose**: thin entry point; logs + delegates to the Supervisor.
- **Inputs**: `query: str`.
- **Outputs**: the Supervisor's response `dict`.
- **Depends on**: `agents/supervisor_agent.py`, `utils/logger.py`.

### `app.py`
- **Purpose**: Streamlit chat UI, kill-switch status/controls, live monitoring panel.
- **Depends on**: `routes/artist_routes.py`, `core/kill_switch.py`, `streamlit`.

## How Ollama is used (requirement H)

`core/llm_client.get_ollama_llm()` builds one shared, cached
`ChatOllama(model="llama3.1:8b", ...)`. It's invoked by:
- **Intent Agent** — structured-output classification.
- **Entity Extraction Agent** — structured-output candidate extraction.
- **Explanation Agent** — free-text narration grounded in Neo4j facts.

All three degrade to a deterministic fallback if the call fails, so
Ollama being down never crashes the app — it just reduces explanation
quality/intent accuracy for that one request.

## How LangSmith is used (requirement H)

See the docstring at the top of `monitoring/langsmith_tracer.py` for
the exact `.env` + `@traceable` code. Summary: `@traceable` decorators
on every agent method export full run trees to LangSmith when
`LANGCHAIN_TRACING_V2=true`; the local `LangSmithTracer` class always
captures per-step latency/tokens/cost/failures regardless, and feeds
the Streamlit sidebar.

## How the Kill Switch works (requirement H)

See `docs/ARCHITECTURE.md` §4. Two independent, fail-closed activation
paths (`.env` flag, runtime flag file), checked as the very first line
of `SupervisorAgent.handle_query()`.

## How token monitoring works (requirement H)

`LangSmithTracer._extract_usage()` reads `usage_metadata` off whatever
each agent step returns (LangChain's `AIMessage`/structured-output
objects carry this for `ChatOllama` in the pinned `langchain-core`
version). Tokens are summed per step and totalled per request;
`COST_PER_1K_TOKENS` in `.env` (0.0 for local Ollama by default) turns
that into an estimated cost, ready to become non-zero the moment a
paid API model is swapped in via `MODEL_PROVIDER`.
