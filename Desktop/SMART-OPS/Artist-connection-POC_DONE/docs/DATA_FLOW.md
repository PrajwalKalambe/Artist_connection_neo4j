# Data Flow — Artist Connection Explorer

## End-to-end request lifecycle

```
 User types:
 "How is Arijit Singh connected to Shreya Ghoshal?"
        │
        ▼
 ┌────────────────────┐
 │ Streamlit (app.py)  │  st.chat_input() captures the query
 └─────────┬────────────┘
          │ router.process_query(query)
          ▼
 ┌────────────────────┐
 │  ArtistRouter        │  logs receipt, calls Supervisor
 └─────────┬────────────┘
          │ supervisor.handle_query(query)
          ▼
 ┌──────────────────────────────────────────────────────────┐
 │                    SUPERVISOR AGENT                        │
 │                                                              │
 │  Step 1  KillSwitch.enforce()                                │
 │          reads .env + KILL_SWITCH.flag fresh                │
 │          ── if active → return blocked response, STOP HERE   │
 │                                                              │
 │  Step 2  GuardRails.validate_user_input(query)                │
 │          length / emptiness check                            │
 │          ── if invalid → return rejected response, STOP       │
 │                                                              │
 │  Step 3  IntentAgent.classify(query)                          │
 │          → Ollama structured output                          │
 │          → IntentClassification(intent="connection_path", ..) │
 │                                                              │
 │  Step 4  EntityAgent.extract_and_validate(query)               │
 │          a. Ollama pulls candidate names: ["Arijit Singh",     │
 │             "Shreya Ghoshal"]                                 │
 │          b. tools.neo4j_tools.resolve_artist_name() validates  │
 │             EACH candidate against the LIVE graph               │
 │             (exact match → fuzzy match → drop if no match)      │
 │          → ["Arijit Singh", "Shreya Ghoshal"]  (Neo4j-confirmed)│
 │                                                              │
 │  Step 5  Tool dispatch: intent "connection_path" maps to        │
 │          tools.neo4j_tools.find_connection_path(a1, a2)         │
 │          → Cypher shortestPath query against Neo4j               │
 │          → {"chain": ["Arijit Singh","Shreya Ghoshal"],"hops":1} │
 │                                                              │
 │  Step 6  ExplanationAgent.explain(query, intent, entities, facts)│
 │          a. Narrator builds a deterministic factual summary      │
 │          b. Ollama is prompted with query + intent + entities +  │
 │             facts + that summary → rich narrated explanation      │
 │          → "Arijit Singh and Shreya Ghoshal are directly         │
 │             connected — they've collaborated together, making    │
 │             this a first-degree connection in the graph."        │
 │                                                              │
 │  Step 7  build_response() — bundles response text + status +     │
 │          latency + token/cost trace + raw intent/entities/facts  │
 └───────────────────────────┬────────────────────────────────┘
                             │ result: dict
                             ▼
                 ┌────────────────────┐
                 │  ArtistRouter        │ logs status, returns dict
                 └─────────┬────────────┘
                           ▼
                 ┌────────────────────┐
                 │ Streamlit (app.py)  │ renders result["response"] in
                 │                      │ chat + trace in sidebar monitor
                 └────────────────────┘
```

## Where monitoring data is captured

Every one of Steps 3–6 above is wrapped individually by
`LangSmithTracer.trace_step()` inside the Supervisor:

```python
intent_result = tracer.trace_step("intent_agent", self.intent_agent.classify, query)
entities      = tracer.trace_step("entity_agent", self.entity_agent.extract_and_validate, query)
facts         = tracer.trace_step("neo4j_tool", self._execute_tool, intent, entities)
explanation   = tracer.trace_step("explanation_agent", self.explanation_agent.explain, query, intent, entities, facts)
```

Each call records latency, token usage (when the wrapped function
returns an `AIMessage`-like object with `usage_metadata`), and status
(success/error) into `tracer.metrics`, which is what powers both the
Streamlit sidebar panel and (when enabled) mirrors what LangSmith
itself records via the `@traceable` decorators on the agent methods.

## Failure-path data flow (kill switch example)

```
 User query
     │
     ▼
 KillSwitch.enforce() raises KillSwitchActiveError
     │
     ▼
 Supervisor catches it immediately — NO Ollama call, NO Neo4j call
     │
     ▼
 { "response": "AI processing is currently disabled...",
   "status": "blocked", "latency_ms": ~0, "trace": [] }
     │
     ▼
 Streamlit shows the message + a red "Kill Switch ENGAGED" banner
```
