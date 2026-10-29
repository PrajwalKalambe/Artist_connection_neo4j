"""
tools/neo4j_tools.py

Every artist/song/label value used anywhere in this app comes from
these functions, straight out of Neo4j — nothing is hardcoded. This
module is the ONLY place that talks to the database.

TIMEOUT NOTE: Neo4j's own defaults are bounded (not infinite like
Ollama's), but they're generous enough (tens of seconds) that a bad or
stale connection to a remote instance can still make the UI sit
unresponsive for a while before anything happens. We tighten them
explicitly via config so a connection problem fails fast instead.
"""
from difflib import get_close_matches

from neo4j import GraphDatabase

import config

driver = GraphDatabase.driver(
    config.NEO4J_URI,
    auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    connection_timeout=config.NEO4J_CONNECTION_TIMEOUT_SECONDS,
    connection_acquisition_timeout=config.NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS,
    max_connection_lifetime=config.NEO4J_MAX_CONNECTION_LIFETIME_SECONDS,
)

# TOOL 1: CHECK DIRECT CONNECTION
def check_direct_connection(artist1, artist2):

    query = """
    MATCH (a1:Artist {name_english:$artist1}),
          (a2:Artist {name_english:$artist2})
    RETURN EXISTS(
        (a1)-[:COLLABORATED_WITH]-(a2)
    ) AS connected
    """

    with driver.session() as session:
        result = session.run(query, artist1=artist1, artist2=artist2)
        record = result.single()
        return record["connected"] if record else False


# TOOL 2: FIND CONNECTION PATH
def find_connection_path(artist1, artist2):

    query = """
    MATCH (a1:Artist {name_english:$artist1}),
          (a2:Artist {name_english:$artist2})

    MATCH path =
    shortestPath(
       (a1)-[:COLLABORATED_WITH*1..6]-(a2)
    )

    RETURN
    [n IN nodes(path) | n.name_english] AS chain,
    length(path) AS hops
    """

    with driver.session() as session:
        result = session.run(query, artist1=artist1, artist2=artist2)
        record = result.single()

        if record:
            return {"chain": record["chain"], "hops": record["hops"]}

        return None


# TOOL 3: GET BRIDGING SONG
def get_bridging_song(artist1, artist2):

    query = """
    MATCH
    (a1:Artist {name_english:$artist1})
        <-[:PERFORMED_BY|FEATURES]-
    (s:Song)
        -[:PERFORMED_BY|FEATURES]->
    (a2:Artist {name_english:$artist2})

    RETURN
    s.title_english AS song,
    s.year AS year

    ORDER BY s.year DESC
    """

    with driver.session() as session:
        result = session.run(query, artist1=artist1, artist2=artist2)
        return [dict(record) for record in result]


# TOOL 4: GET COLLABORATION NETWORK
def get_collaboration_network(artist_name, hops=2):

    query = """
    MATCH (start:Artist {name_english:$artist})

    MATCH path=
    (start)-[:COLLABORATED_WITH*1..2]-(other:Artist)

    WHERE other <> start

    RETURN DISTINCT
    other.name_english AS artist,
    length(path) AS hops

    ORDER BY hops
    """

    with driver.session() as session:
        result = session.run(query, artist=artist_name)
        return [dict(r) for r in result]


# TOOL 5: GET LABEL MATES
def get_label_mates(artist_name):

    query = """
    MATCH
    (a1:Artist {name_english:$artist})
       -[:SIGNED_TO]->
    (l:Label)
       <-[:SIGNED_TO]-
    (a2:Artist)

    WHERE a1 <> a2

    RETURN
    a2.name_english AS artist,
    l.name AS label
    """

    with driver.session() as session:
        result = session.run(query, artist=artist_name)
        return [dict(r) for r in result]


# TOOL 6: GET SHARED LABELS (labels BOTH artists are signed to)
def get_shared_labels(artist1, artist2):

    query = """
    MATCH (a1:Artist {name_english:$artist1})
       -[:SIGNED_TO]->
    (l:Label)
       <-[:SIGNED_TO]-
    (a2:Artist {name_english:$artist2})

    RETURN DISTINCT l.name AS label
    """

    with driver.session() as session:
        result = session.run(query, artist1=artist1, artist2=artist2)
        return [record["label"] for record in result]


