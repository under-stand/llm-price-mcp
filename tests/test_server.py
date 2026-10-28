import asyncio

from llm_price_mcp import server


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == {"list_models", "compare_cost", "cheapest"}
