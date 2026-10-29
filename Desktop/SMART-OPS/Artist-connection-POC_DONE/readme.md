# Artist Connection Explorer

Find and explain how artists are connected — collaborations, bridging
songs, shared labels, and full collaboration networks — using Neo4j
graph traversal and a real multi-agent Ollama pipeline.

## What changed in v2

The original single-service architecture has been replaced with a
**Supervisor + 3-agent** design. See `docs/` for full detail:

- `docs/ARCHITECTURE.md` — component diagram, kill switch, monitoring
- `docs/DATA_FLOW.md` — step-by-step request lifecycle
- `docs/AGENT_INTERACTION.md` — sequence diagram, agent contracts
- `docs/FILE_PLAN.md` — file-by-file plan, what was deleted/merged/added
- `docs/PYTHON_3_14_UPGRADE.md` — checklist for upgrading from Python 3.11 to 3.14

## Components

- Neo4j graph database (artists, songs, labels — nothing hardcoded)
- **Supervisor Agent** — orchestrates the pipeline below
- **Intent Agent** — Ollama-driven intent classification
- **Entity Extraction Agent** — Ollama extraction + Neo4j validation
- **Explanation Agent** — Ollama-driven rich narration of the results
- **Kill Switch** — `.env`-controlled + runtime flag file, enterprise-ready
- **LangSmith / local tracer** — latency, token, cost, failure monitoring
- Streamlit UI

## Features

- **Direct Connection** — did two artists collaborate directly?
- **Connection Path** — shortest chain between two artists
- **Bridging Songs** — the song(s) that connect two artists
- **Collaboration Network** — artists within 2 hops
- **Label Mates** — artists signed to the same label
- **Graph Statistics** — dataset size / totals

## Data flow (high level)

```
User
 │
 ▼
Streamlit UI
 │
 ▼
ArtistRouter
 │
 ▼
Supervisor Agent
 │
 ├─► Kill Switch (blocks everything below if engaged)
 ├─► Intent Agent (Ollama)
 ├─► Entity Extraction Agent (Ollama + Neo4j validation)
 ├─► Neo4j Tool Layer
 └─► Explanation Agent (Ollama, grounded in Neo4j facts)
 │
 ▼
Formatted, narrated response + live monitoring trace
 │
 ▼
Streamlit UI
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your real Neo4j / LangSmith values
ollama pull llama3.1:8b
streamlit run app.py
```

## Running tests

```bash
# Fast, mocked, no live services needed:
pytest tests/test_kill_switch.py tests/test_agents.py tests/test_supervisor.py -v

# Manual smoke tests (need a reachable Neo4j + running Ollama):
python tests/test_connection.py
python tests/test_router.py
```

## Kill switch

```bash
# Option A — .env
KILL_SWITCH_ENABLED=true

# Option B — runtime flag file (no redeploy needed)
touch KILL_SWITCH.flag   # engage
rm KILL_SWITCH.flag      # disengage
```

Both are also exposed as buttons in the Streamlit sidebar.
YES