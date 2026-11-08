# llm-price-mcp

[![CI](https://github.com/under-stand/llm-price-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/under-stand/llm-price-mcp/actions/workflows/ci.yml)

> 让 AI Agent 查询、比较大模型 API 价格、GPU 租赁价格和自建推理成本的 MCP Server · An MCP server that lets AI agents compare LLM API prices, GPU rental prices and self-hosting cost.

- 模型 API 价格来自 [OpenRouter 公开模型接口](https://openrouter.ai/api/v1/models)（无需 API Key），内存缓存 1 小时。
- GPU 租赁价格来自 price-tracker 生成的 `gpu_prices.csv`（RunPod / Lambda / Vast.ai / AutoDL 等），每行带来源 URL 与抓取日期；没有本地数据时使用包内自带的快照（2026-11-02；其中 AutoDL 为手工值，日期 2026-10-28），并在输出中注明。
- LLM prices come from OpenRouter's public models endpoint (no API key), cached for 1 hour.
- GPU rental prices come from a price-tracker `gpu_prices.csv` (RunPod / Lambda / Vast.ai / AutoDL …), each row with its source URL and fetch date; without local data a bundled, clearly dated snapshot (2026-11-02; AutoDL rows are manual values dated 2026-10-28) is used.

当前版本 / Version: **0.2.0** — 见 / see [CHANGELOG.md](CHANGELOG.md).

---

## 中文

### 功能（工具）

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_models` | `filter`（可选，厂商/关键词，多个词用空格分隔，需全部匹配）、`limit`（默认 50） | 列出模型及价格（美元 / 百万 token） |
| `compare_cost` | `models`（模型 id 列表，唯一子串也可）、`input_tokens`、`output_tokens` | 计算给定用量在各模型上的成本（美元），从低到高排序；找不到的模型列在 `not_found` |
| `cheapest` | `min_context`（可选）、`keyword`（可选）、`limit`（默认 10）、`include_free`（默认 false） | 按「100 万输入 + 100 万输出 token」的成本给出最便宜的模型 |
| `gpu_rental_prices` | `gpu`（可选，如 `H100`、`a100 sxm`、`4090`，多个词需全部匹配，忽略大小写/空格/连字符）、`provider`（可选，如 `runpod`、`lambda`、`vast`、`autodl`） | 每卡每小时租赁价格，按美元价从低到高；含原币种价格、`usd_per_hour`（人民币按同文件汇率折算）、来源 URL、抓取日期、数据文件路径；无匹配时返回明确提示，不编造数据 |
| `estimate_self_host` | `tokens_per_second`、`gpu_hourly_usd`、`utilization`（默认 1.0）、`compare_models`（可选，模型 id 列表） | 自建推理每百万 token 成本，并可与指定 API 模型的输入/输出单价对比 |

说明：OpenRouter 中价格为“可变”（如 `openrouter/auto` 路由）的模型会被跳过；免费模型（通常有限流）默认不参与 `cheapest` 排序。

#### GPU 数据来源（按优先级）

1. 环境变量 `LLM_PRICE_GPU_CSV`：指定 CSV 文件路径（文件不存在时直接报错，不会悄悄换用其他数据）；
2. `LLM_PRICE_TRACKER_DIR`（默认 `/workspace/price-tracker`）下最新一期 `data/<YYYY-MM-DD>/gpu_prices.csv`；
3. 包内快照 `src/llm_price_mcp/data/gpu_prices_snapshot.csv`，输出中带 `source_kind: "bundled-snapshot"`、`snapshot_date` 和过期提醒。

另外，[Runcrate](https://www.runcrate.ai/pricing)（一家 AI 云）的行不来自 CSV：除非设置了 `LLM_PRICE_GPU_CSV`，否则每次调用都会从其公开接口 `https://www.runcrate.ai/api/gpu-pricing`（无需 Key）实时读取并合并。只收录接口能明确区分型号的 GPU（接口不区分 SXM/PCIe，因此不含 H100 和 A100），且跳过无库存的型号；接口不可用时仍返回 CSV 数据，并在输出中给出 `live_error`。

CSV 列：`provider,gpu,variant,price_per_hour,currency,note,source,fetch_date`；`provider=FX, gpu=USD/CNY` 一行为汇率。价格为空的行（如 Vast.ai 当期无报价）会被跳过。

#### 自建成本公式

```
每百万 token 成本（美元）= gpu_hourly_usd / (tokens_per_second × 3600 × utilization) × 1,000,000
```

`tokens_per_second` 应是整套部署在实际并发下的总吞吐，`gpu_hourly_usd` 是对应全部 GPU 的小时费用（如 8 卡 × 单价）。只计 GPU 租金，不含存储、流量、运维和闲置（`utilization` 之外）。对比时以 API 的输出单价为主要参照（`self_host_vs_output_ratio` < 1 表示自建更便宜）。

### 安装

需要 Python ≥ 3.10。推荐使用 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/under-stand/llm-price-mcp.git
cd llm-price-mcp
uv venv && uv pip install -e .
# 或：python -m venv .venv && .venv/bin/pip install -e .
```

> 仓库地址默认是 `under-stand/llm-price-mcp`；如果你 fork 或改了 GitHub 用户名，替换成自己的即可。

本地试运行（stdio 传输）：

```bash
.venv/bin/llm-price-mcp
# 或使用 MCP Inspector 调试：
npx @modelcontextprotocol/inspector .venv/bin/llm-price-mcp
# Streamable HTTP（端点 http://localhost:8081/mcp）：
.venv/bin/llm-price-mcp --transport streamable-http --port 8081
```

### Docker

```bash
docker build -t llm-price-mcp .
docker run -i --rm llm-price-mcp                                   # stdio
docker run --rm -p 8081:8081 -e MCP_TRANSPORT=streamable-http llm-price-mcp   # HTTP /mcp
# 使用更新的 GPU 数据：
docker run -i --rm -v /path/to/price-tracker:/data -e LLM_PRICE_TRACKER_DIR=/data llm-price-mcp
```

### Smithery

仓库根目录的 `smithery.yaml` 采用 Smithery 的 container 运行时格式（构建 `Dockerfile`，以 Streamable HTTP 提供 `/mcp`）。注意：Smithery 现行文档主推「填写公网 URL」或「上传 MCPB 包」的发布方式，`smithery.yaml` 参考页已从现行文档移除，发布前请以 Smithery 当时的说明为准。

### 在 Claude Desktop 中配置

编辑 `claude_desktop_config.json`（macOS：`~/Library/Application Support/Claude/`，Windows：`%APPDATA%\Claude\`）：

```json
{
  "mcpServers": {
    "llm-price": {
      "command": "uv",
      "args": ["--directory", "/绝对路径/llm-price-mcp", "run", "llm-price-mcp"]
    }
  }
}
```

### 在 Cursor 中配置

编辑 `~/.cursor/mcp.json`（全局）或项目内 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "llm-price": {
      "command": "/绝对路径/llm-price-mcp/.venv/bin/llm-price-mcp",
      "args": []
    }
  }
}
```

配置后可以直接问 Agent：“帮我比较 gpt-4o-mini、deepseek-chat、mistral-nemo 处理 200 万输入、50 万输出 token 的费用”，“上下文至少 128k 的最便宜的 5 个模型是哪些？”，“现在租 H100 最便宜的是哪家？”，或“一张 2.69 美元/小时的 H100 跑到 1500 token/s、利用率 60%，和 deepseek-chat API 比哪个便宜？”

如需指定 GPU 数据文件，可在配置里加 `"env": {"LLM_PRICE_GPU_CSV": "/绝对路径/gpu_prices.csv"}`。

### 开发与测试

```bash
uv pip install -e '.[dev]'
.venv/bin/pytest -q          # 网络请求均已 mock，离线可跑
```

---

## English

### Tools

| Tool | Arguments | Description |
| --- | --- | --- |
| `list_models` | `filter` (optional provider/keyword; space-separated terms must all match), `limit` (default 50) | List models with prices in USD per 1M tokens |
| `compare_cost` | `models` (list of model ids; a unique substring works too), `input_tokens`, `output_tokens` | Estimated USD cost of the workload per model, sorted cheapest first; unknown names go to `not_found` |
| `cheapest` | `min_context` (optional), `keyword` (optional), `limit` (default 10), `include_free` (default false) | Cheapest models ranked by the cost of 1M input + 1M output tokens |
| `gpu_rental_prices` | `gpu` (optional, e.g. `H100`, `a100 sxm`, `4090`; all terms must match, case/space/dash-insensitive), `provider` (optional, e.g. `runpod`, `lambda`, `vast`, `autodl`) | Per-GPU-hour rental prices, cheapest (USD) first, with original currency, `usd_per_hour` (CNY converted with the FX row in the same file), source URL, fetch date and data file; an explicit message when nothing matches — no invented data |
| `estimate_self_host` | `tokens_per_second`, `gpu_hourly_usd`, `utilization` (default 1.0), `compare_models` (optional list of model ids) | Self-hosting cost per 1M tokens, optionally compared with API input/output prices |

Models with variable pricing (e.g. the `openrouter/auto` router) are skipped. Free models (usually rate-limited) are excluded from `cheapest` unless `include_free=true`.

#### GPU data source (in order)

1. `LLM_PRICE_GPU_CSV`: explicit CSV path (a missing file is reported as an error, never silently replaced);
2. the newest `data/<YYYY-MM-DD>/gpu_prices.csv` under `LLM_PRICE_TRACKER_DIR` (default `/workspace/price-tracker`);
3. the bundled snapshot `src/llm_price_mcp/data/gpu_prices_snapshot.csv`; the output then carries `source_kind: "bundled-snapshot"`, `snapshot_date` and a staleness notice.

Separately, Runcrate (an AI cloud) rows do not come from the CSV: unless `LLM_PRICE_GPU_CSV` is set, they are fetched live on each call from its public feed `https://www.runcrate.ai/api/gpu-pricing` (no key) and merged in. Only GPUs the feed names unambiguously are listed (the feed does not say SXM vs PCIe, so H100 and A100 are left out) and out-of-stock types are skipped. If the feed is unreachable the CSV data is still returned, with a `live_error` field.

CSV columns: `provider,gpu,variant,price_per_hour,currency,note,source,fetch_date`; the `provider=FX, gpu=USD/CNY` row holds the exchange rate. Rows with an empty price are skipped.

#### Self-hosting formula

```
USD per 1M tokens = gpu_hourly_usd / (tokens_per_second × 3600 × utilization) × 1,000,000
```

Use the deployment's aggregate throughput under real concurrency and the hourly cost of all its GPUs. Only GPU rent is counted (no storage, egress, ops or idle time beyond `utilization`). Compare mainly against the API output price (`self_host_vs_output_ratio` < 1 means self-hosting is cheaper).

### Install

Python ≥ 3.10. With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/under-stand/llm-price-mcp.git
cd llm-price-mcp
uv venv && uv pip install -e .
# or: python -m venv .venv && .venv/bin/pip install -e .
```

Run locally (stdio): `.venv/bin/llm-price-mcp`, or debug with
`npx @modelcontextprotocol/inspector .venv/bin/llm-price-mcp`.
Streamable HTTP: `.venv/bin/llm-price-mcp --transport streamable-http --port 8081` (endpoint `/mcp`).

### Docker

```bash
docker build -t llm-price-mcp .
docker run -i --rm llm-price-mcp                                              # stdio
docker run --rm -p 8081:8081 -e MCP_TRANSPORT=streamable-http llm-price-mcp   # HTTP /mcp
docker run -i --rm -v /path/to/price-tracker:/data -e LLM_PRICE_TRACKER_DIR=/data llm-price-mcp
```

### Smithery

`smithery.yaml` uses Smithery's container-runtime format (builds the `Dockerfile`, serves Streamable HTTP at `/mcp`). Smithery's current docs favour publishing by public URL or as an MCPB bundle and no longer list the `smithery.yaml` reference page, so check Smithery's instructions at publish time.

To point the server at a specific GPU CSV, add `"env": {"LLM_PRICE_GPU_CSV": "/absolute/path/gpu_prices.csv"}` to the client config.

### Claude Desktop

```json
{
  "mcpServers": {
    "llm-price": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/llm-price-mcp", "run", "llm-price-mcp"]
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "llm-price": {
      "command": "/absolute/path/to/llm-price-mcp/.venv/bin/llm-price-mcp",
      "args": []
    }
  }
}
```

### Development

```bash
uv pip install -e '.[dev]'
.venv/bin/pytest -q   # all network calls are mocked
```

### Disclaimer

GPU prices are on-demand list prices captured on the stated fetch date (RunPod/Lambda/Vast.ai/AutoDL pages and APIs); marketplace prices such as Vast.ai change constantly and AutoDL prices are before member discounts.
GPU 价格为抓取日期当天的按需标价；Vast.ai 等市场价格变化很快，AutoDL 为会员折扣前价格。

Prices are OpenRouter's listed prices and may differ from a provider's direct pricing, tiered/long-context pricing, caching discounts or batch discounts. Always verify before making budget decisions.
价格为 OpenRouter 标价，可能与厂商直连价、长上下文阶梯价、缓存/批量折扣不同，做预算前请自行核实。

---

## 变现思路 / Monetization ideas

简短、务实，不保证收入：

1. **免费开源基础版（本仓库）**：MIT 协议，用来获取 GitHub Star、在 MCP 目录（如 Smithery、mcp.so、Glama）上架，积累用户和信任。
2. **付费托管版**：提供远程 HTTP/SSE 端点 + API Key，免去用户本地安装；按调用量或月订阅（例如每月几美元的个人档）收费。可同时提供一个普通 REST API，服务不用 MCP 的开发者。
3. **更多数据源与数据质量**：在付费版中合并厂商官方直连价格（OpenAI、Anthropic、Google、DeepSeek、国内厂商等）、缓存/批量折扣、阶梯价、历史价格曲线和降价提醒——这些是免费版没有、且维护有成本的部分。
4. **团队功能**：按团队实际用量做成本预测、模型选型建议报告、预算告警。

先验证：观察 Star / 安装量和 issue 里的真实需求，再决定做哪个付费功能；在有人愿意付费之前，不要先投入大量开发。

1. **Free open-source core (this repo)** for stars, MCP-directory listings and trust.
2. **Hosted paid version**: remote HTTP endpoint with API keys, priced per usage or a small monthly plan; optionally a plain REST API too.
3. **More data sources**: direct provider pricing, cache/batch discounts, tiered pricing, price history and drop alerts.
4. **Team features**: cost forecasting from real usage, model-selection reports, budget alerts.

Validate demand (stars, installs, issues) before building paid features.

## License

[MIT](LICENSE)
