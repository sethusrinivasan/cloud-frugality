"""
Unit tests for FrugalityStore (DuckDB engine over local/S3 data) and acronym rules.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

from store import FrugalityStore, get_service_acronym


def test_service_acronym_formation():
    # 1. Strips Amazon / AWS and maps prominent acronyms
    assert get_service_acronym("Amazon Relational Database Service") == "RDS"
    assert get_service_acronym("AWS CloudWatch") == "CW"
    assert get_service_acronym("AmazonCloudWatch") == "CW"
    assert get_service_acronym("Amazon Simple Storage Service") == "S3"
    assert get_service_acronym("AWS Lambda") == "LAM"
    assert get_service_acronym("Amazon DynamoDB") == "DDB"
    assert get_service_acronym("AWS Key Management Service") == "KMS"
    assert get_service_acronym("Amazon Route 53") == "R53"

    # 2. General services: strips Amazon/AWS and takes first 3 letters
    assert get_service_acronym("AWS Cost Explorer") == "CE"
    assert get_service_acronym("Amazon Inspector") == "INS"
    assert get_service_acronym("Amazon Rekognition") == "REK"
    assert get_service_acronym("AWS X-Ray") == "XRA"


def test_frugality_store_lifecycle_and_duckdb_queries():
    temp_dir = tempfile.mkdtemp()
    try:
        store = FrugalityStore(bucket="", local_dir=temp_dir)

        # 1. Test Default Settings
        settings = store.get_settings()
        assert settings["daily_baseline_usd"] == 1.00
        assert settings["budget_type"] == "monthly"
        assert settings["monthly_credit_amount"] == 60.0

        # 2. Update Settings to Fixed Budget
        store.save_settings({
            "budget_type": "fixed",
            "fixed_budget_amount": 750.0,
            "fixed_budget_expiry": "2027-12-31",
            "daily_baseline_usd": 0.80,
        })
        updated = store.get_settings()
        assert updated["budget_type"] == "fixed"
        assert updated["fixed_budget_amount"] == 750.0
        assert updated["daily_baseline_usd"] == 0.80

        # 3. Save Sample Daily Costs
        store.save_daily_cost({
            "date": "2026-11-22",
            "gross_usd": 1.20,
            "net_usd": 0.0,
            "credit_usd": -1.20,
            "services": {
                "Amazon Relational Database Service": 0.90,
                "AWS CloudWatch": 0.30,
            },
            "service_subcosts": {
                "Amazon Relational Database Service": {
                    "Aurora ACU": 0.70,
                    "Aurora Storage": 0.20,
                },
                "AWS CloudWatch": {
                    "MetricStorage": 0.30,
                },
            },
            "app_tags": {
                "Frugality": 1.00,
                "Untagged": 0.20,
            },
        })

        store.save_daily_cost({
            "date": "2026-11-21",
            "gross_usd": 0.50,
            "net_usd": 0.0,
            "credit_usd": -0.50,
            "services": {
                "Amazon Relational Database Service": 0.40,
                "Amazon Simple Storage Service": 0.10,
            },
            "service_subcosts": {
                "Amazon Relational Database Service": {
                    "Aurora ACU": 0.35,
                    "Aurora Storage": 0.05,
                },
            },
            "app_tags": {
                "Frugality": 0.50,
            },
        })

        # 4. Save Inventory
        store.save_inventory({
            "arn:aws:s3:::test-bucket": {
                "arn": "arn:aws:s3:::test-bucket",
                "service": "s3",
                "resource_type": "bucket",
                "region": "us-east-2",
                "application_name": "Frugality",
                "tags": "{}",
                "created_at": None,
            }
        })
        assert store.get_inventory_count() == 1

        # 5. Query DuckDB Summary
        summary = store.query_cost_summary(window_days=30)
        assert summary["window_gross_usd"] == 1.70
        assert summary["days_recorded"] == 2
        assert summary["resource_count"] == 1

        # Check Top Services Spend & Subcosts
        top_services = summary["top_services"]
        assert len(top_services) >= 2
        assert top_services[0]["service"] == "Amazon Relational Database Service"
        assert top_services[0]["acronym"] == "RDS"
        assert len(top_services[0]["subcosts"]) >= 1
        assert "trend" in top_services[0]

        # Check Application Tag Breakdown
        app_breakdown = summary["app_tag_breakdown"]
        assert len(app_breakdown) >= 1
        assert app_breakdown[0]["application"] == "Frugality"
        assert app_breakdown[0]["usd"] == 1.50

        # Check AWS Region Breakdown
        reg_breakdown = summary["region_breakdown"]
        assert len(reg_breakdown) >= 1
        assert "region" in reg_breakdown[0]
        assert "region_name" in reg_breakdown[0]
        assert "usd" in reg_breakdown[0]
        assert "percent" in reg_breakdown[0]

        # Check Daily Cost Records (Top 5 Services, Acronyms, and Color Classes)
        daily = summary["daily"]
        assert len(daily) == 2
        # Day 1: 1.20 > 0.80 baseline -> cost-red
        assert daily[0]["date"] == "2026-11-22"
        assert daily[0]["color_class"] == "cost-red"
        assert len(daily[0]["top_5_services"]) == 2
        assert daily[0]["top_5_services"][0]["acronym"] == "RDS"
        assert "RDS($0.90; 75%)" in daily[0]["top_5_services"][0]["short_display"]

        # Day 2: 0.50 < 0.80 * 0.70 (0.56) -> cost-green
        assert daily[1]["date"] == "2026-11-21"
        assert daily[1]["color_class"] == "cost-green"

        # Check Budget Calculations
        budget = summary["budget"]
        assert budget["budget_type"] == "fixed"
        assert budget["budgeted_usd"] == 750.0
        assert budget["remaining_usd"] == round(750.0 - 1.70, 2)
        assert budget["days_available"] > 0

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
