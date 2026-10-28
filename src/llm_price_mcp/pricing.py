"""Fetching, caching and computing LLM prices (no MCP dependency, easy to test)."""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 3600
PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    id: str
    name: str
    provider: str
    context_length: int
    input_per_m: float  # USD per 1M input tokens
    output_per_m: float  # USD per 1M output tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None  # OpenRouter uses -1 for "variable" pricing


def parse_model(raw: dict[str, Any]) -> ModelPrice | None:
    """Convert one OpenRouter model entry into a ModelPrice. Returns None if unusable."""
    model_id = raw.get("id")
    pricing = raw.get("pricing") or {}
    prompt = _to_float(pricing.get("prompt"))
    completion = _to_float(pricing.get("completion"))
    if not model_id or prompt is None or completion is None:
        return None
    return ModelPrice(
        id=model_id,
        name=raw.get("name") or model_id,
        provider=model_id.split("/", 1)[0] if "/" in model_id else "unknown",
        context_length=int(raw.get("context_length") or 0),
        input_per_m=round(prompt * PER_MILLION, 6),
        output_per_m=round(completion * PER_MILLION, 6),
    )


class PriceCatalog:
    """Loads model prices from OpenRouter with a simple in-memory TTL cache."""

    def __init__(
        self,
        url: str = OPENROUTER_MODELS_URL,
        ttl: float = CACHE_TTL_SECONDS,
        timeout: float = 20.0,
    ) -> None:
        self.url = url
        self.ttl = ttl
        self.timeout = timeout
        self._models: list[ModelPrice] = []
        self._fetched_at: float = 0.0

    def _fetch(self) -> list[ModelPrice]:
        resp = httpx.get(self.url, timeout=self.timeout, headers={"User-Agent": "llm-price-mcp/0.1"})
        resp.raise_for_status()
        data = resp.json().get("data", [])
        models = [m for m in (parse_model(r) for r in data) if m is not None]
        return sorted(models, key=lambda m: m.id)

    def models(self, force_refresh: bool = False) -> list[ModelPrice]:
        now = time.monotonic()
        if force_refresh or not self._models or now - self._fetched_at > self.ttl:
            self._models = self._fetch()
            self._fetched_at = now
        return self._models

    # ---- queries -------------------------------------------------------

    def list_models(self, filter: str | None = None, limit: int = 50) -> list[ModelPrice]:
        items = self.models()
        if filter:
            terms = filter.lower().split()
            items = [
                m for m in items
                if all(t in f"{m.id} {m.name} {m.provider}".lower() for t in terms)
            ]
        return items[: max(limit, 0)]

    def find(self, model: str) -> ModelPrice | None:
        """Exact id match first, then a unique case-insensitive substring match."""
        key = model.strip().lower()
        items = self.models()
        for m in items:
            if m.id.lower() == key:
                return m
        hits = [m for m in items if key in m.id.lower() or key in m.name.lower()]
        return hits[0] if len(hits) == 1 else None

    def compare_cost(
        self, models: list[str], input_tokens: int, output_tokens: int
    ) -> dict[str, Any]:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be >= 0")
        results, not_found = [], []
        for name in models:
            m = self.find(name)
            if m is None:
                not_found.append(name)
                continue
            cost = estimate_cost(m, input_tokens, output_tokens)
            results.append({**m.to_dict(), "cost_usd": cost})
        results.sort(key=lambda r: r["cost_usd"])
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "results": results,
            "not_found": not_found,
        }

    def cheapest(
        self,
        min_context: int | None = None,
        keyword: str | None = None,
        limit: int = 10,
        include_free: bool = False,
        input_tokens: int = 1_000_000,
        output_tokens: int = 1_000_000,
    ) -> list[dict[str, Any]]:
        items = self.list_models(keyword, limit=10**9) if keyword else self.models()
        if min_context:
            items = [m for m in items if m.context_length >= min_context]
        if not include_free:
            items = [m for m in items if m.input_per_m > 0 or m.output_per_m > 0]
        ranked = sorted(
            ({**m.to_dict(), "cost_usd": estimate_cost(m, input_tokens, output_tokens)} for m in items),
            key=lambda r: (r["cost_usd"], r["id"]),
        )
        return ranked[: max(limit, 0)]


def estimate_cost(m: ModelPrice, input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens * m.input_per_m + output_tokens * m.output_per_m) / PER_MILLION, 8
    )
