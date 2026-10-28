"""MCP server exposing LLM pricing tools (stdio transport)."""

from __future__ import annotations

import argparse
import os
from typing import Any

try:  # mcp SDK >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server

    _SDK_V2 = True
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

    _SDK_V2 = False

from . import __version__
from . import gpu as gpu_mod
from .pricing import PriceCatalog

try:
    mcp = _Server("llm-price", version=__version__)
except TypeError:  # older SDKs without a version argument
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


@mcp.tool()
def gpu_rental_prices(gpu: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """GPU rental prices per GPU-hour (RunPod, Lambda, Vast.ai, AutoDL, ...), cheapest first.

    Data comes from the newest price-tracker CSV (data/<date>/gpu_prices.csv), or the file in
    the LLM_PRICE_GPU_CSV env var, falling back to a dated snapshot bundled with the package.
    Each row carries its source URL and fetch date; CNY prices are also converted to USD.

    Args:
        gpu: Optional GPU name filter, e.g. "H100", "a100 sxm", "4090" (all terms must match).
        provider: Optional provider filter, e.g. "runpod", "lambda", "vast", "autodl".
    """
    return gpu_mod.gpu_rental_prices(gpu=gpu, provider=provider)


@mcp.tool()
def estimate_self_host(
    tokens_per_second: float,
    gpu_hourly_usd: float,
    utilization: float = 1.0,
    compare_models: list[str] | None = None,
) -> dict[str, Any]:
    """Estimate the USD cost per 1M tokens of self-hosting a model on rented GPUs.

    cost_per_1M = gpu_hourly_usd / (tokens_per_second * 3600 * utilization) * 1,000,000

    Args:
        tokens_per_second: Sustained aggregate throughput of the deployment (all concurrent
            requests together), in generated tokens per second.
        gpu_hourly_usd: Total hourly cost of the GPUs serving that throughput (e.g. 8 x price).
        utilization: Fraction of paid hours actually spent serving traffic, in (0, 1]. Default 1.0.
        compare_models: Optional OpenRouter model ids (unique substrings work) to compare
            against their API input/output prices per 1M tokens.
    """
    cost = gpu_mod.self_host_cost_per_million(tokens_per_second, gpu_hourly_usd, utilization)
    out: dict[str, Any] = {
        "self_host_usd_per_1m_tokens": cost,
        "inputs": {
            "tokens_per_second": tokens_per_second,
            "gpu_hourly_usd": gpu_hourly_usd,
            "utilization": utilization,
        },
        "effective_tokens_per_hour": round(tokens_per_second * 3600 * utilization, 2),
        "assumptions": "Counts only GPU rental; excludes storage, egress, ops labour and idle "
                       "capacity beyond `utilization`. Throughput should be measured for your model, "
                       "batch size and sequence lengths.",
    }
    if compare_models:
        try:
            results, not_found = [], []
            for name in compare_models:
                m = catalog.find(name)
                if m is None:
                    not_found.append(name)
                    continue
                results.append({
                    "id": m.id,
                    "api_input_per_1m": m.input_per_m,
                    "api_output_per_1m": m.output_per_m,
                    "self_host_vs_output_ratio": (
                        round(cost / m.output_per_m, 4) if m.output_per_m > 0 else None
                    ),
                    "self_host_cheaper_than_api_output": cost < m.output_per_m,
                })
            out["comparison"] = sorted(results, key=lambda r: r["api_output_per_1m"])
            out["not_found"] = not_found
        except Exception as exc:  # network errors should not hide the self-host estimate
            out["comparison_error"] = f"Could not load API prices from OpenRouter: {exc}"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="llm-price-mcp", description=__doc__)
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport (default: stdio, or $MCP_TRANSPORT).",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8081")))
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
        return
    if _SDK_V2:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:  # mcp SDK 1.x: host/port live on settings
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
