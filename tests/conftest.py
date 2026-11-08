import pytest

from llm_price_mcp import gpu


@pytest.fixture(autouse=True)
def no_live_gpu_feed(monkeypatch):
    """Keep every test offline: the live Runcrate feed is only exercised where a test mocks it."""
    monkeypatch.setattr(gpu, "fetch_runcrate_rows", lambda: ([], ""))
