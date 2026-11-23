"""
Unit tests for Cloud Frugality web portal rendering and metrics.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("psycopg", MagicMock())
sys.modules.setdefault("certifi", MagicMock())

from metrics import LatencyTracker
import web


def test_latency_tracker():
    tracker = LatencyTracker()
    tracker.record("AWS RDS", "rds:generate_db_auth_token", 5.0)
    tracker.record("Amazon Aurora PostgreSQL", "psycopg:connect", 25.0)
    tracker.record("Amazon Aurora PostgreSQL", "Query daily_cost", 10.0)

    summary = tracker.summary()
    assert summary["total_calls"] == 3
    assert summary["total_ms"] == 40.0
    assert len(summary["services"]) == 2
    assert summary["database_status"] == "Warm"


def test_render_html_contains_frugality_branding():
    tracker = LatencyTracker()
    tracker.record("Amazon Aurora PostgreSQL", "psycopg:connect", 20.0)

    mock_data = {
        "window_days": 30,
        "days_recorded": 2,
        "window_gross_usd": 45.20,
        "window_net_usd": 0.0,
        "resource_count": 22,
        "credit": {
            "plan_type": "FREE",
            "credits_granted_usd": 200.0,
            "credits_remaining_usd": 154.80,
            "credits_consumed_usd": 45.20,
            "credits_expiry": "2027-04-15",
            "projection": {"binding_limit": "exhaustion", "days_until_exhaustion": 100},
        },
        "daily": [
            {"date": "2026-11-22", "gross_usd": 1.50, "net_usd": 0.0, "credit_usd": -1.50, "services": {"Amazon RDS": 1.20}},
            {"date": "2026-11-21", "gross_usd": 1.45, "net_usd": 0.0, "credit_usd": -1.45, "services": {"Amazon RDS": 1.15}},
        ],
        "top_services": [
            {"service": "Amazon Relational Database Service", "usd": 35.0},
            {"service": "AWS Lambda", "usd": 5.20},
        ],
    }

    html = web._render_html(mock_data, tracker)
    assert "Cloud Frugality" in html
    assert "Tag: Frugality" in html
    assert "$45.20" in html
    assert "$154.80" in html
    assert "Amazon Relational Database Service" in html
    assert "2026-11-22" in html


def test_healthz_endpoint():
    res = web.lambda_handler({"rawPath": "/healthz"}, None)
    assert res["statusCode"] == 200
    assert "healthy" in res["body"]
    assert "Frugality" in res["body"]
