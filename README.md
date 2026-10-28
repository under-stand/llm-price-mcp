# llm-price-mcp

> 让 AI Agent 查询、比较大模型 API 价格的 MCP Server · An MCP server that lets AI agents look up and compare LLM API prices.

数据来自 [OpenRouter 公开模型接口](https://openrouter.ai/api/v1/models)（无需 API Key），内存缓存 1 小时。
Data comes from OpenRouter's public models endpoint (no API key required), cached in memory for 1 hour.

---

## 中文

### 功能（工具）

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_models` | `filter`（可选，厂商/关键词，多个词用空格分隔，需全部匹配）、`limit`（默认 50） | 列出模型及价格（美元 / 百万 token） |
| `compare_cost` | `models`（模型 id 列表，唯一子串也可）、`input_tokens`、`output_tokens` | 计算给定用量在各模型上的成本（美元），从低到高排序；找不到的模型列在 `not_found` |
| `cheapest` | `min_context`（可选）、`keyword`（可选）、`limit`（默认 10）、`include_free`（默认 false） | 按「100 万输入 + 100 万输出 token」的成本给出最便宜的模型 |

说明：OpenRouter 中价格为“可变”（如 `openrouter/auto` 路由）的模型会被跳过；免费模型（通常有限流）默认不参与 `cheapest` 排序。

### 安装

需要 Python ≥ 3.10。推荐使用 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/<your-name>/llm-price-mcp.git
cd llm-price-mcp
uv venv && uv pip install -e .
# 或：pip install -e .
```

本地试运行（stdio 传输）：

```bash
.venv/bin/llm-price-mcp
# 或使用 MCP Inspector 调试：
npx @modelcontextprotocol/inspector .venv/bin/llm-price-mcp
```

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

配置后可以直接问 Agent：“帮我比较 gpt-4o-mini、deepseek-chat、mistral-nemo 处理 200 万输入、50 万输出 token 的费用”，或“上下文至少 128k 的最便宜的 5 个模型是哪些？”

### 开发与测试

```bash
uv pip install -e '.[dev]'
pytest -q          # 网络请求均已 mock，离线可跑
```

---

## English

### Tools

| Tool | Arguments | Description |
| --- | --- | --- |
| `list_models` | `filter` (optional provider/keyword; space-separated terms must all match), `limit` (default 50) | List models with prices in USD per 1M tokens |
| `compare_cost` | `models` (list of model ids; a unique substring works too), `input_tokens`, `output_tokens` | Estimated USD cost of the workload per model, sorted cheapest first; unknown names go to `not_found` |
| `cheapest` | `min_context` (optional), `keyword` (optional), `limit` (default 10), `include_free` (default false) | Cheapest models ranked by the cost of 1M input + 1M output tokens |

Models with variable pricing (e.g. the `openrouter/auto` router) are skipped. Free models (usually rate-limited) are excluded from `cheapest` unless `include_free=true`.

### Install

Python ≥ 3.10. With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/<your-name>/llm-price-mcp.git
cd llm-price-mcp
uv venv && uv pip install -e .
# or: pip install -e .
```

Run locally (stdio): `.venv/bin/llm-price-mcp`, or debug with
`npx @modelcontextprotocol/inspector .venv/bin/llm-price-mcp`.

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
pytest -q   # all network calls are mocked
```

### Disclaimer

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
