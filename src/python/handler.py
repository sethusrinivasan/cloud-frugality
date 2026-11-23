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


def lambda_handler(event: dict, context) -> dict:
    log.info("Starting Cloud Frugality collector run: %s", event)
    target_day = event.get("day")
    start_day, end_day = _day_window(target_day)

    # 1. Harvest spend
    cost_data = collect_costs(start_day, end_day)

    # 2. Harvest account plan and runway
    plan = billing.fetch_account_plan()
    runway = billing.calculate_credit_runway(
        plan.get("credits_remaining"),
        plan.get("credits_expiry"),
        cost_data["gross_usd"],
    )

    # 3. Harvest active inventory
    tag_client = boto3.client("resourcegroupstaggingapi", region_name=REGION)
    inv = resources.sweep_resources(tag_client)
    resources.enrich_creation_timestamps(inv)

    # If app_tags was empty from CE, derive from inventory tag mappings
    if not cost_data.get("app_tags"):
        derived_tags = {}
        for r in inv.values():
            app = r.get("application_name") or "Frugality"
            derived_tags[app] = derived_tags.get(app, 0) + 1
        total_items = sum(derived_tags.values()) or 1
        cost_data["app_tags"] = {
            app: round(cost_data["gross_usd"] * (count / total_items), 4)
            for app, count in derived_tags.items()
        }

    # 4. Save to FrugalityStore (S3 + DuckDB)
    store = FrugalityStore()
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
        "plan_type": plan.get("plan_type"),
        "credits_granted_usd": plan.get("credits_granted"),
        "credits_remaining_usd": plan.get("credits_remaining"),
        "credits_expiry": plan.get("credits_expiry"),
        "projection": runway,
    }
    store.save_daily_cost(day_payload)
    store.save_inventory(inv)

    # 5. Optional backward compatibility: write to Aurora PostgreSQL if DB_HOST is set
    if DB_HOST:
        try:
            import certifi
            import psycopg
            rds = boto3.client("rds", region_name=REGION)
            token = rds.generate_db_auth_token(DB_HOST, DB_PORT, DB_IAM_USER)
            conninfo = (
                f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_IAM_USER} "
                f"password={token} sslmode=verify-full sslrootcert={certifi.where()}"
            )
            with psycopg.connect(conninfo) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO daily_cost (
                            usage_date, application_name, unblended_usd, blended_usd, net_usd,
                            currency, services, gross_usd, credit_usd, gross_services,
                            plan_type, credits_granted_usd, credits_remaining_usd,
                            credits_consumed_usd, credits_expiry, projection
                        ) VALUES (
                            %s, 'Frugality', %s, %s, %s, 'USD', %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT (usage_date) DO UPDATE SET
                            gross_usd = EXCLUDED.gross_usd,
                            net_usd = EXCLUDED.net_usd,
                            credit_usd = EXCLUDED.credit_usd,
                            gross_services = EXCLUDED.gross_services,
                            credits_remaining_usd = EXCLUDED.credits_remaining_usd,
                            projection = EXCLUDED.projection,
                            collected_at = now();
                    """, (
                        start_day,
                        cost_data["unblended_usd"],
                        cost_data["blended_usd"],
                        cost_data["net_usd"],
                        json.dumps(cost_data["gross_services"]),
                        cost_data["gross_usd"],
                        cost_data["credit_usd"],
                        json.dumps(cost_data["gross_services"]),
                        plan.get("plan_type"),
                        plan.get("credits_granted"),
                        plan.get("credits_remaining"),
                        (plan.get("credits_granted") - plan.get("credits_remaining")) if (plan.get("credits_granted") and plan.get("credits_remaining")) else None,
                        plan.get("credits_expiry")[:10] if plan.get("credits_expiry") else None,
                        json.dumps(runway),
                    ))
                conn.commit()
        except Exception as exc:
            log.warning("Aurora PostgreSQL upsert skipped/failed: %s", exc)

    log.info("Collector finished: date=%s gross=$%s resources=%d", start_day, cost_data["gross_usd"], len(inv))
    return {
        "statusCode": 200,
        "date": start_day,
        "gross_usd": cost_data["gross_usd"],
        "net_usd": cost_data["net_usd"],
        "resource_count": len(inv),
    }
