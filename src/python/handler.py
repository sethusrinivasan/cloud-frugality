"""
Daily AWS cost and resource collector Lambda handler for Cloud Frugality.
Persists spend, sub-costs, tag distributions, and active resource inventory
to Amazon S3 (queried via DuckDB) and optionally Aurora PostgreSQL.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys

import boto3

import billing
import resources
from store import FrugalityStore

log = logging.getLogger("cloud_frugality.collector")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_IAM_USER = os.environ.get("DB_IAM_USER", "cost_collector")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")
BURN_WINDOW_DAYS = int(os.environ.get("BURN_WINDOW_DAYS", "7"))


def _day_window(target_day: str | None = None) -> tuple[str, str]:
    if target_day is None:
        start = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    else:
        start = dt.date.fromisoformat(target_day)
    return start.isoformat(), (start + dt.timedelta(days=1)).isoformat()


def collect_costs(start: str, end: str) -> dict:
    ce = boto3.client("ce", region_name=REGION)
    res = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost", "BlendedCost", "NetUnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
    )
    unblended = blended = net = gross = credit = 0.0
    for g in res.get("ResultsByTime", [{}])[0].get("Groups", []):
        rtype = g["Keys"][0]
        amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
        blended += float(g["Metrics"]["BlendedCost"]["Amount"])
        net += float(g["Metrics"]["NetUnblendedCost"]["Amount"])
        if rtype == "Usage":
            gross += amt
        elif rtype == "Credit":
            credit += amt
        unblended += amt

    # 1. Breakdown by service
    svc_res = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    gross_services = {}
    for g in svc_res.get("ResultsByTime", [{}])[0].get("Groups", []):
        s_name = g["Keys"][0]
        amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
        if amt > 0:
            gross_services[s_name] = amt

    # 2. Breakdown by Service + UsageType for top sub-costs
    service_subcosts = {}
    try:
        sub_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            GroupBy=[
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
            ],
        )
        for g in sub_res.get("ResultsByTime", [{}])[0].get("Groups", []):
            s_name = g["Keys"][0]
            usage_type = g["Keys"][1]
            amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
            if amt > 0:
                if s_name not in service_subcosts:
                    service_subcosts[s_name] = {}
                service_subcosts[s_name][usage_type] = amt
    except Exception as exc:
        log.warning("Cost Explorer UsageType breakdown unavailable: %s", exc)

    # 3. Breakdown by ApplicationName tag
    app_tags = {}
    try:
        tag_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "TAG", "Key": "ApplicationName"}],
        )
        for g in tag_res.get("ResultsByTime", [{}])[0].get("Groups", []):
            tag_val = g["Keys"][0]
            # Strip tag prefix "ApplicationName$" if returned by CE
            if "$" in tag_val:
                tag_val = tag_val.split("$", 1)[1]
            tag_name = tag_val if tag_val else "Untagged"
            amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
            if amt > 0:
                app_tags[tag_name] = round(app_tags.get(tag_name, 0.0) + amt, 4)
    except Exception as exc:
        log.warning("Cost Explorer ApplicationName tag grouping unavailable: %s", exc)

    # 4. Breakdown by AWS Region
    regions = {}
    try:
        region_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
        )
        for g in region_res.get("ResultsByTime", [{}])[0].get("Groups", []):
            reg_name = g["Keys"][0] or "global"
            amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
            if amt > 0:
                regions[reg_name] = amt
    except Exception as exc:
        log.warning("Cost Explorer REGION grouping unavailable: %s", exc)

    return {
        "unblended_usd": round(unblended, 4),
        "blended_usd": round(blended, 4),
        "net_usd": round(net, 4),
        "gross_usd": round(gross, 4),
        "credit_usd": round(credit, 4),
        "gross_services": gross_services,
        "service_subcosts": service_subcosts,
        "app_tags": app_tags,
        "regions": regions,
    }


def collect_costs_window(start: str, end: str) -> dict[str, dict]:
    """
    Query AWS Cost Explorer across multiple days with Granularity='DAILY'.
    Returns a dict mapping date string -> cost data dictionary.
    """
    ce = boto3.client("ce", region_name=REGION)
    daily_records: dict[str, dict] = {}

    try:
        res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "BlendedCost", "NetUnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
        )
        for time_block in res.get("ResultsByTime", []):
            d_str = time_block.get("TimePeriod", {}).get("Start")
            if not d_str:
                continue
            unblended = blended = net = gross = credit = 0.0
            for g in time_block.get("Groups", []):
                rtype = g["Keys"][0]
                amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
                blended += float(g["Metrics"]["BlendedCost"]["Amount"])
                net += float(g["Metrics"]["NetUnblendedCost"]["Amount"])
                if rtype == "Usage":
                    gross += amt
                elif rtype == "Credit":
                    credit += amt
                unblended += amt
            daily_records[d_str] = {
                "unblended_usd": round(unblended, 4),
                "blended_usd": round(blended, 4),
                "net_usd": round(net, 4),
                "gross_usd": round(gross, 4),
                "credit_usd": round(credit, 4),
                "gross_services": {},
                "service_subcosts": {},
                "app_tags": {},
                "regions": {},
            }
    except Exception as exc:
        log.warning("Cost Explorer daily query failed for %s to %s: %s", start, end, exc)

    # 1. Breakdown by service across window
    try:
        svc_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        for time_block in svc_res.get("ResultsByTime", []):
            d_str = time_block.get("TimePeriod", {}).get("Start")
            if d_str in daily_records:
                for g in time_block.get("Groups", []):
                    s_name = g["Keys"][0]
                    amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
                    if amt > 0:
                        daily_records[d_str]["gross_services"][s_name] = amt
    except Exception as exc:
        log.warning("Cost Explorer SERVICE breakdown unavailable: %s", exc)

    # 2. Breakdown by Service + UsageType for top sub-costs
    try:
        sub_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            GroupBy=[
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
            ],
        )
        for time_block in sub_res.get("ResultsByTime", []):
            d_str = time_block.get("TimePeriod", {}).get("Start")
            if d_str in daily_records:
                subcosts = daily_records[d_str]["service_subcosts"]
                for g in time_block.get("Groups", []):
                    s_name = g["Keys"][0]
                    usage_type = g["Keys"][1]
                    amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
                    if amt > 0:
                        if s_name not in subcosts:
                            subcosts[s_name] = {}
                        subcosts[s_name][usage_type] = amt
    except Exception as exc:
        log.warning("Cost Explorer UsageType breakdown unavailable: %s", exc)

    # 3. Breakdown by ApplicationName tag
    try:
        tag_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "TAG", "Key": "ApplicationName"}],
        )
        for time_block in tag_res.get("ResultsByTime", []):
            d_str = time_block.get("TimePeriod", {}).get("Start")
            if d_str in daily_records:
                app_tags = daily_records[d_str]["app_tags"]
                for g in time_block.get("Groups", []):
                    tag_val = g["Keys"][0]
                    if "$" in tag_val:
                        tag_val = tag_val.split("$", 1)[1]
                    tag_name = tag_val if tag_val else "Untagged"
                    amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
                    if amt > 0:
                        app_tags[tag_name] = round(app_tags.get(tag_name, 0.0) + amt, 4)
    except Exception as exc:
        log.warning("Cost Explorer TAG grouping unavailable: %s", exc)

    # 4. Breakdown by AWS Region
    try:
        region_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
        )
        for time_block in region_res.get("ResultsByTime", []):
            d_str = time_block.get("TimePeriod", {}).get("Start")
            if d_str in daily_records:
                regions = daily_records[d_str]["regions"]
                for g in time_block.get("Groups", []):
                    reg_name = g["Keys"][0] or "global"
                    amt = round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
                    if amt > 0:
                        regions[reg_name] = amt
    except Exception as exc:
        log.warning("Cost Explorer REGION grouping unavailable: %s", exc)

    return daily_records


def lambda_handler(event: dict, context) -> dict:
    log.info("Starting Cloud Frugality collector run: %s", event)
    target_day = event.get("day")
    store = FrugalityStore()

    # 1. Harvest active resource inventory
    tag_client = boto3.client("resourcegroupstaggingapi", region_name=REGION)
    inv = resources.sweep_resources(tag_client)
    resources.enrich_creation_timestamps(inv)
    store.save_inventory(inv)

    # 2. Harvest account plan
    plan = billing.fetch_account_plan()

    def _apply_derived_tags(cost_dict: dict) -> None:
        if not cost_dict.get("app_tags") and inv:
            derived_tags = {}
            for r in inv.values():
                app = r.get("application_name") or "Frugality"
                derived_tags[app] = derived_tags.get(app, 0) + 1
            total_items = sum(derived_tags.values()) or 1
            cost_dict["app_tags"] = {
                app: round(cost_dict["gross_usd"] * (count / total_items), 4)
                for app, count in derived_tags.items()
            }

    if target_day:
        start_day, end_day = _day_window(target_day)
        cost_data = collect_costs(start_day, end_day)
        _apply_derived_tags(cost_data)
        runway = billing.calculate_credit_runway(
            plan.get("credits_remaining"),
            plan.get("credits_expiry"),
            cost_data["gross_usd"],
        )
        day_payload = {
            "date": start_day,
            "unblended_usd": cost_data["unblended_usd"],
            "blended_usd": cost_data["blended_usd"],
            "net_usd": cost_data["net_usd"],
            "gross_usd": cost_data["gross_usd"],
            "credit_usd": cost_data["credit_usd"],
            "services": cost_data["gross_services"],
            "service_subcosts": cost_data["service_subcosts"],
            "app_tags": cost_data["app_tags"],
            "regions": cost_data.get("regions", {REGION: cost_data["gross_usd"]}),
            "plan_type": plan.get("plan_type"),
            "credits_granted_usd": plan.get("credits_granted"),
            "credits_remaining_usd": plan.get("credits_remaining"),
            "credits_expiry": plan.get("credits_expiry"),
            "projection": runway,
        }
        store.save_daily_cost(day_payload)
        return {
            "statusCode": 200,
            "days_harvested": 1,
            "date": start_day,
            "gross_usd": cost_data["gross_usd"],
            "resource_count": len(inv),
        }
    else:
        window_days = int(event.get("window_days") or os.environ.get("HARVEST_WINDOW_DAYS", "30"))
        today = dt.datetime.now(dt.timezone.utc).date()
        start_window = (today - dt.timedelta(days=window_days)).isoformat()
        end_window = today.isoformat()

        daily_records = collect_costs_window(start_window, end_window)
        if not daily_records:
            yesterday_str = (today - dt.timedelta(days=1)).isoformat()
            daily_records[yesterday_str] = {
                "unblended_usd": 0.0,
                "blended_usd": 0.0,
                "net_usd": 0.0,
                "gross_usd": 0.0,
                "credit_usd": 0.0,
                "gross_services": {},
                "service_subcosts": {},
                "app_tags": {},
                "regions": {REGION: 0.0},
            }

        total_gross = sum(d["gross_usd"] for d in daily_records.values())
        avg_gross = (total_gross / len(daily_records)) if daily_records else 0.0
        runway = billing.calculate_credit_runway(
            plan.get("credits_remaining"),
            plan.get("credits_expiry"),
            avg_gross,
        )

        payloads = []
        for d_str, cost_data in daily_records.items():
            _apply_derived_tags(cost_data)
            payloads.append({
                "date": d_str,
                "unblended_usd": cost_data["unblended_usd"],
                "blended_usd": cost_data["blended_usd"],
                "net_usd": cost_data["net_usd"],
                "gross_usd": cost_data["gross_usd"],
                "credit_usd": cost_data["credit_usd"],
                "services": cost_data["gross_services"],
                "service_subcosts": cost_data["service_subcosts"],
                "app_tags": cost_data["app_tags"],
                "regions": cost_data.get("regions", {REGION: cost_data["gross_usd"]}),
                "plan_type": plan.get("plan_type"),
                "credits_granted_usd": plan.get("credits_granted"),
                "credits_remaining_usd": plan.get("credits_remaining"),
                "credits_expiry": plan.get("credits_expiry"),
                "projection": runway,
            })

        store.save_all_daily_costs(payloads)
        log.info("Collector finished: %d days harvested, total_gross=$%s, resources=%d", len(payloads), total_gross, len(inv))
        return {
            "statusCode": 200,
            "days_harvested": len(payloads),
            "window_days": window_days,
            "total_gross_usd": round(total_gross, 4),
            "resource_count": len(inv),
        }
