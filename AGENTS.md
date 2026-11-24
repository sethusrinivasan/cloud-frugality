# Cloud Frugality — AI Agent Instructions & Auto-Discovery

This document provides autonomous AI agents, data analysts, and LLM tool orchestrators with immediate configuration, live endpoints, and MCP server discovery details.

## 1. Live Deployment Endpoints (AWS Lambda Function URLs)

Cloud Frugality is deployed as a dual-engine architecture in region `us-east-2`:

| Engine | Partition | Function URL | Health Endpoint |
|---|---|---|---|
| **Python Engine** (DuckDB / S3) | `frugality/python` | `https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/` | [/healthz](https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/healthz) |
| **Rust Engine** (Native Microservice) | `frugality/rust` | `https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/` | [/healthz](https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/healthz) |

Both engines now provide 100% API parity.

---

## 2. AI Data Resource URLs & Query Syntax

### 1,000,000-Record Paginated Telemetry API
- **Route**: `GET /ai/resource/paginated` (or `/api/resource/paginated`)
- **Python**: `https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/ai/resource/paginated`
- **Rust**: `https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/ai/resource/paginated`

#### Parameters:
- `page`: Integer (1-indexed, default `1`).
- `pageSize`: Integer (`1` to `10000`, default `1000`).
  - *Tip*: Send `Accept-Encoding: gzip` to retrieve full 10,000-record payloads without hitting AWS Lambda 6MB uncompressed payload limits.
- `sort_by`: `date`, `gross_usd`, `region`, `workload_type` (default: `date`).
- `sort_order`: `desc` or `asc` (default: `desc`).
- `start_date` / `end_date`: ISO format `YYYY-MM-DD` (e.g. `start_date=2026-11-01&end_date=2026-11-22`).
- `region`: AWS region code filter (e.g. `us-east-1`, `us-east-2`, `eu-west-1`, `ap-northeast-1`).
- `workload_type`: Archetype filter (`serverless_frugal`, `enterprise_microservices`, `ai_analytics_pipeline`, `global_web_edge`).

### Example Curl:
```bash
curl -s "https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/ai/resource/paginated?page=1&pageSize=5&sort_by=date&sort_order=desc"
```

### Self-Discovery Endpoint
Both engines expose the full OpenAPI/Agent specification at:
```bash
curl -s "https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/.well-known/agent-configuration.json"
```

---

## 3. Model Context Protocol (MCP) Server

AI agents can directly connect via standard stdio JSON-RPC 2.0 using either the Python or Rust engine.

### Connecting in Antigravity or Claude Desktop (`mcp_config.json`):
```json
{
  "mcpServers": {
    "cloud-frugality": {
      "command": "python3",
      "args": ["/home/home/github/cloud-frugality/src/python/mcp_server.py"]
    },
    "cloud-frugality-rust": {
      "command": "/home/home/github/cloud-frugality/src/rust/target/release/cloud-frugality",
      "args": ["mcp"]
    }
  }
}
```

### Available MCP Tools:
1. `get_health`: Returns health status, engine identity, backing source (Real AWS or Emulator), and partition.
2. `get_cost_summary`: Parameters: `window_days` (default 30). Returns pre-credit gross spend, net billed cash, budget runway, and top services.
3. `query_paginated_costs`: Parameters: `page`, `page_size`, `sort_by`, `sort_order`, `start_date`, `end_date`, `region`, `workload_type`. Queries the 1,000,000-record dataset.
4. `get_settings`: Returns daily baseline threshold ($USD) and budget plan settings.
5. `update_settings`: Parameters: `daily_baseline_usd`, `budget_type`, `monthly_credit_amount`, `monthly_reset_day`, `fixed_budget_amount`, `fixed_budget_expiry`.
6. `get_discovery_info`: Returns active URLs and endpoint documentation.
