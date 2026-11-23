//! Public Cloud Frugality web dashboard, settings management, and API handler in Rust.
//!
//! Rationale & Decisions:
//! - Implements a serverless-friendly, zero-external-template HTML renderer.
//! - Embeds SVG sparklines and service icons directly into the HTML to eliminate external CDN dependencies.
//! - Includes clickable column sorting (Date, Gross) and 10 records/page pagination in client-side JS.
//! - Inspects `/proc/self/comm` on `/healthz` to verify live runtime identity.
//! - Provides an interactive engine toggle linking between Python (:8090) and Rust (:8091).

use std::fs;
use std::time::Instant;

use crate::metrics::LatencyTracker;
use crate::store::{CostSummary, FrugalityStore, Settings};

/// HTTP response representation compatible with Lambda Function URLs or local HTTP server.
#[derive(Debug, Clone)]
pub struct HttpResponse {
    pub status_code: u16,
    pub headers: Vec<(String, String)>,
    pub body: String,
}

impl HttpResponse {
    pub fn html(status: u16, body: String) -> Self {
        Self {
            status_code: status,
            headers: vec![
                ("Content-Type".to_string(), "text/html; charset=utf-8".to_string()),
                ("Cache-Control".to_string(), "no-store".to_string()),
            ],
            body,
        }
    }

    pub fn json(status: u16, body: String) -> Self {
        Self {
            status_code: status,
            headers: vec![
                ("Content-Type".to_string(), "application/json".to_string()),
                ("Cache-Control".to_string(), "no-store".to_string()),
            ],
            body,
        }
    }
}

/// Reads the real Linux kernel process identity from `/proc/self/comm`.
pub fn get_process_comm() -> String {
    fs::read_to_string("/proc/self/comm")
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|_| "cloud-frugality".to_string())
}

/// Renders a lightweight, responsive SVG sparkline for 30-day spend trends.
pub fn render_sparkline(vals: &[f64], width: u32, height: u32, stroke: &str) -> String {
    if vals.is_empty() {
        return String::new();
    }
    let max_val = vals.iter().copied().fold(0.0_f64, f64::max).max(1.0);
    let n = vals.len();
    let mut pts = Vec::with_capacity(n);

    for (i, &v) in vals.iter().enumerate() {
        let x = 3.0 + (i as f64 / (n.max(2) - 1) as f64) * ((width - 6) as f64);
        let y = ((height - 4) as f64) - (v / max_val) * ((height - 8) as f64);
        pts.push((x, y));
    }

    let mut line_pts = String::new();
    for (i, (x, y)) in pts.iter().enumerate() {
        if i > 0 {
            line_pts.push(' ');
        }
        line_pts.push_str(&format!("{:.1},{:.1}", x, y));
    }

    let poly_pts = format!("{:.1},{} {} {:.1},{}", pts[0].0, height, line_pts, pts[n - 1].0, height);
    let last_pt = pts[n - 1];

    format!(
        "<svg width=\"{w}\" height=\"{h}\" viewBox=\"0 0 {w} {h}\" style=\"vertical-align:middle;display:inline-block;\">\n<polygon points=\"{poly}\" fill=\"{stroke}\" fill-opacity=\"0.18\"/>\n<polyline points=\"{line}\" fill=\"none\" stroke=\"{stroke}\" stroke-width=\"1.8\" stroke-linecap=\"round\"/>\n<circle cx=\"{cx:.1}\" cy=\"{cy:.1}\" r=\"2.5\" fill=\"{stroke}\"/>\n</svg>",
        w = width,
        h = height,
        poly = poly_pts,
        line = line_pts,
        stroke = stroke,
        cx = last_pt.0,
        cy = last_pt.1,
    )
}

