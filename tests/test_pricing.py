import httpx
import pytest
import respx

from llm_price_mcp.pricing import OPENROUTER_MODELS_URL, PriceCatalog, parse_model

FAKE = {
    "data": [
        {"id": "openai/gpt-x", "name": "OpenAI: GPT X", "context_length": 128000,
         "pricing": {"prompt": "0.000002", "completion": "0.000008"}},
        {"id": "anthropic/claude-y", "name": "Anthropic: Claude Y", "context_length": 200000,
         "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
        {"id": "deepseek/ds-chat", "name": "DeepSeek Chat", "context_length": 64000,
         "pricing": {"prompt": "0.00000027", "completion": "0.0000011"}},
        {"id": "meta/llama-free:free", "name": "Llama Free", "context_length": 8000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openrouter/auto", "name": "Auto router", "context_length": 2000000,
         "pricing": {"prompt": "-1", "completion": "-1"}},
        {"id": "broken/no-pricing", "name": "Broken"},
    ]
}


@pytest.fixture
def catalog():
    with respx.mock(assert_all_called=False) as router:
        route = router.get(OPENROUTER_MODELS_URL).mock(return_value=httpx.Response(200, json=FAKE))
        cat = PriceCatalog()
        cat._route = route  # expose for assertions
        yield cat


def test_parse_skips_variable_and_missing():
    assert parse_model(FAKE["data"][4]) is None
    assert parse_model(FAKE["data"][5]) is None
    m = parse_model(FAKE["data"][0])
    assert m.provider == "openai" and m.input_per_m == 2.0 and m.output_per_m == 8.0


def test_list_models_filter(catalog):
    assert len(catalog.list_models()) == 4
    ids = [m.id for m in catalog.list_models("anthropic")]
    assert ids == ["anthropic/claude-y"]
    assert [m.id for m in catalog.list_models("deepseek chat")] == ["deepseek/ds-chat"]


def test_cache_hits_network_once(catalog):
    catalog.list_models()
    catalog.list_models("gpt")
    catalog.cheapest()
    assert catalog._route.call_count == 1
    catalog.models(force_refresh=True)
    assert catalog._route.call_count == 2


def test_cache_expires(catalog):
    catalog.ttl = 0
    catalog.models()
    catalog.models()
    assert catalog._route.call_count == 2


def test_compare_cost_sorted(catalog):
    out = catalog.compare_cost(["openai/gpt-x", "claude-y", "ds-chat", "nope/none"], 1_000_000, 500_000)
    costs = [(r["id"], r["cost_usd"]) for r in out["results"]]
    assert costs == [
        ("deepseek/ds-chat", pytest.approx(0.82)),
        ("openai/gpt-x", pytest.approx(6.0)),
        ("anthropic/claude-y", pytest.approx(10.5)),
    ]
    assert out["not_found"] == ["nope/none"]


def test_compare_cost_rejects_negative(catalog):
    with pytest.raises(ValueError):
        catalog.compare_cost(["openai/gpt-x"], -1, 0)


def test_cheapest(catalog):
    res = catalog.cheapest(limit=2)
    assert [r["id"] for r in res] == ["deepseek/ds-chat", "openai/gpt-x"]
    assert catalog.cheapest(min_context=150000)[0]["id"] == "anthropic/claude-y"
    assert catalog.cheapest(include_free=True)[0]["id"] == "meta/llama-free:free"
    assert [r["id"] for r in catalog.cheapest(keyword="openai")] == ["openai/gpt-x"]


def test_http_error_propagates():
    with respx.mock() as router:
        router.get(OPENROUTER_MODELS_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            PriceCatalog().models()
