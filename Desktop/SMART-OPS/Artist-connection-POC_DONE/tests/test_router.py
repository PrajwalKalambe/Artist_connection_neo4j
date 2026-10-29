"""
tests/test_router.py

Manual end-to-end smoke test — this exercises the real Supervisor
pipeline (Kill Switch -> Intent -> Entity -> Neo4j -> Explanation), so
it needs a reachable Neo4j instance and a running Ollama server with
llama3.1:8b pulled. Run directly with `python tests/test_router.py`;
it is not a pytest test (see test_kill_switch.py / test_agents.py for
the mocked, CI-safe unit tests).
"""
import sys
import os

sys.path.append(
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            ".."
        )
    )
)

from routes.artist_routes import ArtistRouter

router = ArtistRouter()

queries = [
    "How is Arijit Singh connected to Shreya Ghoshal?",
    "Are Arijit Singh and Shreya Ghoshal directly connected?",
    "What song connects Arijit Singh and Shreya Ghoshal?",
    "Show collaboration network of Arijit Singh",
    "Show label mates of Arijit Singh",
]

for query in queries:
    print("\n")
    print("=" * 80)
    print(query)

    result = router.process_query(query)

    print(f"\nStatus: {result['status']}")
    print(f"Latency: {result['latency_ms']:.1f} ms")
    print(f"Tokens: {result.get('total_tokens', 0)}")
    print("\nResponse:\n")
    print(result["response"])
