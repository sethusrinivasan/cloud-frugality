//! Model Context Protocol (MCP) Server for Cloud Frugality in Rust.
//!
//! Exposes Cloud Frugality cost telemetry, promotional credit runway, and 1M-record
//! multi-region usage dataset directly to AI agents via standard JSON-RPC 2.0 over stdio.

use std::io::{self, BufRead, Write};

use serde_json::{json, Value};

use crate::paginator::get_paginated_records;
use crate::store::{get_backing_source_info, FrugalityStore};

/// Runs the standard JSON-RPC 2.0 MCP event loop over stdio.
pub fn run_mcp_stdio_server(store: &FrugalityStore) {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };

        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        if let Ok(req) = serde_json::from_str::<Value>(trimmed) {
            if let Some(resp) = handle_mcp_message(&req, store) {
                let resp_str = serde_json::to_string(&resp).unwrap_or_default();
                let _ = writeln!(stdout, "{}", resp_str);
                let _ = stdout.flush();
            }
        }
    }
}

/// Dispatches an incoming MCP JSON-RPC message.
pub fn handle_mcp_message(req: &Value, store: &FrugalityStore) -> Option<Value> {
    let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
    let id = req.get("id");

    // Notifications (no ID)
    if id.is_none() {
        return None;
    }

    let id_val = id.unwrap().clone();

    match method {
        "initialize" => Some(json!({
            "jsonrpc": "2.0",
            "id": id_val,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "cloud-frugality-rust",
                    "version": env!("CARGO_PKG_VERSION")
                }
            }
        })),

        "ping" => Some(json!({
            "jsonrpc": "2.0",
            "id": id_val,
            "result": {}
        })),

        "tools/list" => Some(json!({
            "jsonrpc": "2.0",
            "id": id_val,
            "result": {
                "tools": [
                    {
                        "name": "get_health",
                        "description": "Checks Cloud Frugality system health, active runtime engine (Rust), partition, and backing source (Real AWS or Emulator).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "get_cost_summary",
                        "description": "Retrieves 30-day AWS spend summary, top services breakdown, daily records, and promotional credit runway.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "window_days": {
                                    "type": "integer",
                                    "description": "Number of days of historical telemetry (default: 30)"
                                }
                            }
                        }
                    },
                    {
                        "name": "query_paginated_costs",
                        "description": "Queries the 1,000,000-record multi-region AWS usage dataset with date filtering, dimension filtering, multi-column sorting, and pagination.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "page": {
                                    "type": "integer",
                                    "description": "Page number (1-indexed, default: 1)"
                                },
                                "page_size": {
                                    "type": "integer",
                                    "description": "Page size (1 to 10,000, default: 1,000)"
                                },
                                "sort_by": {
                                    "type": "string",
                                    "description": "Field to sort by: 'date', 'gross_usd', 'region', 'workload_type' (default: 'date')"
                                },
                                "sort_order": {
                                    "type": "string",
                                    "description": "Sort order: 'asc' or 'desc' (default: 'desc')"
                                },
                                "start_date": {
                                    "type": "string",
                                    "description": "Optional ISO start date (YYYY-MM-DD)"
                                },
                                "end_date": {
                                    "type": "string",
                                    "description": "Optional ISO end date (YYYY-MM-DD)"
                                },
                                "region": {
                                    "type": "string",
                                    "description": "Optional AWS region code filter (e.g. 'us-east-1', 'us-east-2')"
                                },
                                "workload_type": {
                                    "type": "string",
                                    "description": "Optional workload archetype filter (e.g. 'serverless_frugal', 'enterprise_microservices', 'ai_analytics_pipeline', 'global_web_edge')"
                                }
                            }
                        }
                    },
                    {
                        "name": "get_settings",
                        "description": "Retrieves the current daily cost baseline ($USD) and budget plan settings.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "update_settings",
                        "description": "Updates the daily cost baseline ($USD) and budget plan configuration.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "daily_baseline_usd": { "type": "number", "description": "Daily cost baseline threshold" },
                                "budget_type": { "type": "string", "description": "Budget type: 'none', 'fixed', or 'monthly_credits'" },
                                "monthly_credit_amount": { "type": "number", "description": "Monthly credit allotment amount" },
                                "monthly_reset_day": { "type": "integer", "description": "Day of month credits renew (1-31)" },
                                "fixed_budget_amount": { "type": "number", "description": "Total fixed budget grant" },
                                "fixed_budget_expiry": { "type": "string", "description": "Expiry date of fixed budget (YYYY-MM-DD)" }
                            }
                        }
                    }
                ]
            }
        })),

        "tools/call" => {
            let params = req.get("params").cloned().unwrap_or(json!({}));
            let tool_name = params.get("name").and_then(|n| n.as_str()).unwrap_or("");
            let args = params.get("arguments").cloned().unwrap_or(json!({}));

            let result = execute_tool(tool_name, &args, store);
            match result {
                Ok(content_text) => Some(json!({
                    "jsonrpc": "2.0",
                    "id": id_val,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": content_text
                            }
                        ]
                    }
                })),
                Err(err_msg) => Some(json!({
                    "jsonrpc": "2.0",
                    "id": id_val,
                    "error": {
                        "code": -32000,
                        "message": err_msg
                    }
                })),
            }
        }

        _ => Some(json!({
            "jsonrpc": "2.0",
            "id": id_val,
            "error": {
                "code": -32601,
                "message": format!("Method not found: {}", method)
            }
        })),
    }
}

