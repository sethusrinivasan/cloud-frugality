#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for Cloud Frugality in Python.

Provides AI agents direct access to:
- 1,000,000 multi-region AWS usage dataset with date filtering and pagination.
- Real AWS Cost Explorer telemetry, spend forecasting, and credit runway calculations.
- Live system health, backing source partition, and settings configuration.

Communicates over standard JSON-RPC 2.0 via standard input/output (stdio).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

# Add parent directories to sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (HERE, os.path.join(PROJECT_ROOT, "src"), os.path.join(PROJECT_ROOT, "src", "python")):
    if p not in sys.path:
        sys.path.insert(0, p)

from store import FrugalityStore, get_backing_source_info
from paginator import get_paginated_records
try:
    from duckdb_s3 import query_paginated_from_s3
except ImportError:
    query_paginated_from_s3 = None


def get_health_info() -> Dict[str, Any]:
    src = get_backing_source_info()
    return {
        "status": "healthy",
        "service": "cloud-frugality",
        "engine": "DuckDB over S3/Local Parquet",
        "runtime": f"python {sys.version.split()[0]}",
        "platform": sys.platform,
        "backing_source": src.get("source_type", "Real AWS"),
        "is_emulator": src.get("is_emulator", False),
        "partition": src.get("partition", "frugality/python"),
        "source_detail": src.get("detail", ""),
        "live_python_url": "https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/",
        "live_rust_url": "https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/",
    }


def handle_tool_call(name: str, args: Dict[str, Any], store: FrugalityStore) -> Dict[str, Any]:
    if name == "get_health":
        return get_health_info()

    elif name == "get_cost_summary":
        window_days = int(args.get("window_days", 30))
        return store.query_cost_summary(window_days=window_days)

    elif name == "query_paginated_costs":
        page = int(args.get("page", 1))
        page_size = int(args.get("page_size", 1000))
        sort_by = str(args.get("sort_by", "date"))
        sort_order = str(args.get("sort_order", "desc"))
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        region = args.get("region")
        workload = args.get("workload_type")

        if query_paginated_from_s3 is not None:
            data, err = query_paginated_from_s3(
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                start_date=start_date,
                end_date=end_date,
                region_filter=region,
                workload_filter=workload,
            )
            if err:
                raise ValueError(err)
            return data
        else:
            data, err = get_paginated_records(
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            if err:
                raise ValueError(err)
            return data

    elif name == "get_settings":
        return store.get_settings()

    elif name == "update_settings":
        current = store.get_settings()
        if "daily_baseline_usd" in args:
            current["daily_baseline_usd"] = round(float(args["daily_baseline_usd"]), 2)
        if "budget_type" in args:
            current["budget_type"] = str(args["budget_type"])
        if "monthly_credit_amount" in args:
            current["monthly_credit_amount"] = round(float(args["monthly_credit_amount"]), 2)
        if "monthly_reset_day" in args:
            current["monthly_reset_day"] = max(1, min(31, int(args["monthly_reset_day"])))
        if "fixed_budget_amount" in args:
            current["fixed_budget_amount"] = round(float(args["fixed_budget_amount"]), 2)
        if "fixed_budget_expiry" in args:
            current["fixed_budget_expiry"] = str(args["fixed_budget_expiry"])
        return store.save_settings(current)

    elif name == "get_discovery_info":
        return {
            "name": "Cloud Frugality AI Resource Engine",
            "version": "0.1.0",
            "live_endpoints": {
                "python_engine_url": "https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/",
                "rust_engine_url": "https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/",
            },
            "paginated_api": "/ai/resource/paginated",
            "legacy_api": "/ai/resource",
            "total_records": 1000000,
        }

    else:
        raise ValueError(f"Unknown tool: {name}")


def process_message(req: Dict[str, Any], store: FrugalityStore) -> Optional[Dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")

    # Notifications
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "cloud-frugality-python",
                    "version": "0.1.0",
                },
            },
        }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_health",
                        "description": "Checks Cloud Frugality system health, active runtime engine, partition, and backing source.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "get_cost_summary",
                        "description": "Retrieves 30-day AWS spend summary, top services breakdown, daily records, and promotional credit runway.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "window_days": {"type": "integer", "description": "Number of days (default: 30)"}
                            },
                        },
                    },
                    {
                        "name": "query_paginated_costs",
                        "description": "Queries the 1,000,000-record multi-region AWS usage dataset with date filtering, dimension filtering, multi-column sorting, and pagination.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "page": {"type": "integer", "description": "Page number (1-indexed, default: 1)"},
                                "page_size": {"type": "integer", "description": "Page size (1 to 10000, default: 1000)"},
                                "sort_by": {"type": "string", "description": "Sort field ('date', 'gross_usd', 'region', 'workload_type')"},
                                "sort_order": {"type": "string", "description": "Sort order ('asc' or 'desc')"},
                                "start_date": {"type": "string", "description": "Optional ISO start date (YYYY-MM-DD)"},
                                "end_date": {"type": "string", "description": "Optional ISO end date (YYYY-MM-DD)"},
                                "region": {"type": "string", "description": "Optional AWS region code (e.g. 'us-east-1', 'us-east-2')"},
                                "workload_type": {"type": "string", "description": "Optional workload archetype filter"},
                            },
                        },
                    },
                    {
                        "name": "get_settings",
                        "description": "Retrieves current daily cost baseline and budget settings.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "update_settings",
                        "description": "Updates daily cost baseline ($USD) and budget plan configuration.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "daily_baseline_usd": {"type": "number"},
                                "budget_type": {"type": "string"},
                                "monthly_credit_amount": {"type": "number"},
                                "monthly_reset_day": {"type": "integer"},
                                "fixed_budget_amount": {"type": "number"},
                                "fixed_budget_expiry": {"type": "string"},
                            },
                        },
                    },
                    {
                        "name": "get_discovery_info",
                        "description": "Discovers live AWS Function URLs for Python and Rust engines, API paths, and documentation.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            },
        }

    elif method == "tools/call":
        params = req.get("params") or {}
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}

        try:
            res = handle_tool_call(tool_name, tool_args, store)
            text_output = json.dumps(res, indent=2)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_output,
                        }
                    ]
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                },
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }


def main():
    store = FrugalityStore()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = process_message(req, store)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(exc)}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