/// Returns an appropriate royalty-free inline SVG icon for AWS services.
pub fn get_service_icon_svg(service_name: &str, acronym: &str) -> &'static str {
    let combined = format!("{} {}", service_name, acronym).to_lowercase();

    if combined.contains("rds") || combined.contains("relational database") || combined.contains("aurora") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#3b82f6\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><ellipse cx=\"12\" cy=\"5\" rx=\"9\" ry=\"3\"/><path d=\"M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5\"/><path d=\"M3 12c0 1.66 4 3 9 3s9-1.34 9-3\"/></svg>"
    } else if combined.contains("s3") || combined.contains("simple storage") || combined.contains("storage") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#10b981\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M19 11V4a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v7\"/><rect x=\"2\" y=\"11\" width=\"20\" height=\"11\" rx=\"2\"/><circle cx=\"12\" cy=\"16.5\" r=\"1.5\"/></svg>"
    } else if combined.contains("lambda") || combined.contains("lam") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#f59e0b\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polygon points=\"13 2 3 14 12 14 11 22 21 10 12 10 13 2\"/></svg>"
    } else if combined.contains("cloudwatch") || combined.contains("cw") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#ec4899\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M22 12h-4l-3 9L9 3l-3 9H2\"/></svg>"
    } else if combined.contains("ec2") || combined.contains("elastic compute") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#f97316\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect width=\"16\" height=\"16\" x=\"4\" y=\"4\" rx=\"2\"/><rect width=\"6\" height=\"6\" x=\"9\" y=\"9\" rx=\"1\"/><path d=\"M15 2v2\"/><path d=\"M15 20v2\"/><path d=\"M2 15h2\"/><path d=\"M2 9h2\"/><path d=\"M20 15h2\"/><path d=\"M20 9h2\"/><path d=\"M9 2v2\"/><path d=\"M9 20v2\"/></svg>"
    } else if combined.contains("dynamodb") || combined.contains("ddb") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#6366f1\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"/><path d=\"M3 9h18\"/><path d=\"M3 15h18\"/><path d=\"M9 3v18\"/></svg>"
    } else if combined.contains("kms") || combined.contains("key management") || combined.contains("secrets") {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#8b5cf6\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/></svg>"
    } else {
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#38bdf8\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9\"/><path d=\"M12 12v9\"/><path d=\"m8 17 4 4 4-4\"/></svg>"
    }
}

/// Resolves engine toggle URLs for Python and Rust dashboards.
///
/// Under AWS Lambda (or remote reverse proxies), URLs resolve to configured
/// Function URLs (via `PYTHON_WEB_URL` and `RUST_WEB_URL`) or relative path queries,
/// guaranteeing zero localhost/127.0.0.1 leakage.
/// In local development (outside AWS Lambda with localhost host), defaults to
/// dedicated ports (:8090 and :8091).
///
/// Formal safety verified via TLA+ specification in `formal_spec/EngineSwitch.tla`.
pub fn get_engine_switch_urls(current_host: &str) -> (String, String) {
    let is_aws = std::env::var("AWS_LAMBDA_FUNCTION_NAME").is_ok()
        || std::env::var("AWS_EXECUTION_ENV").is_ok()
        || std::env::var("LAMBDA_TASK_ROOT").is_ok();

    let python_env = std::env::var("PYTHON_WEB_URL").ok().filter(|s| !s.trim().is_empty());
    let rust_env = std::env::var("RUST_WEB_URL").ok().filter(|s| !s.trim().is_empty());

    let clean_host = current_host.split(':').next().unwrap_or("").trim().to_lowercase();
    let is_localhost = clean_host == "localhost" || clean_host == "127.0.0.1" || clean_host.is_empty();

    // Local development: strictly when running locally outside AWS Lambda
    if is_localhost && !is_aws {
        let py_url = python_env.unwrap_or_else(|| "http://localhost:8090/".to_string());
        let rust_url = rust_env.unwrap_or_else(|| "http://localhost:8091/".to_string());
        return (py_url, rust_url);
    }

    // Remote / AWS Deployment:
    let mut resolved_py = python_env.unwrap_or_else(|| "/?engine=python".to_string());
    let mut resolved_rust = rust_env.unwrap_or_else(|| "/?engine=rust".to_string());

    // Invariant: Never leak localhost to remote browsers
    if resolved_py.contains("localhost") || resolved_py.contains("127.0.0.1") {
        resolved_py = "/?engine=python".to_string();
    }
    if resolved_rust.contains("localhost") || resolved_rust.contains("127.0.0.1") {
        resolved_rust = "/?engine=rust".to_string();
    }

    (resolved_py, resolved_rust)
}

