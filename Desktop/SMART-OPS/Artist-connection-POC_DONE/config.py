"""
config.py

Single source of truth for every environment-driven setting used across
the app. Nothing below is hardcoded business data (no artist names, song
names, or labels) — only infrastructure/config values, per the "no
hardcoded data" requirement.
"""
from dotenv import load_dotenv
import os

load_dotenv()


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------
# MODEL / LLM
# --------------------------------------------------------------------
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "ollama")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# The `ollama` python package (which langchain-ollama sits on top of)
# defaults its HTTP client timeout to None -- i.e. NO timeout, ever.
# If Ollama is slow/stuck/overloaded, a call can hang forever and the
# whole Streamlit app freezes with it. This bounds every Ollama call
# to a fixed number of seconds so a stuck call fails fast instead,
# letting each agent's existing try/except fallback logic take over.
OLLAMA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", 90))

# --------------------------------------------------------------------
# NEO4J
# --------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
# Neo4j's own defaults are bounded (not infinite like Ollama's), but
# they're generous (tens of seconds). Tightening them explicitly means
# a bad/stale connection to a remote instance fails fast too, instead
# of the UI sitting there for up to a minute before anything happens.
NEO4J_CONNECTION_TIMEOUT_SECONDS = float(os.getenv("NEO4J_CONNECTION_TIMEOUT_SECONDS", 15))
NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS = float(
    os.getenv("NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS", 20)
)
NEO4J_MAX_CONNECTION_LIFETIME_SECONDS = float(
    os.getenv("NEO4J_MAX_CONNECTION_LIFETIME_SECONDS", 300)
)

# --------------------------------------------------------------------
# GUARDRAILS
# --------------------------------------------------------------------
MAX_INPUT_LENGTH = int(os.getenv("MAX_INPUT_LENGTH", 500))
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", 3))
MAX_RESPONSE_WORDS = int(os.getenv("MAX_RESPONSE_WORDS", 220))
ENTITY_MATCH_THRESHOLD = float(os.getenv("ENTITY_MATCH_THRESHOLD", 0.72))
ALLOWED_DOMAINS = [
    d.strip()
    for d in os.getenv(
        "ALLOWED_DOMAINS", "artist,music,song,label,collaboration"
    ).split(",")
    if d.strip()
]

# --------------------------------------------------------------------
# KILL SWITCH
# --------------------------------------------------------------------
# NOTE: core.kill_switch re-reads this live (does not rely on the cached
# value below) so it can be flipped at runtime without restarting the
# app. This constant is exposed for display/logging purposes only.
KILL_SWITCH_ENABLED = _bool_env("KILL_SWITCH_ENABLED")

# --------------------------------------------------------------------
# SESSION TOKEN TRACKING
# --------------------------------------------------------------------
# Cumulative cap across an entire chat session (not one query). Tracking
# only for now -- monitoring/session_token_tracker.py records usage
# against this, but nothing currently stops execution when it's hit.
MAX_SESSION_TOKENS = int(os.getenv("MAX_SESSION_TOKENS", 3000))

# --------------------------------------------------------------------
# LANGSMITH / OBSERVABILITY
# --------------------------------------------------------------------
LANGCHAIN_TRACING_V2 = _bool_env("LANGCHAIN_TRACING_V2")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "ArtistConnectionExplorer")
LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
# $ per 1K tokens, used to estimate cost in the monitoring layer. Ollama
# is local/free by default (0.0); set this if you point MODEL_PROVIDER
# at a paid API model instead.
COST_PER_1K_TOKENS = float(os.getenv("COST_PER_1K_TOKENS", "0.0"))

# Propagate LangSmith settings into the environment for LangChain's
# tracing middleware, which reads them directly from os.environ.
if LANGCHAIN_TRACING_V2:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_ENDPOINT"] = LANGCHAIN_ENDPOINT
    if LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY