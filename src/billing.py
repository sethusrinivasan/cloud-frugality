"""
Multi-source billing and promotional credit accounting for Cloud Frugality.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

log = logging.getLogger("cloud_frugality.billing")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1")
ASSUMED_CREDIT_GRANT = float(os.environ.get("ASSUMED_CREDIT_GRANT_USD", "200") or 0)

_clients: dict = {}


def _get_ce():
    if "ce" not in _clients:
        import boto3
        _clients["ce"] = boto3.client("ce", region_name=REGION)
    return _clients["ce"]


def _get_ft():
    if "ft" not in _clients:
        import boto3
        _clients["ft"] = boto3.client("freetier", region_name="us-east-1")
    return _clients["ft"]


def fetch_account_plan() -> dict:
    plan = {
        "plan_type": None,
        "credits_remaining": None,
        "credits_expiry": None,
        "credits_granted": None,
    }
    try:
        res = _get_ft().get_account_plan_state()
        plan["plan_type"] = res.get("accountPlanType")
        rem = (res.get("accountPlanRemainingCredits") or {}).get("amount")
        plan["credits_remaining"] = float(rem) if rem is not None else None
        exp = res.get("accountPlanExpirationDate")
        plan["credits_expiry"] = exp.isoformat() if isinstance(exp, dt.datetime) else exp
        if plan["credits_remaining"] is not None and ASSUMED_CREDIT_GRANT > 0:
            plan["credits_granted"] = ASSUMED_CREDIT_GRANT
    except Exception as exc:
        log.warning("freetier:GetAccountPlanState unavailable: %s", exc)
    return plan


def calculate_credit_runway(
    credits_remaining: float | None,
    credits_expiry: str | None,
    avg_daily_gross: float,
) -> dict:
    res = {
        "binding_limit": None,
        "days_until_exhaustion": None,
        "days_until_expiry": None,
        "credit_waste_if_expiry_binds_usd": None,
        "avg_daily_gross_usd": round(avg_daily_gross, 4),
    }

    if credits_expiry:
        try:
            today = dt.datetime.now(dt.timezone.utc).date()
            exp_date = dt.date.fromisoformat(credits_expiry[:10])
            days_exp = max(0, (exp_date - today).days)
            res["days_until_expiry"] = days_exp
        except Exception:
            days_exp = None
    else:
        days_exp = None

    if credits_remaining is not None and avg_daily_gross > 0.0001:
        days_exh = int(credits_remaining / avg_daily_gross)
        res["days_until_exhaustion"] = days_exh
    else:
        days_exh = None

    if days_exh is not None and days_exp is not None:
        if days_exh < days_exp:
            res["binding_limit"] = "exhaustion"
        else:
            res["binding_limit"] = "expiry"
            projected_burn = avg_daily_gross * days_exp
            res["credit_waste_if_expiry_binds_usd"] = max(0.0, round(credits_remaining - projected_burn, 2))
    elif days_exh is not None:
        res["binding_limit"] = "exhaustion"
    elif days_exp is not None:
        res["binding_limit"] = "expiry"
        if credits_remaining is not None:
            res["credit_waste_if_expiry_binds_usd"] = credits_remaining

    return res
