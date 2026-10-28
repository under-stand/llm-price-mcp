import asyncio

import httpx
import pytest
import respx

from llm_price_mcp import server
from llm_price_mcp.pricing import OPENROUTER_MODELS_URL, PriceCatalog

FAKE = {"data": [
    {"id": "openai/gpt-x", "name": "GPT X", "context_length": 128000,
     "pricing": {"prompt": "0.000002", "completion": "0.000008"}},
    {"id": "deepseek/ds-chat", "name": "DeepSeek Chat", "context_length": 64000,
     "pricing": {"prompt": "0.00000027", "completion": "0.0000011"}},
]}


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == {
        "list_models", "compare_cost", "cheapest", "gpu_rental_prices", "estimate_self_host"}


def test_estimate_self_host_with_comparison(monkeypatch):
    with respx.mock() as router:
        router.get(OPENROUTER_MODELS_URL).mock(return_value=httpx.Response(200, json=FAKE))
        monkeypatch.setattr(server, "catalog", PriceCatalog())
        out = server.estimate_self_host(1000, 2.0, 1.0, ["gpt-x", "ds-chat", "nope"])
    assert out["self_host_usd_per_1m_tokens"] == pytest.approx(0.555556)
    assert [r["id"] for r in out["comparison"]] == ["deepseek/ds-chat", "openai/gpt-x"]
    ds, gx = out["comparison"]
    assert ds["self_host_cheaper_than_api_output"] is True and ds["api_output_per_1m"] == 1.1
    assert gx["self_host_vs_output_ratio"] == pytest.approx(0.0694, abs=1e-4)
    assert out["not_found"] == ["nope"]


def test_estimate_self_host_api_failure_keeps_estimate(monkeypatch):
    with respx.mock() as router:
        router.get(OPENROUTER_MODELS_URL).mock(return_value=httpx.Response(503))
        monkeypatch.setattr(server, "catalog", PriceCatalog())
        out = server.estimate_self_host(500, 1.0, compare_models=["gpt-x"])
    assert out["self_host_usd_per_1m_tokens"] == pytest.approx(0.555556)
    assert "comparison_error" in out


def test_estimate_self_host_without_comparison():
    out = server.estimate_self_host(100, 0.36, 0.5)
    assert out["self_host_usd_per_1m_tokens"] == pytest.approx(2.0)
    assert "comparison" not in out
