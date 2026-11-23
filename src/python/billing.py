"""
Multi-source billing, budget tracking, and promotional credit accounting for Cloud Frugality.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

log = logging.getLogger("cloud_frugality.billing")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1")
ASSUMED_CREDIT_GRANT = float(os.environ.get("ASSUMED_CREDIT_GRANT_USD", "60") or 0)

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


def evaluate_daily_cost_baseline(gross_usd: float, baseline_usd: float = 1.00) -> dict:
    """
    Evaluate daily cost against baseline:
    - RED if exceeds baseline (> baseline_usd)
    - YELLOW if 70% and above closer to baseline (>= 0.70 * baseline_usd)
    - GREEN if lower than 70% of baseline (< 0.70 * baseline_usd)
    """
    yellow_thresh = round(0.70 * baseline_usd, 4)
    if gross_usd > baseline_usd:
        color = "red"
        css_class = "cost-red"
        desc = "Exceeds daily baseline"
    elif gross_usd >= yellow_thresh:
        color = "yellow"
        css_class = "cost-yellow"
        desc = "Within 70% threshold of baseline"
    else:
        color = "green"
        css_class = "cost-green"
        desc = "Under 70% of daily baseline"

    return {
        "gross_usd": round(gross_usd, 4),
        "baseline_usd": round(baseline_usd, 4),
        "yellow_threshold_usd": yellow_thresh,
        "color": color,
        "css_class": css_class,
        "description": desc,
    }


def calculate_budget_plan(
    budget_type: str,
    amount: float,
    expiry_or_reset: str | int,
    avg_daily_burn: float,
    current_burn_to_date: float = 0.0,
) -> dict:
    """
    Calculate budget status and runway:
    1) Fixed budget: amount and expiring date (YYYY-MM-DD)
    2) Monthly credits: amount expiring on reset day of month and resets every month
    """
    today = dt.datetime.now(dt.timezone.utc).date()

    if budget_type == "fixed":
        exp_str = str(expiry_or_reset)
        try:
            exp_date = dt.date.fromisoformat(exp_str[:10])
            days_avail = max(0, (exp_date - today).days)
        except Exception:
            days_avail = 0
            exp_date = None

        remaining = max(0.0, round(amount - current_burn_to_date, 2))
        days_exhaustion = int(remaining / avg_daily_burn) if avg_daily_burn > 0.0001 else None

        binding = None
        if days_exhaustion is not None and days_avail is not None:
            binding = "exhaustion" if days_exhaustion < days_avail else "expiry"

        return {
            "budget_type": "fixed",
            "budgeted_usd": round(amount, 2),
            "remaining_usd": remaining,
            "days_available": days_avail,
            "expiry_date": exp_str,
            "days_until_exhaustion": days_exhaustion,
            "binding_limit": binding,
            "avg_daily_burn_usd": round(avg_daily_burn, 4),
        }
    else:
        # Monthly credits
        reset_day = int(expiry_or_reset)
        reset_day = max(1, min(31, reset_day))

        cur_year = today.year
        cur_month = today.month

        if today.day < reset_day:
            next_reset = dt.date(cur_year, cur_month, min(reset_day, 28))
        else:
            next_month = cur_month + 1 if cur_month < 12 else 1
            next_year = cur_year if cur_month < 12 else cur_year + 1
            next_reset = dt.date(next_year, next_month, min(reset_day, 28))

        days_avail = max(0, (next_reset - today).days)
        remaining = max(0.0, round(amount - current_burn_to_date, 2))
        days_exhaustion = int(remaining / avg_daily_burn) if avg_daily_burn > 0.0001 else None

        return {
            "budget_type": "monthly",
            "budgeted_usd": round(amount, 2),
            "remaining_usd": remaining,
            "days_available": days_avail,
            "reset_day_of_month": reset_day,
            "next_reset_date": next_reset.isoformat(),
            "days_until_exhaustion": days_exhaustion,
            "avg_daily_burn_usd": round(avg_daily_burn, 4),
        }
