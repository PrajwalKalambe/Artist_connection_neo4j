# Agent Interaction Diagram

## Sequence diagram

```
User        Supervisor      KillSwitch   IntentAgent   EntityAgent   Neo4jTools   ExplanationAgent
 │  query        │               │             │             │            │               │
 │──────────────►│               │             │             │            │               │
 │               │──enforce()───►│             │             │            │               │
 │               │◄──ok/raise────│             │             │            │               │
 │               │  (if blocked, return here — nothing below runs)         │               │
 │               │                                                          │               │
 │               │──classify(query)───────────►│             │            │               │
 │               │                              │──Ollama invoke()──►      │               │
 │               │                              │◄─IntentClassification────│               │
 │               │◄────intent──────────────────│             │            │               │
 │               │                                                          │               │
 │               │──extract_and_validate(query)──────────────►│            │               │
 │               │                                             │─Ollama───►│               │
 │               │                                             │◄candidates│               │
 │               │                                             │─resolve_artist_name()──►│  │
 │               │                                             │◄validated names──────────│  │
 │               │◄──────────entities─────────────────────────│            │               │
 │               │                                                          │               │
 │               │──dispatch(intent, entities)────────────────────────────►│               │
 │               │◄─────────────────facts (dict/list/bool)─────────────────│               │
 │               │                                                          │               │
 │               │──explain(query, intent, entities, facts)───────────────────────────────►│
 │               │                                                          Narrator (fallback/grounding)
 │               │                                                          Ollama invoke() │
 │               │◄─────────────────────explanation (str)──────────────────────────────────│
 │               │                                                                           
 │◄──response, status, trace────│                                                           
```

## Agent contracts

### Intent Agent
- **In**: `query: str`
- **Out**: `IntentClassification { intent, confidence, reasoning }`
- **Calls**: Ollama (structured output) → rule-based fallback on failure
- **Side effects**: none (pure classification)

### Entity Extraction Agent
- **In**: `query: str`
- **Out**: `list[str]` — canonical artist names, each confirmed to
  exist in Neo4j right now
- **Calls**: Ollama (candidate extraction) → `tools.neo4j_tools.resolve_artist_name`
  (exact + fuzzy match) for every candidate
- **Side effects**: read-only Neo4j queries

### Explanation Agent
- **In**: `query, intent, entities, facts`
- **Out**: `str` — final explanation shown to the user
- **Calls**: `utils.narrator.Narrator` (deterministic grounding text) →
  Ollama (free-text narration constrained to those facts)
- **Side effects**: none

### Supervisor Agent
- **In**: `query: str`
- **Out**: `dict { response, status, latency_ms, trace, total_tokens, total_cost_usd, had_failure, ... }`
- **Calls**: `KillSwitch`, `GuardRails`, all three agents above,
  `tools.neo4j_tools.*` (via the intent→tool dispatch table),
  `LangSmithTracer`
- **Owns**: orchestration order, error translation (unsupported
  intent / missing entities / unhandled exception → user-safe
  messages), response assembly

## Why this shape

- Each agent has exactly one Pydantic-typed input/output contract —
  easy to unit test in isolation (see `tests/test_agents.py`), easy to
  swap the underlying model later (e.g. point `core/llm_client.py` at
  a different provider) without touching agent logic.
- The Supervisor is the *only* place that knows the pipeline order,
  which keeps the individual agents composable and reusable outside
  this specific flow if needed later.