fn execute_tool(name: &str, args: &Value, store: &FrugalityStore) -> Result<String, String> {
    match name {
        "get_health" => {
            let src = get_backing_source_info();
            let data = json!({
                "status": "healthy",
                "service": "cloud-frugality",
                "engine": "rust",
                "runtime": format!("rust {}", env!("CARGO_PKG_VERSION")),
                "backing_source": src.source_type,
                "is_emulator": src.is_emulator,
                "partition": src.partition,
                "source_detail": src.detail,
                "timestamp": chrono::Utc::now().to_rfc3339()
            });
            serde_json::to_string_pretty(&data).map_err(|e| e.to_string())
        }

        "get_cost_summary" => {
            let window_days = args.get("window_days").and_then(|v| v.as_u64()).unwrap_or(30) as usize;
            let summary = store.query_cost_summary(window_days);
            serde_json::to_string_pretty(&summary).map_err(|e| e.to_string())
        }

        "query_paginated_costs" => {
            let page = args.get("page").and_then(|v| v.as_u64()).unwrap_or(1) as usize;
            let page_size = args.get("page_size").and_then(|v| v.as_u64()).unwrap_or(1000) as usize;
            let sort_by = args.get("sort_by").and_then(|v| v.as_str()).unwrap_or("date");
            let sort_order = args.get("sort_order").and_then(|v| v.as_str()).unwrap_or("desc");
            let start_date = args.get("start_date").and_then(|v| v.as_str());
            let end_date = args.get("end_date").and_then(|v| v.as_str());
            let region = args.get("region").and_then(|v| v.as_str());
            let workload = args.get("workload_type").and_then(|v| v.as_str());

            let resp = get_paginated_records(
                page,
                page_size,
                sort_by,
                sort_order,
                start_date,
                end_date,
                region,
                workload,
            )?;
            serde_json::to_string_pretty(&resp).map_err(|e| e.to_string())
        }

        "get_settings" => {
            let s = store.get_settings();
            serde_json::to_string_pretty(&s).map_err(|e| e.to_string())
        }

        "update_settings" => {
            let mut current = store.get_settings();
            if let Some(n) = args.get("daily_baseline_usd").and_then(|v| v.as_f64()) {
                current.daily_baseline_usd = (n * 100.0).round() / 100.0;
            }
            if let Some(t) = args.get("budget_type").and_then(|v| v.as_str()) {
                current.budget_type = t.to_string();
            }
            if let Some(m) = args.get("monthly_credit_amount").and_then(|v| v.as_f64()) {
                current.monthly_credit_amount = (m * 100.0).round() / 100.0;
            }
            if let Some(d) = args.get("monthly_reset_day").and_then(|v| v.as_u64()) {
                current.monthly_reset_day = (d as u32).clamp(1, 31);
            }
            if let Some(f) = args.get("fixed_budget_amount").and_then(|v| v.as_f64()) {
                current.fixed_budget_amount = (f * 100.0).round() / 100.0;
            }
            if let Some(e) = args.get("fixed_budget_expiry").and_then(|v| v.as_str()) {
                current.fixed_budget_expiry = e.to_string();
            }

            let saved = store.save_settings(current);
            serde_json::to_string_pretty(&saved).map_err(|e| e.to_string())
        }

        _ => Err(format!("Unknown tool: {}", name)),
    }
}
