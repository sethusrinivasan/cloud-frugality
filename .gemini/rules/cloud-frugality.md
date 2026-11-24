# Cloud Frugality Auto-Discovery Rule for Antigravity Agents

When working in this repository or handling AWS cost, billing, or telemetry queries:

## Live Function URLs
- **Python Engine (DuckDB/S3)**: `https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/`
- **Rust Engine (Native AL2023)**: `https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/`

## 1,000,000 Record Paginated Dataset API
- Endpoint: `/ai/resource/paginated` or `/api/resource/paginated`
- Query parameters:
  - `page`: default 1
  - `pageSize`: default 1000 (up to 10000 with gzip)
  - `sort_by`: `date`, `gross_usd`, `region`, `workload_type`
  - `sort_order`: `desc` or `asc`
  - `start_date` / `end_date`: `YYYY-MM-DD`
  - `region`: e.g. `us-east-1`, `us-east-2`
  - `workload_type`: e.g. `serverless_frugal`, `enterprise_microservices`

## MCP Servers
- Python stdio server: `python3 src/python/mcp_server.py`
- Rust native server: `cloud-frugality mcp`
- Configured in `~/.gemini/config/mcp_config.json`.
- Discovered tools: `get_health`, `get_cost_summary`, `query_paginated_costs`, `get_settings`, `update_settings`, `get_discovery_info`.