# COMBINED FETCH: everything the Explanation Agent needs for a
# connection_path query, in one Neo4j session.
def get_connection_bundle(artist1, artist2):
    """
    Returns a single combined dict — shortest path, direct-collaboration
    flag, every bridging song along each hop of that path (deduplicated),
    and any shared record labels — or None if no path exists at all.

    Query strategy notes:
      - All lookups share ONE driver session instead of opening a new
        session per call (the old check_direct_connection /
        find_connection_path / get_bridging_song pattern), cutting
        connection/round-trip overhead for what is functionally one
        logical request.
      - Bridging songs are only ever queried for artist PAIRS that are
        actually adjacent on the shortest path — never the whole graph —
        so a 5-hop chain does 4 small, targeted song lookups instead of
        one unbounded one.
      - If the path is a single hop (hops == 1), the "between" pair is
        just (artist1, artist2), so this also covers the simple direct
        connection case the old get_bridging_song() handled.
    """
    with driver.session() as session:

        path_record = session.run(
            """
            MATCH (a1:Artist {name_english:$artist1}),
                  (a2:Artist {name_english:$artist2})

            MATCH path =
            shortestPath(
               (a1)-[:COLLABORATED_WITH*1..6]-(a2)
            )

            RETURN
            [n IN nodes(path) | n.name_english] AS chain,
            length(path) AS hops
            """,
            artist1=artist1,
            artist2=artist2,
        ).single()

        if not path_record:
            return None

        chain = path_record["chain"]
        hops = path_record["hops"]

        direct_record = session.run(
            """
            MATCH (a1:Artist {name_english:$artist1}),
                  (a2:Artist {name_english:$artist2})
            RETURN EXISTS(
                (a1)-[:COLLABORATED_WITH]-(a2)
            ) AS connected
            """,
            artist1=artist1,
            artist2=artist2,
        ).single()
        direct_collaboration = bool(direct_record["connected"]) if direct_record else False

        songs = []
        seen = set()
        for i in range(len(chain) - 1):
            left, right = chain[i], chain[i + 1]

            hop_songs = session.run(
                """
                MATCH
                (a1:Artist {name_english:$left})
                    <-[:PERFORMED_BY|FEATURES]-
                (s:Song)
                    -[:PERFORMED_BY|FEATURES]->
                (a2:Artist {name_english:$right})

                RETURN DISTINCT
                s.title_english AS song,
                s.year AS year

                ORDER BY s.year DESC
                """,
                left=left,
                right=right,
            )

            for record in hop_songs:
                key = (record["song"], record["year"])
                if key not in seen:
                    seen.add(key)
                    songs.append(
                        {
                            "song": record["song"],
                            "year": record["year"],
                            "between": [left, right],
                        }
                    )

        labels_result = session.run(
            """
            MATCH (a1:Artist {name_english:$artist1})
               -[:SIGNED_TO]->
            (l:Label)
               <-[:SIGNED_TO]-
            (a2:Artist {name_english:$artist2})

            RETURN DISTINCT l.name AS label
            """,
            artist1=artist1,
            artist2=artist2,
        )
        shared_labels = [record["label"] for record in labels_result]

    return {
        "chain": chain,
        "hops": hops,
        "direct_collaboration": direct_collaboration,
        "songs": songs,
        "shared_labels": shared_labels,
    }


# ----------------------------------------------------------------------
# ARTIST RESOLUTION / VALIDATION (used by the Entity Extraction Agent)
# ----------------------------------------------------------------------
def get_artist_name(artist_name):

    query = """
    MATCH (a:Artist)
    WHERE toLower(a.name_english) = toLower($artist)
    RETURN a.name_english AS artist
    """

    with driver.session() as session:
        result = session.run(query, artist=artist_name)
        record = result.single()
        return record["artist"] if record else None


def get_all_artists():
    """Every artist name currently in the graph. Always live, never cached
    across process restarts, so newly-ingested artists are picked up
    automatically."""

    query = """
    MATCH (a:Artist)
    RETURN a.name_english AS artist
    ORDER BY artist
    """

    with driver.session() as session:
        result = session.run(query)
        return [record["artist"] for record in result]


def artist_exists(artist_name):

    query = """
    MATCH (a:Artist)
    WHERE toLower(a.name_english) = toLower($artist)
    RETURN count(a) AS total
    """

    with driver.session() as session:
        result = session.run(query, artist=artist_name)
        return result.single()["total"] > 0


def resolve_artist_name(candidate: str, threshold: float = None):
    """
    Validates a candidate artist name (e.g. extracted by an LLM) against
    the live graph. Returns the canonical name stored in Neo4j, or None
    if nothing close enough is found. Never hardcodes a name list — it
    pulls the current roster via get_all_artists() every call.
    """
    if threshold is None:
        threshold = config.ENTITY_MATCH_THRESHOLD

    exact = get_artist_name(candidate)
    if exact:
        return exact

    known_artists = get_all_artists()
    close = get_close_matches(candidate, known_artists, n=1, cutoff=threshold)
    return close[0] if close else None


def get_graph_statistics():

    query = """
    MATCH (a:Artist)
    WITH count(a) AS artist_count

    MATCH (s:Song)
    WITH artist_count, count(s) AS song_count

    MATCH ()-[r]->()
    RETURN artist_count, song_count, count(r) AS relationship_count
    """

    with driver.session() as session:
        result = session.run(query)
        record = result.single()
        return dict(record) if record else {}


def health_check():

    query = "RETURN 'Neo4j Connected' AS status"

    with driver.session() as session:
        result = session.run(query)
        return result.single()["status"]


def close_driver():
    """Call on app shutdown to release the connection pool cleanly."""
    driver.close()
