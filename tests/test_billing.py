"""
Unit tests for credit runway calculation in Cloud Frugality.
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