/// Renders the complete HTML dashboard string with interactive engine switcher.
pub fn render_dashboard_html(data: &CostSummary, tracker: &LatencyTracker, host: &str) -> String {
    let summary = tracker.summary();
    let daily_baseline = data.daily_baseline_usd;
    let budget = &data.budget;
    let (python_url, rust_url) = get_engine_switch_urls(host);

    // Overall 30-day gross sparkline
    let mut gross_chron: Vec<f64> = data.daily.iter().map(|d| d.gross_usd).collect();
    gross_chron.reverse();
    let main_sparkline = render_sparkline(&gross_chron, 130, 30, "#3fb950");

    // Top services rows
    let mut svc_rows = String::new();
    for s in data.top_services.iter().take(8) {
        let s_trend = render_sparkline(&s.trend, 90, 20, "#58a6ff");
        let s_icon = get_service_icon_svg(&s.service, &s.acronym);

        let mut sub_items = String::new();
        for sub in s.subcosts.iter().take(3) {
            sub_items.push_str(&format!(
                r#"<div style="color:#8b949e;font-size:11px;padding-left:14px;margin-top:2px;">↳ <span style="color:#c9d1d9;">{}</span>: <span style="font-variant-numeric:tabular-nums;">${:.4}</span></div>"#,
                sub.subcost, sub.usd
            ));
        }
        if sub_items.is_empty() {
            sub_items = format!(
                r#"<div style="color:#8b949e;font-size:11px;padding-left:14px;margin-top:2px;">↳ General Usage: ${:.4}</div>"#,
                s.usd
            );
        }

        svc_rows.push_str(&format!(
            r#"<tr>
  <td style="vertical-align:top;">
    <div style="display:flex;align-items:flex-start;">
      <span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);margin-right:8px;flex-shrink:0;margin-top:1px;">
        {icon}
      </span>
      <div>
        <strong style="color:#f0f6fc;">{svc}</strong>
        <span class="tag" style="margin-left:6px;font-size:10px;">{acronym}</span>
        <div style="margin-top:4px;">{subs}</div>
      </div>
    </div>
  </td>
  <td style="vertical-align:middle;text-align:center;">{trend}</td>
  <td class="num" style="vertical-align:top;font-weight:600;">${usd:.4}</td>
  <td class="num" style="vertical-align:top;color:#8b949e;">{pct:.1}%</td>
</tr>"#,
            icon = s_icon,
            svc = s.service,
            acronym = s.acronym,
            subs = sub_items,
            trend = s_trend,
            usd = s.usd,
            pct = s.percent
        ));
    }

    // ApplicationName breakdown rows
    let mut app_rows = String::new();
    for app in &data.app_tag_breakdown {
        let width_pct = app.percent.clamp(3.0, 100.0);
        app_rows.push_str(&format!(
            r#"<tr>
  <td><strong style="color:#f0f6fc;">{}</strong></td>
  <td class="num" style="font-weight:600;">${:.2}</td>
  <td class="num" style="color:#8b949e;">{:.1}%</td>
  <td style="width:35%;vertical-align:middle;">
    <div style="background:#21262d;border-radius:4px;overflow:hidden;height:8px;width:100%;">
      <div style="background:#238636;height:100%;width:{:.1}%;"></div>
    </div>
  </td>
</tr>"#,
            app.application, app.usd, app.percent, width_pct
        ));
    }

    // AWS Region breakdown rows
    let mut region_rows = String::new();
    for reg in &data.region_breakdown {
        let width_pct = reg.percent.clamp(3.0, 100.0);
        region_rows.push_str(&format!(
            r#"<tr>
  <td><strong style="color:#f0f6fc;">{}</strong> <span style="color:#8b949e;font-size:12px;">({})</span></td>
  <td class="num" style="font-weight:600;">${:.2}</td>
  <td class="num" style="color:#8b949e;">{:.1}%</td>
  <td style="width:35%;vertical-align:middle;">
    <div style="background:#21262d;border-radius:4px;overflow:hidden;height:8px;width:100%;">
      <div style="background:#58a6ff;height:100%;width:{:.1}%;"></div>
    </div>
  </td>
</tr>"#,
            reg.region_name, reg.region, reg.usd, reg.percent, width_pct
        ));
    }

    // Embedded JSON for client-side sorting & pagination
    let daily_json_str = serde_json::to_string(&data.daily).unwrap_or_else(|_| "[]".to_string());

    // Latency rows
    let mut lat_rows = String::new();
    for s in &summary.services {
        lat_rows.push_str(&format!(
            r#"<tr style="background:rgba(255,255,255,0.02);font-weight:600;">
  <td colspan="2">{}</td>
  <td class="num">{:.2} ms ({:.1}%)</td>
</tr>"#,
            s.service, s.total_ms, s.percent
        ));
        for sub in &s.sub_operations {
            lat_rows.push_str(&format!(
                r#"<tr style="color:#8b949e;font-size:12px;">
  <td style="padding-left:20px;">↳ {}</td>
  <td class="num"></td>
  <td class="num">{:.2} ms</td>
</tr>"#,
                sub.operation, sub.total_ms
            ));
        }
    }

    let budget_sub = if budget.budget_type == "fixed" {
        format!(
            "${:.2} budgeted · {} days until expiry ({})",
            budget.budgeted_usd,
            budget.days_available,
            budget.expiry_date.as_deref().unwrap_or("N/A")
        )
    } else {
        format!(
            "${:.2}/mo · {} days left in cycle (resets day {})",
            budget.budgeted_usd,
            budget.days_available,
            budget.reset_day.unwrap_or(1)
        )
    };

    let yellow_limit = ((0.70 * daily_baseline) * 100.0).round() / 100.0;
    let source_info = crate::store::get_backing_source_info();

    format!(
        r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cloud Frugality — AWS Cost, Runway & Inventory Portal (Rust Engine)</title>
  <style>
    :root {{
      --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#8b949e;
      --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:24px 20px; }}
    .container {{ max-width:1040px; margin:0 auto; }}
    nav {{ display:flex; justify-content:space-between; align-items:center; padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:20px; flex-wrap:wrap; gap:12px; }}
    .nav-brand {{ font-size:18px; font-weight:700; display:flex; align-items:center; gap:10px; color:#f0f6fc; text-decoration:none; }}
    .nav-links {{ display:flex; gap:14px; align-items:center; font-size:13px; }}
    .nav-link {{ color:var(--muted); text-decoration:none; padding:4px 8px; border-radius:6px; }}
    .nav-link:hover, .nav-link.active {{ color:var(--fg); background:#21262d; }}
    .tag {{ background:#1f6feb33; color:var(--accent); border:1px solid #1f6feb88; font-size:12px; padding:2px 8px; border-radius:12px; font-weight:600; display:inline-block; }}
    
    /* Interactive Engine Toggle Styles */
    .engine-switcher {{
      display:inline-flex; align-items:center; background:#161b22; border:1px solid var(--line);
      border-radius:20px; padding:2px; font-size:12px; font-weight:600; gap:2px;
    }}
    .engine-btn {{
      padding:4px 12px; border-radius:16px; text-decoration:none; color:var(--muted); transition:all 0.15s ease;
      display:inline-flex; align-items:center; gap:5px;
    }}
    .engine-btn:hover {{ color:var(--fg); }}
    .engine-btn.active {{
      background:#f85149; color:#fff; font-weight:700; box-shadow:0 1px 3px rgba(0,0,0,0.4);
    }}
    
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:28px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:18px; position:relative; }}
    .card-title {{ color:var(--muted); font-size:13px; margin-bottom:6px; }}
    .big {{ font-size:26px; font-weight:700; color:var(--green); display:flex; align-items:center; justify-content:space-between; }}
    .sub {{ color:var(--muted); font-size:12px; margin-top:6px; }}
    table {{ width:100%; border-collapse:collapse; margin-bottom:24px; font-size:13px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ color:var(--muted); font-size:12px; user-select:none; }}
    th.sortable {{ cursor:pointer; }}
    th.sortable:hover {{ color:var(--fg); background:rgba(255,255,255,0.03); }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .cost-red {{ color:var(--red) !important; font-weight:700; }}
    .cost-yellow {{ color:var(--yellow) !important; font-weight:700; }}
    .cost-green {{ color:var(--green) !important; font-weight:600; }}
    .svc-badge {{
      display:inline-block; margin:2px 3px 2px 0; padding:2px 6px; border-radius:4px;
      background:#21262d; border:1px solid var(--line); font-size:11px; text-decoration:none; color:var(--fg);
      cursor:help;
    }}
    .svc-badge:hover {{ border-color:var(--accent); color:var(--accent); }}
    .pagination {{ display:flex; justify-content:space-between; align-items:center; margin-top:-14px; margin-bottom:28px; font-size:12px; color:var(--muted); }}
    .btn {{ background:#21262d; border:1px solid var(--line); color:var(--fg); padding:5px 12px; border-radius:6px; cursor:pointer; font-size:12px; }}
    .btn:hover {{ background:#30363d; border-color:#8b949e; }}
    .btn:disabled {{ opacity:0.4; cursor:not-allowed; }}
    footer {{ margin-top:40px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; }}
  </style>
</head>
<body>
<div class="container">
  <nav>
    <a href="/" class="nav-brand">
      Cloud Frugality
      <span class="tag" style="background:#da363322;color:#f85149;border-color:#da363388;">Tag: Frugality (Rust Engine :8091)</span>
    </a>
    
    <!-- Real Engine Switcher & Backing Source Indicators -->
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
      <div class="engine-switcher">
        <a href="{python_url}" class="engine-btn" title="Switch to Python Server">
          <span>🐍 Python</span>
        </a>
        <a href="{rust_url}" class="engine-btn active" title="Currently Running on Rust Server">
          <span>🦀 Rust</span>
        </a>
      </div>

      <!-- Backing Source Indicator (AWS Emulator vs Real AWS) -->
      <span style="font-size:11px;font-weight:700;padding:3px 9px;border-radius:12px;background:rgba(210,153,34,0.15);color:{source_color};border:1px solid {source_color}66;" title="{source_detail}">
        {source_text}
      </span>

      <!-- Data Partition Badge -->
      <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:12px;background:rgba(56,189,248,0.1);color:#38bdf8;border:1px solid rgba(56,189,248,0.3);" title="Data Partition: {source_part}">
        📁 {source_part}
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
        <span>${window_gross:.2}</span>
        {sparkline}
      </div>
      <div class="sub">Pre-credit cloud consumption (Zero-Idle Rust Engine)</div>
    </div>
    <div class="card">
      <div class="card-title">Last 30 Days (Net Billed)</div>
      <div class="big">${window_net:.2}</div>
      <div class="sub">Actual billed cash post promotional credits</div>
    </div>
    <div class="card">
      <div class="card-title">Credits Remaining</div>
      <div class="big">${rem_usd:.2}</div>
      <div class="sub">{budget_sub}</div>
    </div>
    <div class="card">
      <div class="card-title">Tracked AWS Resources</div>
      <div class="big">{res_count}</div>
      <div class="sub">Active account inventory via Resource Tagging API</div>
    </div>
  </div>

  <div style="background:rgba(88,166,255,0.06);border:1px solid rgba(88,166,255,0.2);padding:10px 14px;border-radius:6px;margin-bottom:24px;font-size:12px;color:#c9d1d9;display:flex;justify-content:space-between;align-items:center;">
    <span>
      <strong>Active Daily Baseline:</strong> ${daily_base:.2} USD/day.
      Legend: <span class="cost-green">■ &lt;70% (${yellow_limit:.2})</span>,
      <span class="cost-yellow">■ 70%–100% (${yellow_limit:.2}–${daily_base:.2})</span>,
      <span class="cost-red">■ &gt;Baseline (&gt;${daily_base:.2})</span>.
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
    <span id="pageInfo">Showing 1–10 of {rec_count} records</span>
    <button class="btn" id="nextBtn" onclick="changePage(1)">Next →</button>
  </div>

  <h3 style="margin-bottom:10px;">Operational Instrumentation & Latency Breakdown (Rust Engine)</h3>
  <table>
    <thead><tr><th>Operation</th><th></th><th class="num">Latency / Share</th></tr></thead>
    <tbody>{lat_rows}</tbody>
  </table>

  <footer>
    <div>Cloud Frugality · Serverless AWS Spend & Runway Microservice (Rust Engine on Port 8091)</div>
    <div>
      <a href="/settings" style="color:var(--accent);margin-right:12px;">Configuration</a>
      <a href="/api/costs" style="color:var(--accent);margin-right:12px;">Raw JSON API</a>
      <a href="/healthz" style="color:var(--accent);">Health Check</a>
    </div>
  </footer>
</div>

<script>
  const dailyData = {daily_json};
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
</script>
</body>
</html>"#,
        window_gross = data.window_gross_usd,
        sparkline = main_sparkline,
        window_net = data.window_net_usd,
        rem_usd = budget.remaining_usd,
        budget_sub = budget_sub,
        res_count = data.resource_count,
        daily_base = daily_baseline,
        yellow_limit = yellow_limit,
        svc_rows = svc_rows,
        app_rows = app_rows,
        region_rows = region_rows,
        rec_count = data.daily.len(),
        lat_rows = lat_rows,
        daily_json = daily_json_str,
        source_color = source_info.badge_color,
        source_detail = source_info.detail,
        source_text = source_info.badge_text,
        source_part = source_info.partition
    )
}

/// Renders the Settings and Budget Configuration HTML page.
pub fn render_settings_html(settings: &Settings, budget: &crate::store::BudgetInfo, message: Option<&str>) -> String {
    let b_type = &settings.budget_type;
    let is_fixed = b_type == "fixed";

    let msg_box = if let Some(msg) = message {
        format!(
            r#"<div style="background:#23863622;border:1px solid #23863688;color:#3fb950;padding:12px;border-radius:6px;margin-bottom:20px;font-size:13px;">✓ {}</div>"#,
            msg
        )
    } else {
        String::new()
    };

    format!(
        r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Settings & Budget — Cloud Frugality (Rust Engine)</title>
  <style>
    :root {{
      --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#8b949e;
      --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:24px 20px; }}
    .container {{ max-width:820px; margin:0 auto; }}
    nav {{ display:flex; justify-content:space-between; align-items:center; padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:20px; }}
    .nav-brand {{ font-size:18px; font-weight:700; color:#f0f6fc; text-decoration:none; }}
    .nav-links {{ display:flex; gap:16px; font-size:13px; }}
    .nav-link {{ color:var(--muted); text-decoration:none; padding:4px 8px; border-radius:6px; }}
    .nav-link:hover, .nav-link.active {{ color:var(--fg); background:#21262d; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:24px; margin-bottom:24px; }}
    h1 {{ font-size:24px; margin:0 0 8px; }}
    h3 {{ font-size:16px; margin:0 0 16px; color:#f0f6fc; border-bottom:1px solid var(--line); padding-bottom:8px; }}
    .form-group {{ margin-bottom:18px; }}
    label {{ display:block; font-size:13px; color:var(--fg); font-weight:600; margin-bottom:6px; }}
    .hint {{ font-size:12px; color:var(--muted); margin-top:4px; }}
    input[type="number"], input[type="date"], select {{
      width:100%; max-width:320px; background:#0d1117; border:1px solid var(--line);
      color:var(--fg); padding:8px 12px; border-radius:6px; font-size:13px;
    }}
    input[type="number"]:focus, input[type="date"]:focus, select:focus {{
      border-color:var(--accent); outline:none;
    }}
    .radio-option {{ display:flex; align-items:flex-start; gap:10px; margin-bottom:12px; padding:10px; border-radius:6px; border:1px solid var(--line); background:#161b22; }}
    .btn {{ background:#238636; border:1px solid rgba(240,246,252,0.1); color:#fff; padding:8px 18px; border-radius:6px; font-weight:600; cursor:pointer; font-size:13px; }}
    .btn:hover {{ background:#2ea043; }}
  </style>
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
        <div style="font-size:18px;font-weight:700;margin-top:2px;">{model_name}</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Budgeted Amount</div>
        <div style="font-size:18px;font-weight:700;color:var(--accent);margin-top:2px;">${budgeted:.2}</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Days Available</div>
        <div style="font-size:18px;font-weight:700;color:var(--green);margin-top:2px;">{days_avail} days</div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;">Estimated Remaining</div>
        <div style="font-size:18px;font-weight:700;color:var(--green);margin-top:2px;">${remaining:.2}</div>
      </div>
    </div>
  </div>

  <form method="POST" action="/settings" class="card">
    <h3>Budget Runway Options</h3>

    <div class="form-group">
      <label>Select Budget Tracking Option:</label>
      <div class="radio-option">
        <input type="radio" id="type_monthly" name="budget_type" value="monthly" {monthly_checked} onchange="toggleBudgetOptions()">
        <div>
          <label for="type_monthly" style="margin:0;cursor:pointer;">Option 2: Monthly Credits (Resets Every Month)</label>
          <div class="hint">Credits expire on a specific day of the month and reset automatically every month.</div>
        </div>
      </div>
      <div class="radio-option">
        <input type="radio" id="type_fixed" name="budget_type" value="fixed" {fixed_checked} onchange="toggleBudgetOptions()">
        <div>
          <label for="type_fixed" style="margin:0;cursor:pointer;">Option 1: Fixed Budget with Calendar Expiry</label>
          <div class="hint">Specify a fixed pool of dollars and a definite expiration date.</div>
        </div>
      </div>
    </div>

    <!-- Monthly credits inputs -->
    <div id="monthly_fields" style="display:{monthly_display};border-left:2px solid var(--accent);padding-left:14px;margin-bottom:20px;">
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
    <div id="fixed_fields" style="display:{fixed_display};border-left:2px solid var(--accent);padding-left:14px;margin-bottom:20px;">
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
  function toggleBudgetOptions() {{
    const isFixed = document.getElementById('type_fixed').checked;
    document.getElementById('fixed_fields').style.display = isFixed ? 'block' : 'none';
    document.getElementById('monthly_fields').style.display = isFixed ? 'none' : 'block';
  }}
</script>
</body>
</html>"#,
        msg_box = msg_box,
        model_name = if is_fixed { "Fixed Budget" } else { "Monthly Credits" },
        budgeted = budget.budgeted_usd,
        days_avail = budget.days_available,
        remaining = budget.remaining_usd,
        monthly_checked = if !is_fixed { "checked" } else { "" },
        fixed_checked = if is_fixed { "checked" } else { "" },
        monthly_display = if !is_fixed { "block" } else { "none" },
        fixed_display = if is_fixed { "block" } else { "none" },
        m_amount = settings.monthly_credit_amount,
        m_reset = settings.monthly_reset_day,
        f_amount = settings.fixed_budget_amount,
        f_exp = settings.fixed_budget_expiry,
        daily_base = settings.daily_baseline_usd
    )
}

/// Unified request handler for Cloud Frugality endpoints with default host.
pub fn handle_request(
    method: &str,
    path: &str,
    body: &str,
    content_type: &str,
    store: &FrugalityStore,
) -> HttpResponse {
    handle_request_with_host(method, path, body, content_type, "", store)
}

/// Unified request handler for Cloud Frugality endpoints with explicit host resolution.
pub fn handle_request_with_host(
    method: &str,
    path: &str,
    body: &str,
    content_type: &str,
    host: &str,
    store: &FrugalityStore,
) -> HttpResponse {
    let mut tracker = LatencyTracker::new();
    let method_upper = method.to_uppercase();

    // 1. /healthz endpoint - runtime integrity check
    if path == "/healthz" {
        let source_info = crate::store::get_backing_source_info();
        let health_data = serde_json::json!({
            "status": "healthy",
            "service": "cloud-frugality",
            "engine": "rust",
            "runtime": format!("rust {}", env!("CARGO_PKG_VERSION")),
            "platform": std::env::consts::OS,
            "comm": get_process_comm(),
            "pid": std::process::id(),
            "region": std::env::var("AWS_REGION").unwrap_or_else(|_| "us-east-2".to_string()),
            "tag": "Frugality",
            "backing_source": source_info.source_type,
            "is_emulator": source_info.is_emulator,
            "partition": source_info.partition,
            "source_detail": source_info.detail,
            "timestamp": chrono::Utc::now().to_rfc3339()
        });
        return HttpResponse::json(200, serde_json::to_string_pretty(&health_data).unwrap());
    }

    // 2. Settings management (/settings and /api/settings)
    if path == "/settings" || path == "/api/settings" {
        if method_upper == "POST" {
            let t0 = Instant::now();
            let mut current = store.get_settings();

            if content_type.contains("application/json") {
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(body) {
                    if let Some(n) = val.get("daily_baseline_usd").and_then(|v| v.as_f64()) {
                        current.daily_baseline_usd = (n * 100.0).round() / 100.0;
                    }
                    if let Some(t) = val.get("budget_type").and_then(|v| v.as_str()) {
                        current.budget_type = t.to_string();
                    }
                    if let Some(m) = val.get("monthly_credit_amount").and_then(|v| v.as_f64()) {
                        current.monthly_credit_amount = (m * 100.0).round() / 100.0;
                    }
                    if let Some(d) = val.get("monthly_reset_day").and_then(|v| v.as_u64()) {
                        current.monthly_reset_day = (d as u32).clamp(1, 31);
                    }
                    if let Some(f) = val.get("fixed_budget_amount").and_then(|v| v.as_f64()) {
                        current.fixed_budget_amount = (f * 100.0).round() / 100.0;
                    }
                    if let Some(e) = val.get("fixed_budget_expiry").and_then(|v| v.as_str()) {
                        current.fixed_budget_expiry = e.to_string();
                    }
                }
            } else {
                for pair in body.split('&') {
                    let mut parts = pair.splitn(2, '=');
                    let k = parts.next().unwrap_or("").trim();
                    let v = parts.next().unwrap_or("").trim();
                    match k {
                        "daily_baseline_usd" => {
                            if let Ok(n) = v.parse::<f64>() {
                                current.daily_baseline_usd = (n * 100.0).round() / 100.0;
                            }
                        }
                        "budget_type" => {
                            current.budget_type = v.to_string();
                        }
                        "monthly_credit_amount" => {
                            if let Ok(n) = v.parse::<f64>() {
                                current.monthly_credit_amount = (n * 100.0).round() / 100.0;
                            }
                        }
                        "monthly_reset_day" => {
                            if let Ok(n) = v.parse::<u32>() {
                                current.monthly_reset_day = n.clamp(1, 31);
                            }
                        }
                        "fixed_budget_amount" => {
                            if let Ok(n) = v.parse::<f64>() {
                                current.fixed_budget_amount = (n * 100.0).round() / 100.0;
                            }
                        }
                        "fixed_budget_expiry" => {
                            current.fixed_budget_expiry = v.to_string();
                        }
                        _ => {}
                    }
                }
            }

            let saved = store.save_settings(current);
            tracker.record("Frugality Storage Engine", "Save Settings (config.json)", t0.elapsed().as_secs_f64() * 1000.0);

            if path == "/api/settings" {
                let resp = serde_json::json!({
                    "status": "saved",
                    "settings": saved
                });
                return HttpResponse::json(200, serde_json::to_string_pretty(&resp).unwrap());
            }

            let summary = store.query_cost_summary(30);
            let html = render_settings_html(&saved, &summary.budget, Some("Settings and budget successfully updated!"));
            return HttpResponse::html(200, html);
        }

        // GET request for settings
        let settings = store.get_settings();
        if path == "/api/settings" {
            return HttpResponse::json(200, serde_json::to_string_pretty(&settings).unwrap());
        }

        let summary = store.query_cost_summary(30);
        let html = render_settings_html(&settings, &summary.budget, None);
        return HttpResponse::html(200, html);
    }

    // 3. Analytics query execution
    let t0 = Instant::now();
    let mut data = store.query_cost_summary(30);
    tracker.record(
        "Frugality Analytics Engine",
        "Query 30-day Spend, Sub-costs & Badges",
        t0.elapsed().as_secs_f64() * 1000.0,
    );

    // 4. /api/costs endpoint
    if path == "/api/costs" {
        data.latency_breakdown = Some(tracker.summary());
        return HttpResponse::json(200, serde_json::to_string_pretty(&data).unwrap());
    }

    // 5. Dashboard HTML root
    let html = render_dashboard_html(&data, &tracker, host);
    HttpResponse::html(200, html)
}
