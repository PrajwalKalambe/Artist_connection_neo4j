"""
monitoring/langsmith_tracer.py

Two layers of observability, both driven from here:

1. LangSmith itself — every agent method that calls an LLM is wrapped
   with `@traceable` (see agents/*.py). When LANGCHAIN_TRACING_V2=true
   and LANGCHAIN_API_KEY is set in .env, LangSmith automatically
   receives a full run tree (inputs, outputs, latency, token usage,
   errors) for every agent call, nested under the Supervisor's run.
   That satisfies "trace every agent execution" with zero extra code
   in the agents beyond the decorator.

2. A lightweight LOCAL tracer (this class) that the Supervisor Agent
   uses to time each pipeline step and read token usage off each
   agent's `last_usage_metadata` attribute. This is what powers the
   "System Monitor" panel in the Streamlit UI, and — critically — it
   works even if LangSmith is not configured (no API key / offline
   dev), which is the enterprise requirement that monitoring must not
   have a hard dependency on a third-party SaaS being reachable.

TOKEN EXTRACTION — WHY IT'S NOT AS SIMPLE AS "READ THE RETURN VALUE":
Each Supervisor step calls an agent METHOD (e.g. self.intent_agent.classify),
and that method returns a parsed value (IntentClassification, list[str],
str, or raw Neo4j data) — never the raw AIMessage LangChain gives you,
which is the only place token counts (.usage_metadata) actually live.
So instead of inspecting the return value, _extract_usage() looks at
the bound object the method belongs to (`fn.__self__` — i.e. the
IntentAgent/EntityAgent/ExplanationAgent instance) and reads
`last_usage_metadata`, which each agent sets internally right after
its own LLM call, before reducing the response down to whatever it
returns to the Supervisor. Steps with no such attribute (e.g. the
Neo4j tool call, which is a plain function, not an LLM call) simply
report 0 tokens, which is correct.

Exact LangSmith wiring (for reference / requirement H):

    # .env
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=ls__...
    LANGCHAIN_PROJECT=ArtistConnectionExplorer

    # any agent method
    from langsmith import traceable

    class IntentAgent:
        @traceable(name="intent_agent.classify")
        def classify(self, query: str) -> IntentClassification:
            ...

That's the entire integration — `traceable` reads the env vars above
and no-ops automatically when tracing is disabled, so it's always safe
to leave the decorator in place.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any, Callable, List, Optional

import config
from utils.logger import logger


@dataclass
class StepMetric:
    name: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    status: str = "success"
    error: Optional[str] = None


class LangSmithTracer:
    """One instance per incoming query. Collects a StepMetric for each
    pipeline stage the Supervisor Agent runs through."""

    def __init__(self):
        self.metrics: List[StepMetric] = []

    def trace_step(self, name: str, fn: Callable, *args, **kwargs) -> Any:
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            latency_ms = (time.perf_counter() - start) * 1000

            usage = self._extract_usage(fn, result)
            metric = StepMetric(
                name=name,
                latency_ms=latency_ms,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                cost_usd=self._estimate_cost(usage.get("total_tokens", 0)),
                status="success",
            )
            self.metrics.append(metric)
            logger.info(
                f"[trace] {name} OK latency={latency_ms:.1f}ms "
                f"tokens={metric.total_tokens} cost=${metric.cost_usd:.5f}"
            )
            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            metric = StepMetric(
                name=name, latency_ms=latency_ms, status="error", error=str(e)
            )
            self.metrics.append(metric)
            logger.error(f"[trace] {name} FAILED latency={latency_ms:.1f}ms error={e}")
            raise

    @staticmethod
    def _extract_usage(fn: Callable, result: Any) -> dict:
        """
        Best-effort extraction of token usage for a traced step.

        Preferred source: `last_usage_metadata` on the bound agent
        instance (fn.__self__) — this is how IntentAgent, EntityAgent,
        and ExplanationAgent expose real token counts even though their
        methods return parsed/plain values, not the raw AIMessage.

        Fallback: check the return value itself, in case some future
        step returns an AIMessage-like object directly.

        Steps with neither (e.g. a plain Neo4j tool call) correctly
        report 0 tokens — they never call an LLM.
        """
        owner = getattr(fn, "__self__", None)
        usage_metadata = getattr(owner, "last_usage_metadata", None) if owner is not None else None

        if not usage_metadata:
            usage_metadata = getattr(result, "usage_metadata", None)

        if usage_metadata:
            return {
                "input_tokens": usage_metadata.get("input_tokens", 0),
                "output_tokens": usage_metadata.get("output_tokens", 0),
                "total_tokens": usage_metadata.get("total_tokens", 0),
            }
        return {}

    @staticmethod
    def _estimate_cost(total_tokens: int) -> float:
        # Ollama is local/free by default -> COST_PER_1K_TOKENS is 0.0
        # unless the operator points MODEL_PROVIDER at a paid API model.
        return (total_tokens / 1000) * config.COST_PER_1K_TOKENS

    def summary(self) -> List[dict]:
        return [asdict(m) for m in self.metrics]

    def total_latency_ms(self) -> float:
        return sum(m.latency_ms for m in self.metrics)

    def total_tokens(self) -> int:
        return sum(m.total_tokens for m in self.metrics)

    def total_cost_usd(self) -> float:
        return sum(m.cost_usd for m in self.metrics)

    def had_failure(self) -> bool:
        return any(m.status == "error" for m in self.metrics)