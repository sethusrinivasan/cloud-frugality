import json
import pytest
from store import FrugalityStore
from mcp_server import process_message, handle_tool_call


def test_python_mcp_initialize():
    store = FrugalityStore()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    resp = process_message(req, store)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "cloud-frugality-python"


def test_python_mcp_tools_list():
    store = FrugalityStore()
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    }
    resp = process_message(req, store)
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "get_health" in tool_names
    assert "get_cost_summary" in tool_names
    assert "query_paginated_costs" in tool_names
    assert "get_settings" in tool_names
    assert "update_settings" in tool_names
    assert "get_discovery_info" in tool_names


def test_python_mcp_tool_execution():
    store = FrugalityStore()

    # 1. get_health
    res_health = handle_tool_call("get_health", {}, store)
    assert res_health["status"] == "healthy"
    assert "live_python_url" in res_health

    # 2. get_cost_summary
    res_cost = handle_tool_call("get_cost_summary", {"window_days": 30}, store)
    assert "window_gross_usd" in res_cost

    # 3. query_paginated_costs
    res_pag = handle_tool_call("query_paginated_costs", {"page": 1, "page_size": 5}, store)
    assert res_pag["total"] == 1_000_000
    assert len(res_pag["records"]) == 5

    # 4. get_discovery_info
    res_disc = handle_tool_call("get_discovery_info", {}, store)
    assert "live_endpoints" in res_disc
    assert res_disc["total_records"] == 1_000_000
