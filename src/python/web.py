"""
Public Cloud Frugality web portal, settings management, and DuckDB analytics handler.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import time
import urllib.parse
from typing import Any

from metrics import LatencyTracker
from store import FrugalityStore, get_service_acronym, get_backing_source_info

log = logging.getLogger("cloud_frugality.web")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")
COST_WINDOW_DAYS = int(os.environ.get("COST_WINDOW_DAYS", "30"))


def _get_process_comm() -> str:
    try:
        with open("/proc/self/comm", "r") as f:
            return f.read().strip()
    except Exception:
        return "python"


def _render_sparkline(vals: list[float], w: int = 120, h: int = 26, stroke: str = "#3fb950") -> str:
    if not vals:
        return ""
    max_val = max(vals) if vals and max(vals) > 0 else 1.0
    pts = []
    n = len(vals)
    for i, v in enumerate(vals):
        x = round(3.0 + (i / max(1, n - 1)) * (w - 6), 1)
        y = round((h - 4) - (v / max_val) * (h - 8), 1)
        pts.append((x, y))

    poly_pts = f"{pts[0][0]},{h} " + " ".join(f"{x},{y}" for x, y in pts) + f" {pts[-1][0]},{h}"
    line_pts = " ".join(f"{x},{y}" for x, y in pts)
    last_pt = pts[-1]

    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="vertical-align:middle;display:inline-block;">'
        f'<polygon points="{poly_pts}" fill="{stroke}" fill-opacity="0.18"/>'
        f'<polyline points="{line_pts}" fill="none" stroke="{stroke}" stroke-width="1.8" stroke-linecap="round"/>'
        f'<circle cx="{last_pt[0]}" cy="{last_pt[1]}" r="2.5" fill="{stroke}"/>'
        f'</svg>'
    )


def _get_service_icon_svg(service_name: str, acronym: str = "") -> str:
    """
    Returns an appropriate, lightweight, royalty-free inline SVG icon (Open Source / MIT Lucide/Feather format)
    for prominent AWS cloud services. Ensures crisp rendering with zero external CDN dependencies.
    """
    low = (service_name + " " + acronym).lower()

    # 1. Databases (RDS, Aurora, DocumentDB)
    if "rds" in low or "relational database" in low or "aurora" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>'

    # 2. Storage (S3, Glacier, EFS, EBS)
    if "s3" in low or "simple storage" in low or "storage" in low or "glacier" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 11V4a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v7"/><rect x="2" y="11" width="20" height="11" rx="2"/><circle cx="12" cy="16.5" r="1.5"/></svg>'

    # 3. Serverless Compute (Lambda)
    if "lambda" in low or "lam" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'

    # 4. Monitoring / Observability (CloudWatch)
    if "cloudwatch" in low or "cw" in low or "metrics" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>'

    # 5. Virtual Servers / Compute (EC2, ECS, EKS)
    if "ec2" in low or "elastic compute" in low or "compute" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>'

    # 6. NoSQL / Key-Value (DynamoDB)
    if "dynamodb" in low or "ddb" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/></svg>'

    # 7. Security / Key Management (KMS, Secrets Manager, IAM)
    if "kms" in low or "key management" in low or "secrets" in low or "iam" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'

    # 8. Networking (VPC, Route53, CloudFront)
    if "vpc" in low or "route" in low or "network" in low or "cloudfront" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>'

    # 9. Messaging & Queues (SNS, SQS, EventBridge)
    if "sns" in low or "notification" in low or "sqs" in low or "queue" in low or "event" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/></svg>'

    # 10. Cost Management / Billing / Free Tier
    if "cost" in low or "billing" in low or "free tier" in low:
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 6v12"/></svg>'

    # Default cloud resource icon (Cyan/Sky)
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9"/><path d="M12 12v9"/><path d="m8 17 4 4 4-4"/></svg>'


def get_engine_switch_urls(current_host: str = "") -> dict[str, str]:
    """
    Dynamically resolves navigation URLs for the Python and Rust engine switcher.
    Guarantees that on live AWS or remote deployments, the switcher NEVER links to localhost.
    """
    python_env_url = (os.environ.get("PYTHON_WEB_URL") or "").strip()
    rust_env_url = (os.environ.get("RUST_WEB_URL") or "").strip()

    is_aws = bool(
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("AWS_EXECUTION_ENV")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )

    clean_host = (current_host or "").split(":")[0].strip().lower()
    is_localhost = clean_host in ("localhost", "127.0.0.1", "")

    # Local development: strictly when running locally outside AWS Lambda
    if is_localhost and not is_aws:
        return {
            "python": python_env_url or "http://localhost:8090/",
            "rust": rust_env_url or "http://localhost:8091/",
        }

    # Remote / AWS Deployment:
    resolved_python = python_env_url if python_env_url else "/?engine=python"
    resolved_rust = rust_env_url if rust_env_url else "/?engine=rust"

    # Invariant: Never leak localhost to remote browsers
    if "localhost" in resolved_python or "127.0.0.1" in resolved_python:
        resolved_python = "/?engine=python"
    if "localhost" in resolved_rust or "127.0.0.1" in resolved_rust:
        resolved_rust = "/?engine=rust"

    return {
        "python": resolved_python,
        "rust": resolved_rust,
    }


def _render_dashboard_html(data: dict, tracker: LatencyTracker, host: str = "") -> str:
    summary = tracker.summary()
    daily_baseline = float(data.get("daily_baseline_usd", 1.00))
    budget = data.get("budget", {})
    source_info = get_backing_source_info(data.get("partition"))
    engine_urls = get_engine_switch_urls(host)

    # 1. Sparkline for overall 30d gross
    daily_chron = list(reversed(data["daily"]))
    gross_vals = [d["gross_usd"] for d in daily_chron]
    main_sparkline = _render_sparkline(gross_vals, w=130, h=30)

    # 2. Top Services Rows with Trend(30d) sparkline and Top 3 Sub-costs
    svc_rows = ""
    for s in data["top_services"][:8]:
        s_trend = _render_sparkline(s.get("trend", []), w=90, h=20, stroke="#58a6ff")
        s_icon = _get_service_icon_svg(s['service'], s.get('acronym', ''))
        sub_items = ""
        for sub in s.get("subcosts", [])[:3]:
            sub_items += (
                f'<div style="color:#8b949e;font-size:11px;padding-left:14px;margin-top:2px;">'
                f'↳ <span style="color:#c9d1d9;">{sub["subcost"]}</span>: '
                f'<span style="font-variant-numeric:tabular-nums;">${sub["usd"]:.4f}</span>'
                f'</div>'
            )
        if not sub_items:
            sub_items = f'<div style="color:#8b949e;font-size:11px;padding-left:14px;margin-top:2px;">↳ General Usage: ${s["usd"]:.4f}</div>'

        svc_rows += f"""
        <tr>
            <td style="vertical-align:top;">
                <div style="display:flex;align-items:flex-start;">
                    <span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);margin-right:8px;flex-shrink:0;margin-top:1px;">
                        {s_icon}
                    </span>
                    <div>
                        <strong style="color:#f0f6fc;">{s['service']}</strong>
                        <span class="tag" style="margin-left:6px;font-size:10px;">{s['acronym']}</span>
                        <div style="margin-top:4px;">{sub_items}</div>
                    </div>
                </div>
            </td>
            <td style="vertical-align:middle;text-align:center;">{s_trend}</td>
            <td class="num" style="vertical-align:top;font-weight:600;">${s['usd']:.4f}</td>
            <td class="num" style="vertical-align:top;color:#8b949e;">{s['percent']}%</td>
        </tr>
        """

    # 3. Breakdown by ApplicationName tag (30-day roll-up, gross)
    app_rows = ""
    for app in data.get("app_tag_breakdown", []):
        pct = app["percent"]
        app_rows += f"""
        <tr>
            <td><strong style="color:#f0f6fc;">{app['application']}</strong></td>
            <td class="num" style="font-weight:600;">${app['usd']:.2f}</td>
            <td class="num" style="color:#8b949e;">{pct}%</td>
            <td style="width:35%;vertical-align:middle;">
                <div style="background:#21262d;border-radius:4px;overflow:hidden;height:8px;width:100%;">
                    <div style="background:#238636;height:100%;width:{min(100, max(3, pct))}%;"></div>
                </div>
            </td>
        </tr>
        """

    # 3b. Breakdown by AWS Region (30-day roll-up, gross)
    region_rows = ""
    for reg in data.get("region_breakdown", []):
        pct = reg["percent"]
        region_rows += f"""
        <tr>
            <td><strong style="color:#f0f6fc;">{reg['region_name']}</strong> <span style="color:#8b949e;font-size:12px;">({reg['region']})</span></td>
            <td class="num" style="font-weight:600;">${reg['usd']:.2f}</td>
            <td class="num" style="color:#8b949e;">{pct}%</td>
            <td style="width:35%;vertical-align:middle;">
                <div style="background:#21262d;border-radius:4px;overflow:hidden;height:8px;width:100%;">
                    <div style="background:#58a6ff;height:100%;width:{min(100, max(3, pct))}%;"></div>
                </div>
            </td>
        </tr>
        """

    # 4. JSON payload embedded for client-side sorting and pagination
    daily_json_str = json.dumps(data["daily"]).replace("</script>", "<\\/script>")

    # 5. Live Latency Rows
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

    # Budget info details
    rem_usd = budget.get("remaining_usd", 0.0)
    budgeted_usd = budget.get("budgeted_usd", 0.0)
    days_avail = budget.get("days_available", 0)
    b_type = budget.get("budget_type", "monthly")
    if b_type == "fixed":
        budget_sub = f"${budgeted_usd:.2f} budgeted · {days_avail} days until expiry ({budget.get('expiry_date')})"
    else:
        budget_sub = f"${budgeted_usd:.2f}/mo · {days_avail} days left in cycle (resets day {budget.get('reset_day', 1)})"

    css = """
    :root {
      --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#8b949e;
      --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149;
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:24px 20px; }
    .container { max-width:1040px; margin:0 auto; }
    nav { display:flex; justify-content:space-between; align-items:center; padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:20px; }
    .nav-brand { font-size:18px; font-weight:700; display:flex; align-items:center; gap:10px; color:#f0f6fc; text-decoration:none; }
    .nav-links { display:flex; gap:16px; align-items:center; font-size:13px; }
    .nav-link { color:var(--muted); text-decoration:none; padding:4px 8px; border-radius:6px; }
    .nav-link:hover, .nav-link.active { color:var(--fg); background:#21262d; }
    .tag { background:#1f6feb33; color:var(--accent); border:1px solid #1f6feb88; font-size:12px; padding:2px 8px; border-radius:12px; font-weight:600; display:inline-block; }
    
    /* Interactive Engine Toggle Styles */
    .engine-switcher {
      display:inline-flex; align-items:center; background:#161b22; border:1px solid var(--line);
      border-radius:20px; padding:2px; font-size:12px; font-weight:600; gap:2px;
    }
    .engine-btn {
      padding:4px 12px; border-radius:16px; text-decoration:none; color:var(--muted); transition:all 0.15s ease;
      display:inline-flex; align-items:center; gap:5px;
    }
    .engine-btn:hover { color:var(--fg); }
    .engine-btn.active {
      background:#238636; color:#fff; font-weight:700; box-shadow:0 1px 3px rgba(0,0,0,0.4);
    }

    .cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:28px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:18px; position:relative; }
    .card-title { color:var(--muted); font-size:13px; margin-bottom:6px; }
    .big { font-size:26px; font-weight:700; color:var(--green); display:flex; align-items:center; justify-content:space-between; }
    .sub { color:var(--muted); font-size:12px; margin-top:6px; }
    table { width:100%; border-collapse:collapse; margin-bottom:24px; font-size:13px; }
    th, td { padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; }
    th { color:var(--muted); font-size:12px; user-select:none; }
    th.sortable { cursor:pointer; }
    th.sortable:hover { color:var(--fg); background:rgba(255,255,255,0.03); }
    .num { text-align:right; font-variant-numeric:tabular-nums; }
    .cost-red { color:var(--red) !important; font-weight:700; }
    .cost-yellow { color:var(--yellow) !important; font-weight:700; }
    .cost-green { color:var(--green) !important; font-weight:600; }
    .svc-badge {
      display:inline-block; margin:2px 3px 2px 0; padding:2px 6px; border-radius:4px;
      background:#21262d; border:1px solid var(--line); font-size:11px; text-decoration:none; color:var(--fg);
      cursor:help;
    }
    .svc-badge:hover { border-color:var(--accent); color:var(--accent); }
    .pagination { display:flex; justify-content:space-between; align-items:center; margin-top:-14px; margin-bottom:28px; font-size:12px; color:var(--muted); }
    .btn { background:#21262d; border:1px solid var(--line); color:var(--fg); padding:5px 12px; border-radius:6px; cursor:pointer; font-size:12px; }
    .btn:hover { background:#30363d; border-color:#8b949e; }
    .btn:disabled { opacity:0.4; cursor:not-allowed; }
    footer { margin-top:40px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; }
    """

    client_js = f"""
  const dailyData = {daily_json_str};
  let currentPage = 1;
  const pageSize = 10;
  let sortKey = 'date';
  let sortAsc = false;

  function renderTable() {{
    const tbody = document.getElementById('dailyTbody');
    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    const pageRecords = dailyData.slice(start, end);

    let html = '';
    for (const d of pageRecords) {{
      let svcsHtml = '';
      if (d.top_5_services && d.top_5_services.length > 0) {{
        for (const s of d.top_5_services) {{
          svcsHtml += '<a href="javascript:void(0)" class="svc-badge" title="' + s.service + ': $' + s.amount.toFixed(2) + ' (' + s.percent + '%)">' + s.short_display + '</a> ';
        }}
      }} else {{
        svcsHtml = '<span style="color:#8b949e;">No service spend recorded</span>';
      }}

      html += '<tr>' +
        '<td style="font-family:monospace;">' + d.date + '</td>' +
        '<td class="num ' + d.color_class + '" title="' + d.status_label + '">$' + d.gross_usd.toFixed(4) + '</td>' +
        '<td>' + svcsHtml + '</td>' +
      '</tr>';
    }}
    tbody.innerHTML = html;

    const total = dailyData.length;
    const actualEnd = Math.min(end, total);
    document.getElementById('pageInfo').innerText = 'Showing ' + (total === 0 ? 0 : start + 1) + '–' + actualEnd + ' of ' + total + ' days (Page ' + currentPage + ' of ' + Math.max(1, Math.ceil(total / pageSize)) + ')';
    document.getElementById('prevBtn').disabled = (currentPage <= 1);
    document.getElementById('nextBtn').disabled = (end >= total);

    ['date', 'gross_usd'].forEach(k => {{
      const el = document.getElementById('sort-' + k);
      if (el) el.innerText = (sortKey === k) ? (sortAsc ? '▲' : '▼') : '';
    }});
  }}

  function changePage(delta) {{
    const maxPage = Math.max(1, Math.ceil(dailyData.length / pageSize));
    currentPage = Math.max(1, Math.min(maxPage, currentPage + delta));
    renderTable();
  }}

  function sortTable(key) {{
    if (sortKey === key) {{
      sortAsc = !sortAsc;
    }} else {{
      sortKey = key;
      sortAsc = (key === 'date') ? false : true;
    }}

    dailyData.sort((a, b) => {{
      let va = a[sortKey];
      let vb = b[sortKey];
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    }});

    currentPage = 1;
    renderTable();
  }}

  document.addEventListener('DOMContentLoaded', () => {{
    renderTable();
  }});
    """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cloud Frugality — AWS Cost, Runway & Inventory Portal</title>
  <style>{css}</style>
</head>
<body>
<div class="container">
  <nav>
    <a href="/" class="nav-brand">Cloud Frugality <span class="tag">Tag: Frugality (Python :8090)</span></a>
    
    <!-- Real Engine Switcher & Backing Source Indicators -->
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
      <div class="engine-switcher">
        <a href="{engine_urls['python']}" class="engine-btn active" title="Currently Running on Python Server">
          <span>🐍 Python</span>
        </a>
        <a href="{engine_urls['rust']}" class="engine-btn" title="Switch to Rust Server">
          <span>🦀 Rust</span>
        </a>
      </div>

      <!-- Backing Source Indicator (AWS Emulator vs Real AWS) -->
      <span style="font-size:11px;font-weight:700;padding:3px 9px;border-radius:12px;background:rgba(210,153,34,0.15);color:{source_info['badge_color']};border:1px solid {source_info['badge_color']}66;" title="{source_info['detail']}">
        {source_info['badge_text']}
      </span>

      <!-- Data Partition Badge -->
      <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:12px;background:rgba(56,189,248,0.1);color:#38bdf8;border:1px solid rgba(56,189,248,0.3);" title="Data Partition: {source_info['partition']}">
        📁 {source_info['partition']}
      </span>
    </div>

    <div class="nav-links">
      <a href="/" class="nav-link active">Dashboard</a>
      <a href="/settings" class="nav-link">Settings & Budget</a>
      <a href="/api/costs" class="nav-link" target="_blank">Raw JSON API</a>
      <a href="/healthz" class="nav-link" target="_blank">Healthz</a>
    </div>
  </nav>

  <div class="cards">
    <div class="card">
      <div class="card-title">Last 30 Days (Gross Usage)</div>
      <div class="big">
        <span>${data['window_gross_usd']:.2f}</span>
        {main_sparkline}
      </div>
      <div class="sub">Pre-credit cloud consumption (DuckDB SQL over S3)</div>
    </div>
    <div class="card">
      <div class="card-title">Last 30 Days (Net Billed)</div>
      <div class="big">${data['window_net_usd']:.2f}</div>
      <div class="sub">Actual billed cash post promotional credits</div>
    </div>
    <div class="card">
      <div class="card-title">Credits Remaining</div>
      <div class="big">${rem_usd:.2f}</div>
      <div class="sub">{budget_sub}</div>
    </div>
    <div class="card">
      <div class="card-title">Tracked AWS Resources</div>
      <div class="big">{data['resource_count']}</div>
      <div class="sub">Active account inventory via Resource Tagging API</div>
    </div>
  </div>

  <div style="background:rgba(88,166,255,0.06);border:1px solid rgba(88,166,255,0.2);padding:10px 14px;border-radius:6px;margin-bottom:24px;font-size:12px;color:#c9d1d9;display:flex;justify-content:space-between;align-items:center;">
    <span>
      <strong>Active Daily Baseline:</strong> ${daily_baseline:.2f} USD/day.
      Legend: <span class="cost-green">■ &lt;70% (${round(0.70*daily_baseline,2):.2f})</span>,
      <span class="cost-yellow">■ 70%–100% (${round(0.70*daily_baseline,2):.2f}–${daily_baseline:.2f})</span>,
      <span class="cost-red">■ &gt;Baseline (&gt;${daily_baseline:.2f})</span>.
    </span>
    <a href="/settings" style="color:var(--accent);text-decoration:none;font-weight:600;">Configure Baseline & Budget →</a>
  </div>

  <h3 style="margin-bottom:10px;">Top Services Spend (30-day roll-up, gross)</h3>
  <table>
    <thead>
      <tr>
        <th>Service & Top 3 Sub-Costs</th>
        <th style="text-align:center;">Trend (30d)</th>
        <th class="num">Gross Cost (USD)</th>
        <th class="num">Share</th>
      </tr>
    </thead>
    <tbody>{svc_rows}</tbody>
  </table>

  <h3 style="margin-bottom:10px;">Breakdown by ApplicationName tag (30-day roll-up, gross)</h3>
  <table>
    <thead>
      <tr>
        <th>ApplicationName Tag</th>
        <th class="num">Gross Cost (USD)</th>
        <th class="num">Share</th>
        <th>Distribution</th>
      </tr>
    </thead>
    <tbody>{app_rows}</tbody>
  </table>

  <h3 style="margin-bottom:10px;">Breakdown by AWS Region (30-day roll-up, gross)</h3>
  <table>
    <thead>
      <tr>
        <th>AWS Region</th>
        <th class="num">Gross Cost (USD)</th>
        <th class="num">Share</th>
        <th>Distribution</th>
      </tr>
    </thead>
    <tbody>{region_rows}</tbody>
  </table>

  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <h3 style="margin:0;">Daily Cost History (Last 30 Days)</h3>
    <span style="font-size:12px;color:var(--muted);">Click headers to sort · 10 records per page</span>
  </div>

  <table id="dailyTable">
    <thead>
      <tr>
        <th class="sortable" onclick="sortTable('date')">Date (UTC) <span id="sort-date">▼</span></th>
        <th class="sortable num" onclick="sortTable('gross_usd')">Gross (USD) <span id="sort-gross_usd"></span></th>
        <th>Top 5 Services (Acronym, Spend, Share)</th>
      </tr>
    </thead>
    <tbody id="dailyTbody"></tbody>
  </table>

  <div class="pagination">
    <button class="btn" id="prevBtn" onclick="changePage(-1)">← Previous</button>
    <span id="pageInfo">Showing 1–10 of {len(data['daily'])} records</span>
    <button class="btn" id="nextBtn" onclick="changePage(1)">Next →</button>
  </div>

  <h3 style="margin-bottom:10px;">DuckDB Serverless Analytics Latency Breakdown</h3>
  <table>
    <thead><tr><th>Operation</th><th></th><th class="num">Latency / Share</th></tr></thead>
    <tbody>{lat_rows}</tbody>
  </table>

  <footer>
    <div>Cloud Frugality · Serverless AWS Spend & Runway Microservice (DuckDB + S3 Backing Store)</div>
    <div>
      <a href="/settings" style="color:var(--accent);margin-right:12px;">Configuration</a>
      <a href="/api/costs" style="color:var(--accent);margin-right:12px;">Raw JSON API</a>
      <a href="/healthz" style="color:var(--accent);">Health Check</a>
    </div>
  </footer>
</div>

<script>
{client_js}
</script>
</body>
</html>
"""


def _render_settings_html(settings: dict, budget: dict, message: str = "") -> str:
    b_type = settings.get("budget_type", "monthly")
    daily_base = float(settings.get("daily_baseline_usd", 1.00))
    m_amount = float(settings.get("monthly_credit_amount", 60.0))
    m_reset = int(settings.get("monthly_reset_day", 1))
    f_amount = float(settings.get("fixed_budget_amount", 500.0))
    f_exp = str(settings.get("fixed_budget_expiry", ""))

    msg_box = ""
    if message:
        msg_box = (
            f'<div style="background:#23863622;border:1px solid #23863688;color:#3fb950;padding:12px;border-radius:6px;margin-bottom:20px;font-size:13px;">'
            f'✓ {message}'
            f'</div>'
        )

    css = """
    :root {
      --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#8b949e;
      --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149;
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:24px 20px; }
    .container { max-width:820px; margin:0 auto; }
    nav { display:flex; justify-content:space-between; align-items:center; padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:20px; }
    .nav-brand { font-size:18px; font-weight:700; color:#f0f6fc; text-decoration:none; }
    .nav-links { display:flex; gap:16px; font-size:13px; }
    .nav-link { color:var(--muted); text-decoration:none; padding:4px 8px; border-radius:6px; }
    .nav-link:hover, .nav-link.active { color:var(--fg); background:#21262d; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:24px; margin-bottom:24px; }
    h1 { font-size:24px; margin:0 0 8px; }
    h3 { font-size:16px; margin:0 0 16px; color:#f0f6fc; border-bottom:1px solid var(--line); padding-bottom:8px; }
    .form-group { margin-bottom:18px; }
    label { display:block; font-size:13px; color:var(--fg); font-weight:600; margin-bottom:6px; }
    .hint { font-size:12px; color:var(--muted); margin-top:4px; }
    input[type="number"], input[type="date"], select {
      width:100%; max-width:320px; background:#0d1117; border:1px solid var(--line);
      color:var(--fg); padding:8px 12px; border-radius:6px; font-size:13px;
    }
    input[type="number"]:focus, input[type="date"]:focus, select:focus {
      border-color:var(--accent); outline:none;
    }
    .radio-option { display:flex; align-items:flex-start; gap:10px; margin-bottom:12px; padding:10px; border-radius:6px; border:1px solid var(--line); background:#161b22; }
    .btn { background:#238636; border:1px solid rgba(240,246,252,0.1); color:#fff; padding:8px 18px; border-radius:6px; font-weight:600; cursor:pointer; font-size:13px; }
    .btn:hover { background:#2ea043; }
    .status-badge { padding:3px 8px; border-radius:12px; font-size:11px; font-weight:600; display:inline-block; }
    """

    client_js = """
  function toggleBudgetOptions() {
    const isFixed = document.getElementById('type_fixed').checked;
    document.getElementById('fixed_fields').style.display = isFixed ? 'block' : 'none';
    document.getElementById('monthly_fields').style.display = isFixed ? 'none' : 'block';
  }
    """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Settings & Budget — Cloud Frugality</title>
  <style>{css}</style>
</head>
<body>
<div class="container">
  <nav>
    <a href="/" class="nav-brand">Cloud Frugality</a>
    <div class="nav-links">
      <a href="/" class="nav-link">Dashboard</a>
      <a href="/settings" class="nav-link active">Settings & Budget</a>
      <a href="/api/settings" class="nav-link" target="_blank">Settings JSON</a>
    </div>
  </nav>

  <h1>Configuration & Budget Tracking</h1>
  <p style="color:var(--muted);margin:0 0 24px;font-size:13px;">
    Track budgeted $ and days available, configure fixed or monthly credit runway, and adjust daily cost baseline thresholds.
  </p>

  {msg_box}

  <div class="card">
    <h3>Current Budget & Days Available</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:16px;">
      <div>
        <div style="color:var(--muted);font-size:12px;">Active Model</div>
        <div style="font-size:18px;font-weight:700;margin-top:2px;">{'Fixed Budget' if b_type == 'fixed' else 'Monthly Credits'}</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Budgeted Amount</div>
        <div style="font-size:18px;font-weight:700;color:var(--accent);margin-top:2px;">${budget.get('budgeted_usd', 0.0):.2f}</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Days Available</div>
        <div style="font-size:18px;font-weight:700;color:var(--green);margin-top:2px;">{budget.get('days_available', 0)} days</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Estimated Remaining</div>
        <div style="font-size:18px;font-weight:700;color:var(--green);margin-top:2px;">${budget.get('remaining_usd', 0.0):.2f}</div>
      </div>
    </div>
  </div>

  <form method="POST" action="/settings" class="card">
    <h3>Budget Runway Options</h3>

    <div class="form-group">
      <label>Select Budget Tracking Option:</label>
      <div class="radio-option">
        <input type="radio" id="type_monthly" name="budget_type" value="monthly" {'checked' if b_type == 'monthly' else ''} onchange="toggleBudgetOptions()">
        <div>
          <label for="type_monthly" style="margin:0;cursor:pointer;">Option 2: Monthly Credits (Resets Every Month)</label>
          <div class="hint">Credits expire on a specific day of the month and reset automatically every month.</div>
        </div>
      </div>
      <div class="radio-option">
        <input type="radio" id="type_fixed" name="budget_type" value="fixed" {'checked' if b_type == 'fixed' else ''} onchange="toggleBudgetOptions()">
        <div>
          <label for="type_fixed" style="margin:0;cursor:pointer;">Option 1: Fixed Budget with Calendar Expiry</label>
          <div class="hint">Specify a fixed pool of dollars and a definite expiration date.</div>
        </div>
      </div>
    </div>

    <!-- Monthly credits inputs -->
    <div id="monthly_fields" style="display:{'block' if b_type == 'monthly' else 'none'};border-left:2px solid var(--accent);padding-left:14px;margin-bottom:20px;">
      <div class="form-group">
        <label for="monthly_credit_amount">Monthly Credit Grant ($ USD):</label>
        <input type="number" step="0.01" min="0" id="monthly_credit_amount" name="monthly_credit_amount" value="{m_amount}">
        <div class="hint">Granted monthly credits amount (e.g. $60.00).</div>
      </div>
      <div class="form-group">
        <label for="monthly_reset_day">Monthly Reset Day of Month (1–31):</label>
        <input type="number" min="1" max="31" id="monthly_reset_day" name="monthly_reset_day" value="{m_reset}">
        <div class="hint">The calendar day each month when the credit pool resets (e.g. 1st or 15th).</div>
      </div>
    </div>

    <!-- Fixed budget inputs -->
    <div id="fixed_fields" style="display:{'block' if b_type == 'fixed' else 'none'};border-left:2px solid var(--accent);padding-left:14px;margin-bottom:20px;">
      <div class="form-group">
        <label for="fixed_budget_amount">Fixed Budget ($ USD):</label>
        <input type="number" step="0.01" min="0" id="fixed_budget_amount" name="fixed_budget_amount" value="{f_amount}">
        <div class="hint">Total dollar budget available across the fixed period.</div>
      </div>
      <div class="form-group">
        <label for="fixed_budget_expiry">Budget Expiration Date (YYYY-MM-DD):</label>
        <input type="date" id="fixed_budget_expiry" name="fixed_budget_expiry" value="{f_exp}">
        <div class="hint">Date on which this fixed budget expires.</div>
      </div>
    </div>

    <h3 style="margin-top:24px;">Daily Baseline Costs</h3>
    <div class="form-group">
      <label for="daily_baseline_usd">Daily Baseline Cost ($ USD/day):</label>
      <input type="number" step="0.01" min="0.01" id="daily_baseline_usd" name="daily_baseline_usd" value="{daily_base}">
      <div class="hint">
        Default: <strong>$1.00</strong>. Used to color the Gross column in Daily Cost History:
        <br><span style="color:var(--red);">■ RED</span>: Day spend &gt; baseline.
        <br><span style="color:var(--yellow);">■ YELLOW</span>: Day spend &ge; 70% of baseline (closer to baseline).
        <br><span style="color:var(--green);">■ GREEN</span>: Day spend &lt; 70% of baseline.
      </div>
    </div>

    <div style="margin-top:24px;">
      <button type="submit" class="btn">Save Configuration</button>
      <a href="/" style="color:var(--muted);text-decoration:none;font-size:13px;margin-left:14px;">Cancel & Return</a>
    </div>
  </form>
</div>

<script>
{client_js}
</script>
</body>
</html>
"""


def _seed_sample_data_if_empty(store: FrugalityStore) -> None:
    """Seed representative 30-day data if backing store is fresh."""
    existing = store.list_all_daily_costs()
    if existing:
        return

    today = dt.datetime.now(dt.timezone.utc).date()
    sample_records = []
    # Generate 30 days of realistic serverless AWS spending
    for i in range(1, 31):
        d = (today - dt.timedelta(days=i)).isoformat()
        # Daily pattern: RDS Aurora Serverless, CloudWatch, Lambda, S3, KMS
        rds_cost = round(0.48 + (i % 5) * 0.05, 4)
        cw_cost = round(0.12 + (i % 3) * 0.02, 4)
        lam_cost = round(0.04 + (i % 4) * 0.01, 4)
        s3_cost = round(0.03 + (i % 2) * 0.01, 4)
        kms_cost = round(0.01 + (i % 3) * 0.005, 4)
        gross = round(rds_cost + cw_cost + lam_cost + s3_cost + kms_cost, 4)

        sample_records.append({
            "date": d,
            "unblended_usd": gross,
            "blended_usd": gross,
            "net_usd": 0.0,
            "credit_usd": -gross,
            "gross_usd": gross,
            "services": {
                "Amazon Relational Database Service": rds_cost,
                "AmazonCloudWatch": cw_cost,
                "AWS Lambda": lam_cost,
                "Amazon Simple Storage Service": s3_cost,
                "AWS Key Management Service": kms_cost,
            },
            "service_subcosts": {
                "Amazon Relational Database Service": {
                    "Aurora Serverless v2 ACU": round(rds_cost * 0.70, 4),
                    "Storage and IOs": round(rds_cost * 0.20, 4),
                    "Backup Retention": round(rds_cost * 0.10, 4),
                },
                "AmazonCloudWatch": {
                    "MetricStorage": round(cw_cost * 0.50, 4),
                    "LogIngestion": round(cw_cost * 0.35, 4),
                    "Alarms": round(cw_cost * 0.15, 4),
                },
                "AWS Lambda": {
                    "ARM Graviton Invocations": round(lam_cost * 0.60, 4),
                    "Duration Execution": round(lam_cost * 0.40, 4),
                },
                "Amazon Simple Storage Service": {
                    "StandardStorage": round(s3_cost * 0.70, 4),
                    "API Requests": round(s3_cost * 0.30, 4),
                },
            },
            "app_tags": {
                "CloudFrugality-Python": round(gross * 0.65, 4),
                "DataLake-DuckDB": round(gross * 0.25, 4),
                "CoreInfra": round(gross * 0.10, 4),
            },
            "regions": {
                "us-east-2": round(gross * 0.70, 4),
                "us-east-1": round(gross * 0.20, 4),
                "global": round(gross * 0.10, 4),
            },
            "plan_type": "AWS Free Tier & Promotional Credit",
            "credits_granted_usd": 60.0,
            "credits_remaining_usd": round(60.0 - (gross * i), 2),
            "credits_expiry": (today + dt.timedelta(days=150)).isoformat(),
        })

    for r in sample_records:
        store.save_daily_cost(r)

    # Seed resource inventory
    store.save_inventory({
        "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-collector": {
            "arn": "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-collector",
            "service": "lambda",
            "resource_type": "function",
            "region": REGION,
            "application_name": "Frugality",
            "tags": json.dumps({"Frugality": "true"}),
            "created_at": (today - dt.timedelta(days=35)).isoformat(),
        },
        "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-web": {
            "arn": "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-web",
            "service": "lambda",
            "resource_type": "function",
            "region": REGION,
            "application_name": "Frugality",
            "tags": json.dumps({"Frugality": "true"}),
            "created_at": (today - dt.timedelta(days=35)).isoformat(),
        },
        "arn:aws:s3:::cloud-frugality-data": {
            "arn": "arn:aws:s3:::cloud-frugality-data",
            "service": "s3",
            "resource_type": "bucket",
            "region": REGION,
            "application_name": "Frugality",
            "tags": json.dumps({"Frugality": "true"}),
            "created_at": (today - dt.timedelta(days=35)).isoformat(),
        },
    })


def lambda_handler(event: dict, context: Any) -> dict:
    raw_path = event.get("rawPath") or event.get("path") or "/"
    method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod") or "GET").upper()
    tracker = LatencyTracker()
    store = FrugalityStore()

    # Engine toggle delegation: if ?engine=rust, delegate to native Rust binary
    query_params = event.get("queryStringParameters") or {}
    requested_engine = (query_params.get("engine") or event.get("headers", {}).get("x-engine") or "").lower()
    if requested_engine == "rust":
        import subprocess
        # Search for compiled Rust binary
        real_dir = os.path.dirname(os.path.realpath(__file__))
        cur_dir = os.path.dirname(__file__)
        possible_bins = [
            os.path.abspath(os.path.join(real_dir, "..", "rust", "target", "debug", "cloud-frugality")),
            os.path.abspath(os.path.join(cur_dir, "rust", "target", "debug", "cloud-frugality")),
            os.path.abspath(os.path.join(real_dir, "..", "rust", "target", "release", "cloud-frugality")),
            os.path.abspath(os.path.join(cur_dir, "rust", "target", "release", "cloud-frugality")),
            os.path.expanduser("~/.cargo/bin/cloud-frugality"),
            "cloud-frugality",
        ]
        rust_bin = next((b for b in possible_bins if os.path.exists(b)), "cloud-frugality")
        body = event.get("body") or ""
        ct = (event.get("headers") or {}).get("content-type", "")
        try:
            cmd = [rust_bin, "request", "--method", method, "--path", raw_path, "--body", body, "--content-type", ct]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(res.stdout)
        except Exception as exc:
            log.warning("Rust delegation failed (%s), falling back to Python: %s", rust_bin, exc)

    # Seed sample data if empty
    _seed_sample_data_if_empty(store)

    # 0. CORS Preflight & Alibaba Cloud Quick BI Support
    cors_origin = (event.get("headers") or {}).get("origin") or (event.get("headers") or {}).get("Origin") or "*"
    if method == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": {
                "Access-Control-Allow-Origin": cors_origin if "alibabacloud.com" in cors_origin else "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS, HEAD",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "86400",
            },
            "body": "",
        }

    # Alibaba Cloud Quick BI Data API endpoint
    if raw_path in ("/ai/resource", "/api/resource"):
        data = store.query_cost_summary(window_days=COST_WINDOW_DAYS)
        records = data.get("services") or data.get("daily") or []
        res_payload = {
            "code": 200,
            "message": "success",
            "data": {
                "total": len(records),
                "pageSize": len(records),
                "pageNum": 1,
                "records": records,
            }
        }
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": cors_origin if "alibabacloud.com" in cors_origin else "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS, HEAD",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
                "Cache-Control": "no-store",
            },
            "body": json.dumps(res_payload, indent=2),
        }

    # 1. Health check & process identity
    if raw_path == "/healthz":
        source_info = store.get_backing_source_info()
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
                "engine": "DuckDB over S3/Local Parquet",
                "backing_source": source_info["source_type"],
                "is_emulator": source_info["is_emulator"],
                "partition": source_info["partition"],
                "source_detail": source_info["detail"],
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            }),
        }

    # 2. Configuration API / Page
    if raw_path in ("/settings", "/api/settings"):
        if method == "POST":
            t0 = time.perf_counter()
            body = event.get("body") or ""
            is_b64 = event.get("isBase64Encoded", False)
            if is_b64:
                import base64
                body = base64.b64decode(body).decode("utf-8")

            payload = {}
            content_type = event.get("headers", {}).get("content-type", "")
            if "application/json" in content_type:
                try:
                    payload = json.loads(body)
                except Exception:
                    payload = {}
            else:
                parsed = urllib.parse.parse_qs(body)
                for k, v in parsed.items():
                    payload[k] = v[0]

            saved = store.save_settings(payload)
            tracker.record("DuckDB / S3 Store", "Save Settings (config.json)", (time.perf_counter() - t0) * 1000)

            if raw_path == "/api/settings":
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"status": "saved", "settings": saved}, indent=2),
                }

            # For form post to /settings, render with confirmation message
            summary_data = store.query_cost_summary(window_days=COST_WINDOW_DAYS)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": _render_settings_html(saved, summary_data["budget"], message="Settings and budget successfully updated!"),
            }

        # GET request for settings
        settings = store.get_settings()
        if raw_path == "/api/settings":
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(settings, indent=2),
            }

        summary_data = store.query_cost_summary(window_days=COST_WINDOW_DAYS)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": _render_settings_html(settings, summary_data["budget"]),
        }

    # 3. Query spend analytics using DuckDB
    try:
        t0 = time.perf_counter()
        data = store.query_cost_summary(window_days=COST_WINDOW_DAYS)
        tracker.record("DuckDB Serverless Analytics", f"Execute SQL analytics over 30d records", (time.perf_counter() - t0) * 1000)
    except Exception as exc:
        log.error("Failed to query cost data: %s", exc, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc), "status": "error"}),
        }

    # 4. JSON Costs API
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

    # 5. Main Dashboard HTML
    headers = event.get("headers") or {}
    host = headers.get("host") or headers.get("Host") or ""
    html = _render_dashboard_html(data, tracker, host=host)
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": html,
    }
