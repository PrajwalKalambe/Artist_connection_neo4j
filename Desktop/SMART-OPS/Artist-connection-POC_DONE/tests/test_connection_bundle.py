"""
tests/test_connection_bundle.py

Verifies the new combined connection_path behavior end-to-end at the
Narrator/ExplanationAgent level (Neo4j itself is not touched — these
feed in the same dict shape tools.neo4j_tools.get_connection_bundle()
returns).
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.narrator import Narrator


SAMPLE_BUNDLE = {
    "chain": ["Arijit Singh", "Shreya Ghoshal"],
    "hops": 1,
    "direct_collaboration": True,
    "songs": [
        {"song": "Where Are You", "year": 2023, "between": ["Arijit Singh", "Shreya Ghoshal"]},
        {"song": "Ve Maahi", "year": 2019, "between": ["Arijit Singh", "Shreya Ghoshal"]},
        {"song": "Pal", "year": 2018, "between": ["Arijit Singh", "Shreya Ghoshal"]},
        {"song": "Ghar", "year": 2020, "between": ["Arijit Singh", "Shreya Ghoshal"]},
    ],
    "shared_labels": [],
}


def test_narrator_includes_all_required_sections():
    text = Narrator.format_connection_bundle(SAMPLE_BUNDLE)

    assert "Arijit Singh and Shreya Ghoshal are directly connected." in text
    assert "Key Insights:" in text
    assert "Degrees of Separation: 1" in text
    assert "Direct Collaboration: Yes" in text
    assert "Shared Songs: 4" in text
    assert "Connection Chain:" in text
    assert "Arijit Singh → Shreya Ghoshal" in text
    assert "Songs Connecting These Artists:" in text
    assert "Where Are You (2023)" in text
    assert "Ve Maahi (2019)" in text
    assert "Pal (2018)" in text
    assert "Summary:" in text


def test_narrator_never_invents_songs_not_in_facts():
    text = Narrator.format_connection_bundle(SAMPLE_BUNDLE)
    # Only the 4 songs actually in the bundle should appear.
    assert text.count("(20") == 4  # 4 "(YEAR)" occurrences, no more


def test_narrator_handles_no_path():
    assert Narrator.format_connection_bundle(None) == (
        "No connection path found between these artists in the graph."
    )


def test_narrator_multi_hop_without_direct_collaboration():
    bundle = {
        "chain": ["Taylor Swift", "Ed Sheeran", "BTS"],
        "hops": 2,
        "direct_collaboration": False,
        "songs": [
            {"song": "End Game", "year": 2017, "between": ["Taylor Swift", "Ed Sheeran"]},
        ],
        "shared_labels": [],
    }
    text = Narrator.format_connection_bundle(bundle)
    assert "2 degrees of separation" in text
    assert "Direct Collaboration: No" in text
    assert "End Game (2017)" in text
    assert "Taylor Swift → Ed Sheeran → BTS" in text


def test_explanation_agent_fallback_matches_narrator_bundle_format(monkeypatch):
    monkeypatch.setattr(
        "agents.explanation_agent.get_ollama_llm",
        lambda **_: _FailingLLM(),
    )
    from agents.explanation_agent import ExplanationAgent

    agent = ExplanationAgent()
    text = agent.explain(
        "How is Arijit Singh connected to Shreya Ghoshal?",
        "connection_path",
        ["Arijit Singh", "Shreya Ghoshal"],
        SAMPLE_BUNDLE,
    )
    # LLM failed -> should fall back to the exact Narrator structured text.
    assert text == Narrator.format_connection_bundle(SAMPLE_BUNDLE)


class _FailingLLM:
    def invoke(self, messages):
        raise RuntimeError("ollama unreachable")
