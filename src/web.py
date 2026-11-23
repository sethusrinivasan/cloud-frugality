"""
Public Cloud Frugality web portal and JSON API handler.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import time

import boto3
import certifi
import psycopg

from metrics import LatencyTracker

log = logging.getLogger("cloud_frugality.web")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_IAM_USER = os.environ.get("DB_READER_USER", "cost_reader")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")
COST_WINDOW_DAYS = int(os.environ.get("COST_WINDOW_DAYS", "30"))


def _get_process_comm() -> str:
    try:
        with open("/proc/self/comm", "r") as f:
            return f.read().strip()
    except Exception:
        return "python"


def _fetch_cost_data(tracker: LatencyTracker) -> dict:
    t0 = time.perf_counter()
    rds = boto3.client("rds", region_name=REGION)
    token = rds.generate_db_auth_token(DB_HOST, DB_PORT, DB_IAM_USER)
    tracker.record("AWS RDS", "rds:generate_db_auth_token", (time.perf_counter() - t0) * 1000)

    conninfo = (
        f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_IAM_USER} "
        f"password={token} sslmode=verify-full sslrootcert={certifi.where()}"
    )

    t1 = time.perf_counter()
    conn = psycopg.connect(conninfo)
    tracker.record("Amazon Aurora PostgreSQL", "psycopg:connect (TLS + IAM auth)", (time.perf_counter() - t1) * 1000)

    try:
        with conn.cursor() as cur:
            t2 = time.perf_counter()
            cur.execute("""
                SELECT usage_date, gross_usd, net_usd, credit_usd, gross_services,
                       plan_type, credits_granted_usd, credits_remaining_usd,
                       credits_expiry, projection
                FROM daily_cost
                ORDER BY usage_date DESC
                LIMIT %s;
            """, (COST_WINDOW_DAYS,))
            rows = cur.fetchall()
            tracker.record("Amazon Aurora PostgreSQL", f"Query daily_cost ({COST_WINDOW_DAYS} days)", (time.perf_counter() - t2) * 1000)

            t3 = time.perf_counter()
            cur.execute("SELECT count(*) FROM resource_inventory;")
            resource_count = cur.fetchone()[0]
            tracker.record("Amazon Aurora PostgreSQL", "Query resource_inventory count", (time.perf_counter() - t3) * 1000)
    finally:
        conn.close()

    daily = []
    window_gross = 0.0
    window_net = 0.0
    latest_credit = {}
    top_services_map: dict[str, float] = {}

    for r in rows:
        d_str = r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0])
        gross = float(r[1] or 0.0)
        net = float(r[2] or 0.0)
        credit = float(r[3] or 0.0)
        services = r[4] if isinstance(r[4], dict) else {}
        window_gross += gross
        window_net += net
        daily.append({
            "date": d_str,
            "gross_usd": round(gross, 4),
            "net_usd": round(net, 4),
            "credit_usd": round(credit, 4),
            "services": services,
        })
        for svc, amt in services.items():
            top_services_map[svc] = top_services_map.get(svc, 0.0) + float(amt)

        if not latest_credit and (r[7] is not None or r[9] is not None):
            latest_credit = {
                "plan_type": r[5],
                "credits_granted_usd": float(r[6]) if r[6] is not None else 200.0,
                "credits_remaining_usd": float(r[7]) if r[7] is not None else None,
                "credits_expiry": str(r[8]) if r[8] else None,
                "projection": r[9] if isinstance(r[9], dict) else {},
            }
            if latest_credit["credits_remaining_usd"] is not None:
                latest_credit["credits_consumed_usd"] = round(
                    latest_credit["credits_granted_usd"] - latest_credit["credits_remaining_usd"], 2
                )

    top_services = [
        {"service": k, "usd": round(v, 4)}
        for k, v in sorted(top_services_map.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "window_days": COST_WINDOW_DAYS,
        "days_recorded": len(daily),
        "window_gross_usd": round(window_gross, 2),
        "window_net_usd": round(window_net, 2),
        "resource_count": resource_count,
        "credit": latest_credit,
        "daily": daily,
        "top_services": top_services,
    }


def _render_sparkline(daily: list[dict]) -> str:
    if not daily:
        return ""
    chron = list(reversed(daily))
    vals = [d["gross_usd"] for d in chron]
    max_val = max(vals) if vals and max(vals) > 0 else 1.0
    w = 120
    h = 28
    pts = []
    n = len(vals)
    for i, v in enumerate(vals):
        x = round(3.0 + (i / max(1, n - 1)) * (w - 6), 1)
        y = round((h - 4) - (v / max_val) * (h - 8), 1)
        pts.append((x, y))

    poly_pts = f"{pts[0][0]},{h} " + " ".join(f"{x},{y}" for x, y in pts) + f" {pts[-1][0]},{h}"
    line_pts = " ".join(f"{x},{y}" for x, y in pts)
    last_pt = pts[-1]

    return f"""
    <svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="vertical-align:middle;">
        <polygon points="{poly_pts}" fill="#3fb950" fill-opacity="0.2"/>
        <polyline points="{line_pts}" fill="none" stroke="#3fb950" stroke-width="1.8" stroke-linecap="round"/>
        <circle cx="{last_pt[0]}" cy="{last_pt[1]}" r="2.5" fill="#3fb950"/>
    </svg>
    """


def _render_html(data: dict, tracker: LatencyTracker) -> str:
    summary = tracker.summary()
    daily_rows = ""
    for d in data["daily"]:
        daily_rows += f"""
        <tr>
            <td>{d['date']}</td>
            <td class="num">${d['gross_usd']:.4f}</td>
            <td class="num">${d['net_usd']:.4f}</td>
            <td class="num">${d['credit_usd']:.4f}</td>
        </tr>
        """

    svc_rows = ""
    for s in data["top_services"][:8]:
        svc_rows += f"""
        <tr>
            <td>{s['service']}</td>
            <td class="num">${s['usd']:.4f}</td>
        </tr>
        """

    lat_rows = ""
    for s in summary["services"]:
        lat_rows += f"""
        <tr style="background:rgba(255,255,255,0.02);font-weight:600;">
            <td colspan="2">{s['service']}</td>
            <td class="num">{s['total_ms']} ms ({s['percent']}%)</td>
        </tr>
        """
        for sub in s.get("sub_operations", []):
            lat_rows += f"""
            <tr style="color:#8b949e;font-size:12px;">
                <td style="padding-left:20px;">↳ {sub['operation']}</td>
                <td class="num"></td>
                <td class="num">{sub['total_ms']} ms</td>
            </tr>
            """

    credit = data.get("credit", {})
    rem = credit.get("credits_remaining_usd", 0.0) or 0.0
    consumed = credit.get("credits_consumed_usd", 0.0) or 0.0
    sparkline = _render_sparkline(data["daily"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cloud Frugality — AWS Cost Tracker</title>
  <style>
    :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --green:#3fb950; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:24px 20px; }}
    .container {{ max-width:960px; margin:0 auto; }}
    header {{ margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0 0 8px; font-size:26px; display:flex; align-items:center; gap:12px; }}
    .tag {{ background:#1f6feb33; color:var(--accent); border:1px solid #1f6feb88; font-size:12px; padding:3px 8px; border-radius:12px; font-weight:600; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:16px; margin-bottom:28px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:18px; }}
    .card-title {{ color:var(--muted); font-size:13px; margin-bottom:6px; }}
    .big {{ font-size:26px; font-weight:700; color:var(--green); display:flex; align-items:center; justify-content:space-between; }}
    table {{ width:100%; border-collapse:collapse; margin-bottom:24px; font-size:13px; }}
    th, td {{ padding:8px 12px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ color:var(--muted); font-size:12px; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .sub {{ color:var(--muted); font-size:12px; margin-top:6px; }}
    footer {{ margin-top:40px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; }}
  </style>
</head>
<body>
<div class="container">
  <header>
    <h1>Cloud Frugality <span class="tag">Tag: Frugality</span></h1>
    <p style="color:var(--muted);margin:4px 0 0;">Automated, holistic AWS cost, credit runway, and resource tracking powered by Aurora Serverless v2 PostgreSQL (IAM Database Auth).</p>
  </header>

  <div class="cards">
    <div class="card">
      <div class="card-title">Last 30 Days (Gross Usage)</div>
      <div class="big">
        <span>${data['window_gross_usd']:.2f}</span>
        {sparkline}
      </div>
      <div class="sub">Pre-credit cloud consumption</div>
    </div>
    <div class="card">
      <div class="card-title">Last 30 Days (Net Billed)</div>
      <div class="big">${data['window_net_usd']:.2f}</div>
      <div class="sub">Actual cash billed after promotional credits</div>
    </div>
    <div class="card">
      <div class="card-title">Promotional Credits Remaining</div>
      <div class="big">${rem:.2f}</div>
      <div class="sub">${consumed:.2f} consumed to date</div>
    </div>
    <div class="card">
      <div class="card-title">Tracked AWS Resources</div>
      <div class="big">{data['resource_count']}</div>
      <div class="sub">Active resources across account</div>
    </div>
  </div>

  <h3 style="margin-bottom:10px;">Top Services Spend</h3>
  <table>
    <thead><tr><th>Service</th><th class="num">Gross Cost (USD)</th></tr></thead>
    <tbody>{svc_rows}</tbody>
  </table>

  <h3 style="margin-bottom:10px;">Daily Cost History (Last 30 Days)</h3>
  <table>
    <thead><tr><th>Date (UTC)</th><th class="num">Gross</th><th class="num">Net</th><th class="num">Credits Applied</th></tr></thead>
    <tbody>{daily_rows}</tbody>
  </table>

  <h3 style="margin-bottom:10px;">Live Aurora Database Latency Breakdown</h3>
  <table>
    <thead><tr><th>Operation</th><th></th><th class="num">Latency / Share</th></tr></thead>
    <tbody>{lat_rows}</tbody>
  </table>

  <footer>
    Cloud Frugality · Dedicated Cost & Efficiency Microservice · <a href="/api/costs" style="color:var(--accent);">Raw JSON API</a> · <a href="/healthz" style="color:var(--accent);">Health Check & Identity</a>
  </footer>
</div>
</body>
</html>
"""


def lambda_handler(event: dict, context) -> dict:
    raw_path = event.get("rawPath") or event.get("path") or "/"
    tracker = LatencyTracker()

    if raw_path == "/healthz":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "healthy",
                "service": "cloud-frugality",
                "runtime": f"python {platform.python_version()}",
                "platform": platform.platform(),
                "comm": _get_process_comm(),
                "pid": os.getpid(),
                "region": REGION,
                "tag": "Frugality",
                "database_host": DB_HOST,
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            }),
        }

    try:
        data = _fetch_cost_data(tracker)
    except Exception as exc:
        log.error("Failed to fetch cost data: %s", exc, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc), "database_status": "error"}),
        }

    if raw_path == "/api/costs":
        data["latency_breakdown"] = tracker.summary()
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
            },
            "body": json.dumps(data, indent=2),
        }

    html = _render_html(data, tracker)
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": html,
    }
