"""
core/llm_client.py

Single place that constructs the Ollama chat model. Every agent (Intent,
Entity, Explanation) gets its model from here instead of instantiating
ChatOllama directly — this is what makes Ollama an actual, shared,
first-class part of the architecture instead of being "barely used".

Compatible with LangChain 1.x / langchain-ollama's ChatOllama, which
returns AIMessage objects carrying `.usage_metadata` (input/output/total
tokens) — that's what monitoring/langsmith_tracer.py reads to report
token consumption per agent call.

TIMEOUT NOTE (important — this fixes "app hangs after a few queries"):
The underlying `ollama` python package defaults its HTTP client timeout
to None, meaning a call can block FOREVER if the Ollama server is slow,
overloaded, or stuck (e.g. reloading the model, or already busy with a
previous request). ChatOllama exposes `client_kwargs`, which it merges
into both its sync and async httpx clients — we set `timeout` there
explicitly so a stuck call fails after config.OLLAMA_REQUEST_TIMEOUT_SECONDS
instead of hanging the whole Streamlit app. Once it raises, each
agent's existing try/except already falls back gracefully (rule-based
intent, substring entity match, templated explanation).
"""
from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama

import config


@lru_cache(maxsize=8)
def get_ollama_llm(temperature: float = 0.0) -> ChatOllama:
    """
    Returns a cached ChatOllama instance for the given temperature.
    Cached so repeated agent calls within a session reuse the same
    client/connection instead of reconnecting every query.
    """
    return ChatOllama(
        model=config.OLLAMA_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=temperature,
        client_kwargs={"timeout": config.OLLAMA_REQUEST_TIMEOUT_SECONDS},
    )