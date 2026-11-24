---
name: cloud-frugality
description: Automatic discovery and query tools for Cloud Frugality live AWS endpoints, 1M-record paginated dataset, and MCP server.
---

# Cloud Frugality Skill

Use this skill when interacting with Cloud Frugality telemetry, billing budgets, or the 1,000,000 multi-region usage dataset.

## Live Endpoints
- **Python**: `https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/`
- **Rust**: `https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/`

## Key API Routes
1. `/ai/resource/paginated`: 1M records with pagination, sorting, and date filters.
2. `/ai/resource`: Alibaba Cloud Quick BI / Databricks summary (`resource=daily` or `resource=services`).
3. `/healthz`: Runtime health, engine, and backing source verification.
4. `/.well-known/agent-configuration.json`: Full machine-readable agent discovery JSON.

## MCP Execution
Run locally:
```bash
python3 src/python/mcp_server.py
# or
./src/rust/target/debug/cloud-frugality mcp
```
Tools exposed: `get_health`, `get_cost_summary`, `query_paginated_costs`, `get_settings`, `update_settings`.
