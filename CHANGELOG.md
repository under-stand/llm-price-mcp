# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-28

### Added
- `gpu_rental_prices(gpu?, provider?)` tool: per-GPU-hour rental prices (RunPod, Lambda, Vast.ai,
  AutoDL, …) with source URL and fetch date for every row; CNY prices converted to USD using the
  exchange rate in the same file. Reads `$LLM_PRICE_GPU_CSV`, else the newest
  `data/<YYYY-MM-DD>/gpu_prices.csv` under `$LLM_PRICE_TRACKER_DIR`
  (default `/workspace/price-tracker`), else a snapshot bundled in the package (dated 2026-10-28
  and labelled as a snapshot in the output). Returns an explicit message when nothing matches.
- `estimate_self_host(tokens_per_second, gpu_hourly_usd, utilization=1.0, compare_models?)` tool:
  self-hosting cost per 1M tokens, optionally compared with OpenRouter API prices.
- `--transport streamable-http` / `MCP_TRANSPORT` option (with `--host`/`--port`, `$PORT`).
- GitHub Actions CI (pytest on Python 3.10–3.12), `Dockerfile`, `smithery.yaml`, this changelog.
- Tests for the new tools (20 tests total).

### Changed
- Requires `mcp>=1.8.0` (Streamable HTTP support).
- README rewritten for the new tools, in Chinese and English.

## [0.1.0] - 2026-10-28

### Added
- Initial release: `list_models`, `compare_cost`, `cheapest` tools backed by OpenRouter's public
  models API with a 1-hour in-memory cache.
