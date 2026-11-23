"""
Unit tests for credit runway, budget calculation, and baseline evaluation in Cloud Frugality.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

import billing


def test_credit_expiry_binds_when_burn_is_low():
    today = dt.datetime.now(dt.timezone.utc).date()
    expiry = (today + dt.timedelta(days=180)).isoformat()
    # $150 remaining, $0.05/day burn -> takes 3000 days, so expiry (180 days) binds
    res = billing.calculate_credit_runway(150.0, expiry, 0.05)
    assert res["binding_limit"] == "expiry"
    assert res["days_until_expiry"] == 180
    assert res["credit_waste_if_expiry_binds_usd"] > 100.0


def test_credit_exhaustion_binds_when_burn_is_high():
    today = dt.datetime.now(dt.timezone.utc).date()
    expiry = (today + dt.timedelta(days=180)).isoformat()
    # $100 remaining, $10.0/day burn -> takes 10 days, so exhaustion binds
    res = billing.calculate_credit_runway(100.0, expiry, 10.0)
    assert res["binding_limit"] == "exhaustion"
    assert res["days_until_exhaustion"] == 10
    assert res["credit_waste_if_expiry_binds_usd"] is None


def test_zero_burn_rate():
    today = dt.datetime.now(dt.timezone.utc).date()
    expiry = (today + dt.timedelta(days=90)).isoformat()
    res = billing.calculate_credit_runway(50.0, expiry, 0.0)
    assert res["binding_limit"] == "expiry"
    assert res["days_until_exhaustion"] is None
    assert res["credit_waste_if_expiry_binds_usd"] == 50.0


def test_missing_credits_data():
    res = billing.calculate_credit_runway(None, None, 1.25)
    assert res["binding_limit"] is None
    assert res["avg_daily_gross_usd"] == 1.25


def test_daily_cost_baseline_thresholds():
    # Baseline: 1.00 (default). 70% threshold is 0.70
    # 1. Exceeds baseline -> RED
    res_red = billing.evaluate_daily_cost_baseline(1.25)
    assert res_red["color"] == "red"
    assert res_red["css_class"] == "cost-red"

    # 2. Between 70% and baseline (e.g. 0.85) -> YELLOW
    res_yellow = billing.evaluate_daily_cost_baseline(0.85)
    assert res_yellow["color"] == "yellow"
    assert res_yellow["css_class"] == "cost-yellow"

    # Exactly 70% (0.70) -> YELLOW
    res_exact_70 = billing.evaluate_daily_cost_baseline(0.70)
    assert res_exact_70["color"] == "yellow"
    assert res_exact_70["css_class"] == "cost-yellow"

    # 3. Below 70% (e.g. 0.40) -> GREEN
    res_green = billing.evaluate_daily_cost_baseline(0.40)
    assert res_green["color"] == "green"
    assert res_green["css_class"] == "cost-green"


def test_budget_plan_fixed_option():
    today = dt.datetime.now(dt.timezone.utc).date()
    exp_date = (today + dt.timedelta(days=45)).isoformat()
    # $1000 fixed budget, $100 burned, $20/day burn rate
    res = billing.calculate_budget_plan(
        budget_type="fixed",
        amount=1000.0,
        expiry_or_reset=exp_date,
        avg_daily_burn=20.0,
        current_burn_to_date=100.0,
    )
    assert res["budget_type"] == "fixed"
    assert res["budgeted_usd"] == 1000.0
    assert res["remaining_usd"] == 900.0
    assert res["days_available"] == 45
    assert res["days_until_exhaustion"] == 45


def test_budget_plan_monthly_credits_option():
    # $60 monthly credits, resets on day 15
    res = billing.calculate_budget_plan(
        budget_type="monthly",
        amount=60.0,
        expiry_or_reset=15,
        avg_daily_burn=1.0,
        current_burn_to_date=10.0,
    )
    assert res["budget_type"] == "monthly"
    assert res["budgeted_usd"] == 60.0
    assert res["remaining_usd"] == 50.0
    assert res["reset_day_of_month"] == 15
    assert res["days_available"] > 0
