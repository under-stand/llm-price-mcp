"""MCP server exposing LLM pricing tools (stdio transport)."""

from __future__ import annotations

from typing import Any

try:  # mcp SDK >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .pricing import PriceCatalog

mcp = _Server("llm-price")
catalog = PriceCatalog()


@mcp.tool()
def list_models(filter: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List LLMs and their prices (USD per 1M tokens) from OpenRouter.

    Args:
        filter: Optional provider or keyword, e.g. "anthropic", "gpt", "deepseek coder".
            All space-separated terms must match the model id/name.
        limit: Max number of models to return (default 50).
    """
    models = catalog.list_models(filter, limit=limit)
    return {"count": len(models), "models": [m.to_dict() for m in models]}


@mcp.tool()
def compare_cost(models: list[str], input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """Estimate and rank the cost (USD) of a workload across several models, cheapest first.

    Args:
        models: Model ids such as "openai/gpt-4o-mini" (a unique substring also works).
        input_tokens: Number of prompt/input tokens.
        output_tokens: Number of completion/output tokens.
    """
    return catalog.compare_cost(models, input_tokens, output_tokens)


@mcp.tool()
def cheapest(
    min_context: int | None = None,
    keyword: str | None = None,
    limit: int = 10,
    include_free: bool = False,
) -> dict[str, Any]:
    """Return the cheapest models, ranked by cost of 1M input + 1M output tokens.

    Args:
        min_context: Only models with at least this context window (tokens).
        keyword: Optional provider/keyword filter, e.g. "qwen".
        limit: How many models to return (default 10).
        include_free: Include $0 models (often rate-limited); default False.
    """
    results = catalog.cheapest(min_context, keyword, limit, include_free)
    return {"basis": "1M input + 1M output tokens", "count": len(results), "models": results}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
