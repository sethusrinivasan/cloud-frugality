"""
Unit tests for Cloud Frugality web portal, settings management, and UI requirements.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

from metrics import LatencyTracker
import web


def test_latency_tracker():
    tracker = LatencyTracker()
    tracker.record("DuckDB Analytics", "Query daily_costs", 4.5)
    tracker.record("Amazon S3", "GetObject config.json", 12.0)

    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert summary["total_ms"] == 16.5
    assert len(summary["services"]) == 2


def test_dashboard_html_rendering_requirements():
    res = web.lambda_handler({"rawPath": "/", "httpMethod": "GET"}, None)
    assert res["statusCode"] == 200
    assert "text/html" in res["headers"]["Content-Type"]
    html = res["body"]

    # 1. Branding
    assert "Cloud Frugality" in html
    assert "Tag: Frugality" in html

    # 2. Credits Remaining card title change (Promotional Credits Remaining -> Credits Remaining)
    assert "Credits Remaining" in html
    assert "Promotional Credits Remaining" not in html

    # 3. Breakdown by ApplicationName tag (30-day roll-up, gross)
    assert "Breakdown by ApplicationName tag (30-day roll-up, gross)" in html
    assert "ApplicationName Tag" in html

    # 3b. Breakdown by AWS Region (30-day roll-up, gross)
    assert "Breakdown by AWS Region (30-day roll-up, gross)" in html
    assert "AWS Region" in html

    # 4. Top Services Spend with Trend (30d) sparkline and sub-costs
    assert "Top Services Spend" in html
    assert "Trend (30d)" in html
    assert "↳" in html  # Sub-costs marker
    assert "<svg width=\"15\" height=\"15\"" in html  # Free/Royalty-free open source inline service icons

    # 5. Daily Cost History:
    # Removed Net and Credits Applied columns from the Daily Cost History table
    assert "Daily Cost History (Last 30 Days)" in html
    assert "Credits Applied" not in html
    assert "<th>Gross</th><th class=\"num\">Net</th>" not in html

    # Top 5 Services column present
    assert "Top 5 Services (Acronym, Spend, Share)" in html

    # Acronym format and tooltip: e.g. RDS($...; ...%)
    assert "RDS($" in html
    assert "title=" in html  # Tooltip on hyperlink highlight

    # Navigable view with 10 records per page, Next / Previous
    assert "10 records per page" in html
    assert "Previous" in html
    assert "Next" in html
    assert "sortTable" in html  # Sorting allowed

    # Daily baseline costs configuration notice
    assert "Active Daily Baseline:" in html
    assert "cost-red" in html
    assert "cost-green" in html


def test_settings_page_and_configuration_update():
    # 1. GET /settings HTML page
    res_get = web.lambda_handler({"rawPath": "/settings", "httpMethod": "GET"}, None)
    assert res_get["statusCode"] == 200
    assert "text/html" in res_get["headers"]["Content-Type"]
    body = res_get["body"]
    assert "Configuration & Budget Tracking" in body
    assert "Option 1: Fixed Budget with Calendar Expiry" in body
    assert "Option 2: Monthly Credits (Resets Every Month)" in body
    assert "Daily Baseline Cost" in body
    assert "1.0" in body  # Default baseline

    # 2. POST /settings form submission (e.g. Switch to fixed budget of $800, baseline 0.90)
    post_body = "budget_type=fixed&fixed_budget_amount=800.00&fixed_budget_expiry=2027-06-30&daily_baseline_usd=0.90"
    res_post = web.lambda_handler({
        "rawPath": "/settings",
        "httpMethod": "POST",
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": post_body,
    }, None)
    assert res_post["statusCode"] == 200
    assert "Settings and budget successfully updated!" in res_post["body"]
    assert "$800.00" in res_post["body"]


def test_api_settings_json():
    # 1. GET /api/settings
    res = web.lambda_handler({"rawPath": "/api/settings", "httpMethod": "GET"}, None)
    assert res["statusCode"] == 200
    data = json.loads(res["body"])
    assert "daily_baseline_usd" in data
    assert "budget_type" in data

    # 2. POST /api/settings JSON
    new_settings = {
        "budget_type": "monthly",
        "monthly_credit_amount": 60.0,
        "monthly_reset_day": 1,
        "daily_baseline_usd": 1.00,
    }
    res_post = web.lambda_handler({
        "rawPath": "/api/settings",
        "httpMethod": "POST",
        "headers": {"content-type": "application/json"},
        "body": json.dumps(new_settings),
    }, None)
    assert res_post["statusCode"] == 200
    resp_data = json.loads(res_post["body"])
    assert resp_data["status"] == "saved"
    assert resp_data["settings"]["monthly_credit_amount"] == 60.0
    assert resp_data["settings"]["monthly_reset_day"] == 1
    assert resp_data["settings"]["daily_baseline_usd"] == 1.00


def test_api_costs_endpoint():
    res = web.lambda_handler({"rawPath": "/api/costs", "httpMethod": "GET"}, None)
    assert res["statusCode"] == 200
    data = json.loads(res["body"])
    assert "window_gross_usd" in data
    assert "daily" in data
    assert len(data["daily"]) > 0
    assert "top_services" in data
    assert "app_tag_breakdown" in data
    assert "region_breakdown" in data
    assert len(data["region_breakdown"]) > 0
    assert "budget" in data
    assert "latency_breakdown" in data

    # Verify first daily record has top_5_services formatted with acronyms and baseline color
    first_day = data["daily"][0]
    assert "color_class" in first_day
    assert "top_5_services" in first_day
    assert len(first_day["top_5_services"]) > 0
    assert "acronym" in first_day["top_5_services"][0]


def test_healthz_endpoint():
    res = web.lambda_handler({"rawPath": "/healthz", "httpMethod": "GET"}, None)
    assert res["statusCode"] == 200
    data = json.loads(res["body"])
    assert data["status"] == "healthy"
    assert data["service"] == "cloud-frugality"
    assert data["tag"] == "Frugality"
    assert data["comm"] in ("python", "python3", "python3.12", "python3.14", "pytest")


def test_engine_toggle_and_rust_switch():
    # 1. Default dashboard contains interactive engine toggle
    res = web.lambda_handler({"rawPath": "/", "httpMethod": "GET"}, None)
    assert res["statusCode"] == 200
    html = res["body"]
    assert "engine-switcher" in html
    assert "http://localhost:8090/" in html
    assert "http://localhost:8091/" in html

    # 2. When switching to Rust via engine parameter, verifies genuine Rust output is returned
    res_rust = web.lambda_handler({
        "rawPath": "/healthz",
        "httpMethod": "GET",
        "queryStringParameters": {"engine": "rust"},
    }, None)
    assert res_rust["statusCode"] == 200
    data_rust = json.loads(res_rust["body"])
    assert data_rust["status"] == "healthy"
    assert data_rust["engine"] == "rust"
    assert "rust" in data_rust["runtime"]
    assert data_rust["comm"] == "cloud-frugality"
