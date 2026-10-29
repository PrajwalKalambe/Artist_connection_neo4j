"""
utils/narrator.py

Deterministic, template-based formatting of raw Neo4j facts into
ChatGPT-style text: a short lead-in paragraph, a "Key Insights" bullet
list, an intent-specific "Supporting Data" section, and a closing
summary/conclusion line. Every value that appears is read straight off
the Neo4j result passed in — this module never invents a fact.

This serves two roles:
  1. The Explanation Agent's fallback when Ollama is unreachable or the
     kill switch trips mid-flight, so the app degrades gracefully
     instead of failing or reverting to a bare data dump.
  2. The factual "ground truth" block handed to the LLM as grounding
     context, so the LLM can narrate more naturally while never
     contradicting or adding to the actual graph data.
"""


def _bullets(lines):
    return "\n".join(f"• {line}" for line in lines)


class Narrator:

    # ------------------------------------------------------------------
    # CONNECTION PATH (now driven by the combined bundle from
    # tools.neo4j_tools.get_connection_bundle — path + direct-collab
    # flag + bridging songs per hop + shared labels)
    # ------------------------------------------------------------------
    @staticmethod
    def format_connection_bundle(result):

        if not result:
            return "No connection path found between these artists in the graph."

        chain = result["chain"]
        hops = result["hops"]
        direct = result.get("direct_collaboration", False)
        songs = result.get("songs", [])
        shared_labels = result.get("shared_labels", [])

        artist_a, artist_b = chain[0], chain[-1]

        # ---- Opening paragraph ----
        if hops == 1:
            lead = f"{artist_a} and {artist_b} are directly connected."
        else:
            lead = (
                f"{artist_a} and {artist_b} are connected through "
                f"{hops} degrees of separation in the music collaboration graph."
            )

        # ---- Key Insights ----
        insights = [
            f"Degrees of Separation: {hops}",
            f"Direct Collaboration: {'Yes' if direct else 'No'}",
            f"Shared Songs: {len(songs)}",
        ]
        if shared_labels:
            insights.append(f"Shared Label(s): {', '.join(shared_labels)}")

        parts = [lead, "", "Key Insights:", _bullets(insights)]

        # ---- Supporting data: connection chain ----
        parts += ["", "Connection Chain:", " → ".join(chain)]

        # ---- Supporting data: bridging songs ----
        if songs:
            song_lines = [f"{s['song']} ({s['year']})" for s in songs]
            parts += ["", "Songs Connecting These Artists:", _bullets(song_lines)]

        # ---- Supporting data: shared labels ----
        if shared_labels:
            parts += ["", "Shared Labels:", _bullets(shared_labels)]

        # ---- Summary ----
        if direct and songs:
            summary = (
                f"These artists have collaborated directly on {len(songs)} "
                "song(s) and belong to a closely connected music network."
            )
        elif direct:
            summary = "These artists have collaborated directly with each other."
        elif songs:
            summary = (
                "These artists are linked through shared songs along the "
                "collaboration path shown above, without a single direct pairing."
            )
        else:
            summary = (
                f"These artists are connected only indirectly, through "
                f"{hops} step(s) of collaboration in the graph."
            )

        parts += ["", "Summary:", summary]

        return "\n".join(parts)

    # Backward-compatible alias for the old {chain, hops}-only shape.
    @staticmethod
    def format_connection_path(result):
        if not result:
            return "No connection path found."
        return Narrator.format_connection_bundle(
            {
                "chain": result["chain"],
                "hops": result["hops"],
                "direct_collaboration": result["hops"] == 1,
                "songs": [],
                "shared_labels": [],
            }
        )

    # ------------------------------------------------------------------
    # DIRECT CONNECTION (yes/no)
    # ------------------------------------------------------------------
    @staticmethod
    def format_direct_connection(connected, entities):
        if connected is None:
            return "Could not determine whether these artists are directly connected."

        artist_a = entities[0] if len(entities) > 0 else "Artist A"
        artist_b = entities[1] if len(entities) > 1 else "Artist B"

        if connected:
            lead = f"{artist_a} and {artist_b} are directly connected in the music collaboration graph."
            summary = "They have a direct collaboration relationship recorded in Neo4j."
        else:
            lead = f"{artist_a} and {artist_b} are not directly connected in the music collaboration graph."
            summary = "No direct collaboration between them is recorded in Neo4j."

        insights = [f"Direct Collaboration: {'Yes' if connected else 'No'}"]

        return "\n".join(
            [lead, "", "Key Insights:", _bullets(insights), "", "Summary:", summary]
        )

    # ------------------------------------------------------------------
    # BRIDGING SONG
    # ------------------------------------------------------------------
    @staticmethod
    def format_bridging_song(result):

        if not result:
            return "No bridging songs found between these artists in the graph."

        lead = f"These artists are connected through {len(result)} song(s) in the graph."
        insights = [f"Shared Songs: {len(result)}"]
        song_lines = [f"{s['song']} ({s['year']})" for s in result]

        return "\n".join(
            [
                lead,
                "",
                "Key Insights:",
                _bullets(insights),
                "",
                "Songs Connecting These Artists:",
                _bullets(song_lines),
                "",
                "Summary:",
                "These songs represent direct collaborations recorded between the artists.",
            ]
        )

    # ------------------------------------------------------------------
    # COLLABORATION NETWORK
    # ------------------------------------------------------------------
    @staticmethod
    def format_network(result):

        if not result:
            return "No collaboration network found for this artist in the graph."

        lead = f"This artist is connected to {len(result)} other artist(s) within 2 degrees of collaboration."
        insights = [f"Artists in Network: {len(result)}"]
        network_lines = [f"{a['artist']} (Hop {a['hops']})" for a in result]

        return "\n".join(
            [
                lead,
                "",
                "Key Insights:",
                _bullets(insights),
                "",
                "Collaboration Network:",
                _bullets(network_lines),
                "",
                "Summary:",
                "These artists are reachable through direct or one-step-removed collaborations in the graph.",
            ]
        )

    # ------------------------------------------------------------------
    # LABEL MATES
    # ------------------------------------------------------------------
    @staticmethod
    def format_label_mates(result):

        if not result:
            return "No label mates found for this artist in the graph."

        label = result[0]["label"]
        lead = f"This artist shares a record label with {len(result)} other artist(s)."
        insights = [f"Label: {label}", f"Label Mates: {len(result)}"]
        mate_lines = [a["artist"] for a in result]

        return "\n".join(
            [
                lead,
                "",
                "Key Insights:",
                _bullets(insights),
                "",
                "Label Mates:",
                _bullets(mate_lines),
                "",
                "Summary:",
                f"These artists are all signed to {label} according to the graph.",
            ]
        )

    # ------------------------------------------------------------------
    # GRAPH STATISTICS
    # ------------------------------------------------------------------
    @staticmethod
    def format_graph_statistics(result):

        if not result:
            return "No graph statistics available."

        lead = "Here is a snapshot of the current music collaboration graph."
        insights = [
            f"Artists: {result['artist_count']}",
            f"Songs: {result['song_count']}",
            f"Relationships: {result['relationship_count']}",
        ]

        return "\n".join(
            [lead, "", "Key Insights:", _bullets(insights)]
        )
