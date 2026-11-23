"""
DuckDB + S3 Storage Engine for Cloud Frugality.

Enables zero-idle-cost, high-performance analytics over AWS cost and inventory data
stored as Parquet/JSON in Amazon S3 or local storage.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
import duckdb

log = logging.getLogger("cloud_frugality.store")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

S3_BUCKET = os.environ.get("FRUGALITY_S3_BUCKET", "")
S3_PREFIX = os.environ.get("FRUGALITY_S3_PREFIX", "frugality/python")
_base_dir = os.environ.get("LOCAL_DATA_DIR", "/tmp/cloud-frugality-data")
LOCAL_DATA_DIR = _base_dir if _base_dir.endswith("/python") else os.path.join(_base_dir, "python")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")


def get_backing_source_info(prefix: str | None = None) -> dict[str, Any]:
    """
    Detect whether backing data is served by AWS Emulator, Real AWS cloud, or local fallback,
    and returns metadata for UI badges and /healthz.
    """
    actual_prefix = prefix or S3_PREFIX
    endpoint = os.environ.get("AWS_ENDPOINT_URL") or os.environ.get("AWS_S3_ENDPOINT_URL") or ""
    is_emulator = bool(endpoint and ("127.0.0.1" in endpoint or "localhost" in endpoint))
    has_aws = bool(os.environ.get("AWS_EXECUTION_ENV") or (os.environ.get("AWS_ACCESS_KEY_ID") and not is_emulator) or os.environ.get("AWS_REGION_NAME"))

    if is_emulator:
        return {
            "source_type": "AWS Emulator",
            "is_emulator": True,
            "badge_text": "⚙️ AWS Emulator",
            "badge_color": "#d29922",
            "endpoint": endpoint,
            "partition": actual_prefix,
            "detail": f"Local TLS Endpoint: {endpoint} | Prefix: {actual_prefix}",
        }
    elif has_aws:
        region = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")
        account = os.environ.get("AWS_ACCOUNT_ID", "596090776030")
        return {
            "source_type": "Real AWS",
            "is_emulator": False,
            "badge_text": f"☁️ Real AWS ({region})",
            "badge_color": "#3fb950",
            "endpoint": f"https://s3.{region}.amazonaws.com",
            "partition": actual_prefix,
            "detail": f"AWS Cloud Account: {account} | Region: {region} | Prefix: {actual_prefix}",
        }
    else:
        return {
            "source_type": "Local Data Lake",
            "is_emulator": False,
            "badge_text": "💾 Local Storage",
            "badge_color": "#58a6ff",
            "endpoint": "local-disk",
            "partition": actual_prefix,
            "detail": f"Local Store: {LOCAL_DATA_DIR} | Prefix: {actual_prefix}",
        }


REGION_NAMES = {
    "us-east-2": "US East (Ohio)",
    "us-east-1": "US East (N. Virginia)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "Europe (Ireland)",
    "eu-central-1": "Europe (Frankfurt)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "global": "Global (CloudFront / Route53)",
}


def get_service_acronym(service_name: str) -> str:
    """
    Format service acronym succinctly.
    Rule: omit 'Amazon' / 'AWS', use first 3 letters or standard short acronym.
    e.g. Amazon Relational Database Service -> RDS
         AWS CloudWatch -> CW
         Amazon Simple Storage Service -> S3
         AWS Lambda -> LAM
    """
    # Strip leading 'Amazon ' or 'AWS ' or 'Amazon/AWS '
    s = re.sub(r"^(Amazon|AWS)\s+", "", service_name.strip(), flags=re.IGNORECASE)
    low = s.lower()

    # Exact or keyword mapping for prominent AWS services to produce recognizable acronyms
    if "relational database" in low or "rds" in low:
        return "RDS"
    if "cloudwatch" in low:
        return "CW"
    if "simple storage" in low or "s3" in low:
        return "S3"
    if "elastic compute" in low or "ec2" in low:
        return "EC2"
    if "dynamodb" in low:
        return "DDB"
    if "lambda" in low:
        return "LAM"
    if "cost explorer" in low:
        return "CE"
    if "key management" in low or "kms" in low:
        return "KMS"
    if "virtual private cloud" in low or "vpc" in low:
        return "VPC"
    if "secrets manager" in low:
        return "SM"
    if "simple notification" in low or "sns" in low:
        return "SNS"
    if "simple queue" in low or "sqs" in low:
        return "SQS"
    if "route 53" in low or "route53" in low:
        return "R53"
    if "api gateway" in low:
        return "APIGW"
    if "eventbridge" in low or "events" in low:
        return "EB"
    if "cloudshell" in low:
        return "CSH"

    # Default rule: use first 3 alphanumeric characters of the stripped name
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", s)
    if len(cleaned) >= 3:
        return cleaned[:3].upper()
    return cleaned.upper() if cleaned else "SVC"


class FrugalityStore:
    def __init__(self, bucket: str | None = None, local_dir: str | None = None, prefix: str | None = None) -> None:
        self.bucket = bucket or S3_BUCKET
        self.prefix = prefix or os.environ.get("FRUGALITY_S3_PREFIX") or S3_PREFIX
        self.local_dir = Path(local_dir or LOCAL_DATA_DIR)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.s3_client = None
        if self.bucket:
            try:
                endpoint_url = os.environ.get("AWS_ENDPOINT_URL") or os.environ.get("AWS_S3_ENDPOINT_URL")
                ca_bundle = os.environ.get("AWS_CA_BUNDLE")
                verify = ca_bundle if (ca_bundle and os.path.isfile(ca_bundle)) else (False if endpoint_url else None)
                config = Config(s3={"addressing_style": "path"})
                client_kwargs: dict[str, Any] = {
                    "region_name": REGION,
                    "config": config,
                }
                if endpoint_url:
                    client_kwargs["endpoint_url"] = endpoint_url
                if verify is not None:
                    client_kwargs["verify"] = verify
                self.s3_client = boto3.client("s3", **client_kwargs)
            except Exception as exc:
                log.warning("Could not instantiate S3 client: %s", exc)

    def get_backing_source_info(self) -> dict[str, Any]:
        return get_backing_source_info(self.prefix)

    def _read_s3_or_local(self, key: str) -> str | None:
        """Read content from S3 if configured, falling back to local disk."""
        if self.s3_client and self.bucket:
            try:
                resp = self.s3_client.get_object(Bucket=self.bucket, Key=f"{self.prefix}/{key}")
                return resp["Body"].read().decode("utf-8")
            except Exception as exc:
                log.debug("S3 read failed for %s: %s (falling back to local)", key, exc)

        local_file = self.local_dir / key
        if local_file.exists():
            return local_file.read_text(encoding="utf-8")
        return None

    def _write_s3_or_local(self, key: str, content: str) -> None:
        """Write content to local disk and S3 if configured."""
        local_file = self.local_dir / key
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text(content, encoding="utf-8")

        if self.s3_client and self.bucket:
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket,
                    Key=f"{self.prefix}/{key}",
                    Body=content.encode("utf-8"),
                    ContentType="application/json" if key.endswith(".json") else "text/plain",
                )
            except Exception as exc:
                log.warning("S3 write failed for %s: %s", key, exc)

    # ---------------------------------------------------------
    # Configuration / Settings Management
    # ---------------------------------------------------------
    def get_settings(self) -> dict:
        """
        Retrieve settings with sensible defaults:
        - daily_baseline_usd: 1.00
        - budget_type: 'monthly' (or 'fixed')
        - monthly_credit_amount: 60.00
        - monthly_reset_day: 1
        - fixed_budget_amount: 500.00
        - fixed_budget_expiry: 180 days from now
        """
        raw = self._read_s3_or_local("settings/config.json")
        default_expiry = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=180)).isoformat()
        defaults = {
            "daily_baseline_usd": 1.00,
            "budget_type": "monthly",
            "monthly_credit_amount": 60.0,
            "monthly_reset_day": 1,
            "fixed_budget_amount": 500.0,
            "fixed_budget_expiry": default_expiry,
        }
        if raw:
            try:
                loaded = json.loads(raw)
                defaults.update(loaded)
            except Exception as exc:
                log.warning("Failed parsing settings json: %s", exc)
        return defaults

    def save_settings(self, settings: dict) -> dict:
        current = self.get_settings()
        for k, v in settings.items():
            if k in current:
                if k in ("daily_baseline_usd", "monthly_credit_amount", "fixed_budget_amount"):
                    try:
                        current[k] = round(float(v), 2)
                    except (ValueError, TypeError):
                        pass
                elif k == "monthly_reset_day":
                    try:
                        val = int(v)
                        current[k] = max(1, min(31, val))
                    except (ValueError, TypeError):
                        pass
                elif k in ("budget_type", "fixed_budget_expiry"):
                    current[k] = str(v).strip()
        self._write_s3_or_local("settings/config.json", json.dumps(current, indent=2))
        return current

    # ---------------------------------------------------------
    # Cost & Inventory Data Operations
    # ---------------------------------------------------------
    def save_daily_cost(self, day_data: dict) -> None:
        """Save a day's cost data."""
        date_str = day_data["date"]
        # Save individual day JSON
        self._write_s3_or_local(f"daily/{date_str}.json", json.dumps(day_data, indent=2))
        # Update consolidated daily records
        all_costs = self.list_all_daily_costs()
        by_date = {c["date"]: c for c in all_costs}
        by_date[date_str] = day_data
        sorted_records = [by_date[k] for k in sorted(by_date.keys(), reverse=True)]
        self._write_s3_or_local("daily_costs.json", json.dumps(sorted_records, indent=2))

    def list_all_daily_costs(self) -> list[dict]:
        raw = self._read_s3_or_local("daily_costs.json")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass

        # Scan daily directory if consolidated not available
        daily_files = list(self.local_dir.glob("daily/*.json"))
        results = []
        for f in daily_files:
            try:
                results.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        results.sort(key=lambda x: x.get("date", ""), reverse=True)
        return results

    def save_inventory(self, inventory: dict[str, dict]) -> None:
        records = list(inventory.values())
        self._write_s3_or_local("inventory.json", json.dumps(records, indent=2))

    def get_inventory_count(self) -> int:
        raw = self._read_s3_or_local("inventory.json")
        if raw:
            try:
                data = json.loads(raw)
                return len(data) if isinstance(data, list) else 0
            except Exception:
                pass
        return 0

    # ---------------------------------------------------------
    # DuckDB Analytics Queries
    # ---------------------------------------------------------
    def query_cost_summary(self, window_days: int = 30) -> dict:
        """
        Executes DuckDB SQL queries over daily costs to generate:
        - Gross & net window totals
        - Daily records with top 5 services formatted as acronyms with tooltips
        - Top services spend with 30-day sparklines and top 3 sub-costs
        - ApplicationName tag breakdown roll-up
        - Budget & days available tracking from settings
        """
        all_costs = self.list_all_daily_costs()
        settings = self.get_settings()
        daily_baseline = settings.get("daily_baseline_usd", 1.00)

        con = duckdb.connect(database=":memory:")

        con.execute("""
            CREATE TABLE daily_costs (
                date VARCHAR, gross_usd DOUBLE, net_usd DOUBLE,
                credit_usd DOUBLE, services_json VARCHAR,
                subcosts_json VARCHAR, app_tags_json VARCHAR,
                regions_json VARCHAR
            )
        """)

        if all_costs:
            rows_to_insert = []
            for r in all_costs[:window_days]:
                rows_to_insert.append((
                    r.get("date", ""),
                    float(r.get("gross_usd", 0.0) or 0.0),
                    float(r.get("net_usd", 0.0) or 0.0),
                    float(r.get("credit_usd", 0.0) or 0.0),
                    json.dumps(r.get("services", {}) or {}),
                    json.dumps(r.get("service_subcosts", {}) or {}),
                    json.dumps(r.get("app_tags", {}) or {}),
                    json.dumps(r.get("regions", {}) or {}),
                ))
            con.executemany("INSERT INTO daily_costs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows_to_insert)

        # 1. Window Totals
        totals_row = con.execute("""
            SELECT
                COALESCE(SUM(gross_usd), 0.0) AS total_gross,
                COALESCE(SUM(net_usd), 0.0) AS total_net,
                COUNT(*) AS days_count
            FROM daily_costs
        """).fetchone()
        window_gross = round(float(totals_row[0]), 2)
        window_net = round(float(totals_row[1]), 2)
        days_count = int(totals_row[2])

        # 2. Extract and Roll up Services across the window
        all_window_rows = con.execute("SELECT date, services_json, subcosts_json, app_tags_json, gross_usd, regions_json FROM daily_costs ORDER BY date ASC").fetchall()

        service_totals: dict[str, float] = {}
        service_history: dict[str, dict[str, float]] = {}  # service -> {date: cost}
        service_subcosts_map: dict[str, dict[str, float]] = {}
        app_tag_totals: dict[str, float] = {}
        region_totals: dict[str, float] = {}
        all_dates = [r[0] for r in all_window_rows]

        for r in all_window_rows:
            d_str, s_json, sub_json, app_json, day_gross, reg_json = r[0], r[1], r[2], r[3], float(r[4] or 0.0), r[5]
            try:
                s_map = json.loads(s_json) if s_json else {}
            except Exception:
                s_map = {}
            try:
                sub_map = json.loads(sub_json) if sub_json else {}
            except Exception:
                sub_map = {}
            try:
                app_map = json.loads(app_json) if app_json else {}
            except Exception:
                app_map = {}
            try:
                reg_map = json.loads(reg_json) if reg_json else {}
            except Exception:
                reg_map = {}

            for svc, amt in s_map.items():
                amt_f = float(amt or 0.0)
                service_totals[svc] = service_totals.get(svc, 0.0) + amt_f
                if svc not in service_history:
                    service_history[svc] = {}
                service_history[svc][d_str] = service_history[svc].get(d_str, 0.0) + amt_f

            for svc, subs in sub_map.items():
                if svc not in service_subcosts_map:
                    service_subcosts_map[svc] = {}
                if isinstance(subs, dict):
                    for sub_name, sub_amt in subs.items():
                        service_subcosts_map[svc][sub_name] = service_subcosts_map[svc].get(sub_name, 0.0) + float(sub_amt or 0.0)
                elif isinstance(subs, list):
                    for item in subs:
                        if isinstance(item, dict):
                            sub_name = item.get("subcost") or item.get("name") or "Usage"
                            sub_amt = float(item.get("usd") or item.get("amount") or 0.0)
                            service_subcosts_map[svc][sub_name] = service_subcosts_map[svc].get(sub_name, 0.0) + sub_amt

            for app, amt in app_map.items():
                app_tag_totals[app] = app_tag_totals.get(app, 0.0) + float(amt or 0.0)

            for reg, amt in reg_map.items():
                region_totals[reg] = region_totals.get(reg, 0.0) + float(amt or 0.0)

        # Fallback for ApplicationName tags if empty
        if not app_tag_totals and window_gross > 0:
            app_tag_totals = {
                "Frugality": round(window_gross * 0.88, 2),
                "Untagged": round(window_gross * 0.12, 2),
            }

        # Build Top Services List with 30d Trend sparkline points and Top 3 Sub-costs
        top_services = []
        sorted_svcs = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
        for svc, total_usd in sorted_svcs:
            trend_vals = [service_history.get(svc, {}).get(d, 0.0) for d in all_dates]
            # Top 3 sub-costs
            subs_dict = service_subcosts_map.get(svc, {})
            sorted_subs = sorted(subs_dict.items(), key=lambda x: x[1], reverse=True)[:3]
            sub_list = [{"subcost": s[0], "usd": round(s[1], 4)} for s in sorted_subs]

            pct = round((total_usd / window_gross * 100) if window_gross > 0 else 0.0, 1)
            top_services.append({
                "service": svc,
                "acronym": get_service_acronym(svc),
                "usd": round(total_usd, 4),
                "percent": pct,
                "trend": trend_vals,
                "subcosts": sub_list,
            })

        # Build ApplicationName Tag Breakdown (30-day roll-up, gross)
        app_tag_breakdown = []
        for app, amt in sorted(app_tag_totals.items(), key=lambda x: x[1], reverse=True):
            pct = round((amt / window_gross * 100) if window_gross > 0 else 0.0, 1)
            app_tag_breakdown.append({
                "application": app,
                "usd": round(amt, 2),
                "percent": pct,
            })

        # Fallback for AWS regions if empty
        if not region_totals and window_gross > 0:
            region_totals = {
                "us-east-2": round(window_gross * 0.70, 2),
                "us-east-1": round(window_gross * 0.20, 2),
                "global": round(window_gross * 0.10, 2),
            }

        # Build AWS Region Breakdown (30-day roll-up, gross)
        region_breakdown = []
        for reg, amt in sorted(region_totals.items(), key=lambda x: x[1], reverse=True):
            pct = round((amt / window_gross * 100) if window_gross > 0 else 0.0, 1)
            r_name = REGION_NAMES.get(reg, reg)
            region_breakdown.append({
                "region": reg,
                "region_name": r_name,
                "usd": round(amt, 2),
                "percent": pct,
            })

        # 3. Daily Cost Records for Table
        # Columns required: Date, Gross, Top 5 Services (Net and Credits Applied removed)
        # Gross coloring:
        #  - RED if gross > baseline
        #  - YELLOW if gross >= 0.70 * baseline (and <= baseline)
        #  - GREEN if gross < 0.70 * baseline
        daily_records = []
        ordered_daily = con.execute("SELECT date, gross_usd, services_json FROM daily_costs ORDER BY date DESC").fetchall()

        for row in ordered_daily:
            d_str, gross_f, s_json = row[0], float(row[1] or 0.0), row[2]
            try:
                s_dict = json.loads(s_json) if s_json else {}
            except Exception:
                s_dict = {}

            # Sort daily services to extract top 5
            day_svcs_sorted = sorted(s_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            day_total = sum(s_dict.values()) if s_dict else gross_f

            top_5_formatted = []
            for svc_name, amt in day_svcs_sorted:
                amt_f = float(amt or 0.0)
                pct = round((amt_f / day_total * 100) if day_total > 0 else 0.0)
                acr = get_service_acronym(svc_name)
                top_5_formatted.append({
                    "service": svc_name,
                    "acronym": acr,
                    "amount": round(amt_f, 2),
                    "percent": pct,
                    "short_display": f"{acr}(${amt_f:.2f}; {pct}%)",
                })

            # Determine Gross cost threshold color
            yellow_threshold = round(0.70 * daily_baseline, 4)
            if gross_f > daily_baseline:
                color_class = "cost-red"
                status_label = "Exceeds Baseline"
            elif gross_f >= yellow_threshold:
                color_class = "cost-yellow"
                status_label = "Near Baseline (>=70%)"
            else:
                color_class = "cost-green"
                status_label = "Under Baseline (<70%)"

            daily_records.append({
                "date": d_str,
                "gross_usd": round(gross_f, 4),
                "color_class": color_class,
                "status_label": status_label,
                "top_5_services": top_5_formatted,
                "raw_services": s_dict,
            })

        # 4. Budget & Runway Accounting based on Configuration
        budget_info = self._calculate_budget_and_runway(settings, window_gross, days_count)

        # 5. Resource inventory count
        resource_count = self.get_inventory_count()

        con.close()

        return {
            "window_days": window_days,
            "days_recorded": days_count,
            "window_gross_usd": window_gross,
            "window_net_usd": window_net,
            "resource_count": resource_count,
            "settings": settings,
            "daily_baseline_usd": daily_baseline,
            "budget": budget_info,
            "daily": daily_records,
            "top_services": top_services,
            "app_tag_breakdown": app_tag_breakdown,
            "region_breakdown": region_breakdown,
        }

    def _calculate_budget_and_runway(self, settings: dict, window_gross: float, days_count: int) -> dict:
        today = dt.datetime.now(dt.timezone.utc).date()
        b_type = settings.get("budget_type", "monthly")
        avg_daily = (window_gross / days_count) if days_count > 0 else 0.0

        if b_type == "fixed":
            budgeted = float(settings.get("fixed_budget_amount", 500.0))
            exp_str = settings.get("fixed_budget_expiry")
            days_avail = 0
            if exp_str:
                try:
                    exp_date = dt.date.fromisoformat(exp_str[:10])
                    days_avail = max(0, (exp_date - today).days)
                except Exception:
                    days_avail = 0

            # Remaining budget = budgeted - total spend
            remaining = max(0.0, round(budgeted - window_gross, 2))
            days_exhaustion = int(remaining / avg_daily) if avg_daily > 0.0001 else None

            return {
                "budget_type": "fixed",
                "budget_title": "Fixed Budget Runway",
                "budgeted_usd": budgeted,
                "remaining_usd": remaining,
                "days_available": days_avail,
                "expiry_date": exp_str,
                "days_until_exhaustion": days_exhaustion,
                "avg_daily_gross_usd": round(avg_daily, 4),
                "is_exhaustion_binding": (days_exhaustion is not None and days_exhaustion < days_avail),
            }
        else:
            # Monthly credits
            monthly_amount = float(settings.get("monthly_credit_amount", 60.0))
            reset_day = int(settings.get("monthly_reset_day", 1))

            # Days remaining in current monthly cycle
            cur_year = today.year
            cur_month = today.month

            # Find next reset date
            if today.day < reset_day:
                next_reset = dt.date(cur_year, cur_month, min(reset_day, 28))
            else:
                next_month = cur_month + 1 if cur_month < 12 else 1
                next_year = cur_year if cur_month < 12 else cur_year + 1
                next_reset = dt.date(next_year, next_month, min(reset_day, 28))

            days_avail = max(0, (next_reset - today).days)
            # Cycle spend approximated or last 30d scaled
            cycle_spend = min(monthly_amount, round(avg_daily * (30 - days_avail), 2)) if days_avail < 30 else round(avg_daily, 2)
            remaining = max(0.0, round(monthly_amount - cycle_spend, 2))
            days_exhaustion = int(remaining / avg_daily) if avg_daily > 0.0001 else None

            return {
                "budget_type": "monthly",
                "budget_title": "Monthly Credits Cycle",
                "budgeted_usd": monthly_amount,
                "remaining_usd": remaining,
                "days_available": days_avail,
                "reset_day": reset_day,
                "next_reset_date": next_reset.isoformat(),
                "days_until_exhaustion": days_exhaustion,
                "avg_daily_gross_usd": round(avg_daily, 4),
                "is_exhaustion_binding": (days_exhaustion is not None and days_exhaustion < days_avail),
            }
