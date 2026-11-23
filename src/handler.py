"""
Daily AWS cost and resource collector Lambda handler for Cloud Frugality.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys

import boto3
import certifi
import psycopg

import billing
import resources

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

    # Breakdown by service
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

    return {
        "unblended_usd": round(unblended, 4),
        "blended_usd": round(blended, 4),
        "net_usd": round(net, 4),
        "gross_usd": round(gross, 4),
        "credit_usd": round(credit, 4),
        "gross_services": gross_services,
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

    # 4. Save to Aurora PostgreSQL via IAM DB Auth
    rds = boto3.client("rds", region_name=REGION)
    token = rds.generate_db_auth_token(DB_HOST, DB_PORT, DB_IAM_USER)

    conninfo = (
        f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_IAM_USER} "
        f"password={token} sslmode=verify-full sslrootcert={certifi.where()}"
    )

    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            # Upsert daily cost
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

            # Upsert inventory
            for r in inv.values():
                cur.execute("""
                    INSERT INTO resource_inventory (
                        arn, service, resource_type, region, application_name, tags, created_at, first_seen, last_seen
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (arn) DO UPDATE SET
                        last_seen = now(),
                        tags = EXCLUDED.tags;
                """, (
                    r["arn"], r["service"], r["resource_type"], r["region"],
                    r["application_name"], r["tags"], r["created_at"],
                ))
        conn.commit()

    log.info("Collector finished: date=%s gross=$%s resources=%d", start_day, cost_data["gross_usd"], len(inv))
    return {
        "statusCode": 200,
        "date": start_day,
        "gross_usd": cost_data["gross_usd"],
        "net_usd": cost_data["net_usd"],
        "resource_count": len(inv),
    }
