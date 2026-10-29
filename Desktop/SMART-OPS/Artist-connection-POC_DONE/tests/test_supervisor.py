"""
tests/test_supervisor.py

Tests the Supervisor Agent's orchestration logic in isolation: kill
switch short-circuiting, unsupported intents, missing-entity handling,
and the happy path — all with the three sub-agents and Neo4j tools
mocked out, so no live services are required.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace

from core.kill_switch import KillSwitch


def _make_supervisor(monkeypatch, intent="connection_path", entities=None, tool_result=None, explanation="Explained."):
    # Avoid constructing real agents (which would build real Ollama clients).
    import agents.supervisor_agent as sup_mod

    class FakeIntentAgent:
        def classify(self, query):
            return SimpleNamespace(intent=intent, confidence=0.9, reasoning="fake")

    class FakeEntityAgent:
        def extract_and_validate(self, query):
            return entities if entities is not None else []

    class FakeExplanationAgent:
        def explain(self, query, intent, entities, facts):
            return explanation

    monkeypatch.setattr(sup_mod, "IntentAgent", lambda: FakeIntentAgent())
    monkeypatch.setattr(sup_mod, "EntityAgent", lambda: FakeEntityAgent())
    monkeypatch.setattr(sup_mod, "ExplanationAgent", lambda: FakeExplanationAgent())

    if tool_result is not None:
        monkeypatch.setattr(
            sup_mod, "_TOOL_MAP",
            {**sup_mod._TOOL_MAP, intent: (lambda *a: tool_result, len(entities or []))},
        )

    return sup_mod.SupervisorAgent()


def test_kill_switch_blocks_before_any_agent_runs(monkeypatch):
    from agents.supervisor_agent import SupervisorAgent

    KillSwitch.engage(reason="test")
    try:
        supervisor = _make_supervisor(monkeypatch)
        result = supervisor.handle_query("How is A connected to B?")
        assert result["status"] == "blocked"
    finally:
        KillSwitch.disengage()


def test_missing_entities_asks_for_clarification(monkeypatch):
    supervisor = _make_supervisor(monkeypatch, intent="connection_path", entities=["Only One Artist"])
    result = supervisor.handle_query("How is X connected to Y?")
    assert result["status"] == "needs_clarification"


def test_unknown_intent_returns_supported_queries(monkeypatch):
    supervisor = _make_supervisor(monkeypatch, intent="unknown", entities=[])
    result = supervisor.handle_query("What's the weather today?")
    assert result["status"] == "unsupported"
    assert "Supported queries" in result["response"]


def test_happy_path_returns_explanation(monkeypatch):
    supervisor = _make_supervisor(
        monkeypatch,
        intent="connection_path",
        entities=["Arijit Singh", "Shreya Ghoshal"],
        tool_result={"chain": ["Arijit Singh", "Shreya Ghoshal"], "hops": 1},
        explanation="They are connected through one collaboration.",
    )
    result = supervisor.handle_query("How is Arijit Singh connected to Shreya Ghoshal?")
    assert result["status"] == "success"
    assert result["response"] == "They are connected through one collaboration."
    assert result["entities"] == ["Arijit Singh", "Shreya Ghoshal"]
