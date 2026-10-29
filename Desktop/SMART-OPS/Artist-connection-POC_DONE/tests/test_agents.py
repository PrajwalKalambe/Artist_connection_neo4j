"""
tests/test_agents.py

Unit tests for IntentAgent, EntityAgent, and ExplanationAgent with the
LLM and Neo4j layers mocked out — these run without a live Ollama or
Neo4j instance, which is what makes them safe for CI.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class _FailingStructuredLLM:
    def invoke(self, messages):
        raise RuntimeError("ollama unreachable")


class _FailingLLM:
    def with_structured_output(self, schema):
        return _FailingStructuredLLM()

    def invoke(self, messages):
        raise RuntimeError("ollama unreachable")


class _WorkingStructuredLLM:
    def __init__(self, payload):
        self._payload = payload

    def invoke(self, messages):
        return self._payload


class _WorkingLLM:
    def __init__(self, structured_payload=None, text_content=None):
        self._structured_payload = structured_payload
        self._text_content = text_content

    def with_structured_output(self, schema):
        return _WorkingStructuredLLM(self._structured_payload)

    def invoke(self, messages):
        return SimpleNamespace(content=self._text_content, usage_metadata=None)


# ----------------------------------------------------------------------
# IntentAgent
# ----------------------------------------------------------------------
def test_intent_agent_falls_back_to_rules_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        "agents.intent_agent.get_ollama_llm", lambda **_: _FailingLLM()
    )
    from agents.intent_agent import IntentAgent

    agent = IntentAgent()
    result = agent.classify("Show label mates of Arijit Singh")
    assert result.intent == "label_mates"


def test_intent_agent_uses_llm_result_when_available(monkeypatch):
    from agents.intent_agent import IntentAgent, IntentClassification

    payload = IntentClassification(
        intent="connection_path", confidence=0.9, reasoning="mocked"
    )
    monkeypatch.setattr(
        "agents.intent_agent.get_ollama_llm",
        lambda **_: _WorkingLLM(structured_payload=payload),
    )

    agent = IntentAgent()
    result = agent.classify("How is Arijit Singh connected to Shreya Ghoshal?")
    assert result.intent == "connection_path"
    assert result.confidence == 0.9


# ----------------------------------------------------------------------
# EntityAgent
# ----------------------------------------------------------------------
def test_entity_agent_fallback_substring_match(monkeypatch):
    monkeypatch.setattr(
        "agents.entity_agent.get_ollama_llm", lambda **_: _FailingLLM()
    )
    monkeypatch.setattr(
        "agents.entity_agent.get_all_artists",
        lambda: ["Arijit Singh", "Shreya Ghoshal"],
    )
    monkeypatch.setattr(
        "agents.entity_agent.resolve_artist_name",
        lambda name, threshold=None: name if name in ("Arijit Singh", "Shreya Ghoshal") else None,
    )

    from agents.entity_agent import EntityAgent

    agent = EntityAgent()
    result = agent.extract_and_validate(
        "How is Arijit Singh connected to Shreya Ghoshal?"
    )
    assert result == ["Arijit Singh", "Shreya Ghoshal"]


def test_entity_agent_validates_llm_candidates_against_neo4j(monkeypatch):
    from agents.entity_agent import EntityAgent, ExtractedEntities

    payload = ExtractedEntities(candidates=["arijit singh", "Some Unknown Artist"])
    monkeypatch.setattr(
        "agents.entity_agent.get_ollama_llm",
        lambda **_: _WorkingLLM(structured_payload=payload),
    )
    monkeypatch.setattr(
        "agents.entity_agent.resolve_artist_name",
        lambda name, threshold=None: "Arijit Singh" if name.lower() == "arijit singh" else None,
    )

    agent = EntityAgent()
    result = agent.extract_and_validate("tell me about arijit singh")
    assert result == ["Arijit Singh"]  # unknown candidate dropped by Neo4j validation


# ----------------------------------------------------------------------
# ExplanationAgent
# ----------------------------------------------------------------------
def test_explanation_agent_falls_back_when_no_facts(monkeypatch):
    monkeypatch.setattr(
        "agents.explanation_agent.get_ollama_llm", lambda **_: _FailingLLM()
    )
    from agents.explanation_agent import ExplanationAgent

    agent = ExplanationAgent()
    text = agent.explain("q", "connection_path", [], None)
    assert "No connection path found" in text


def test_explanation_agent_uses_llm_when_facts_present(monkeypatch):
    monkeypatch.setattr(
        "agents.explanation_agent.get_ollama_llm",
        lambda **_: _WorkingLLM(text_content="Rich narrated explanation."),
    )
    from agents.explanation_agent import ExplanationAgent

    agent = ExplanationAgent()
    facts = {"chain": ["Arijit Singh", "Shreya Ghoshal"], "hops": 1}
    text = agent.explain("q", "connection_path", ["Arijit Singh", "Shreya Ghoshal"], facts)
    assert text == "Rich narrated explanation."


def test_explanation_agent_handles_false_direct_connection(monkeypatch):
    monkeypatch.setattr(
        "agents.explanation_agent.get_ollama_llm",
        lambda **_: _WorkingLLM(text_content="They have never collaborated directly."),
    )
    from agents.explanation_agent import ExplanationAgent

    agent = ExplanationAgent()
    text = agent.explain("q", "direct_connection", ["A", "B"], False)
    # False is valid data (not "no facts"), so the LLM path should run.
    assert text == "They have never collaborated directly."
