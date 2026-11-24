//! Cloud Frugality — Serverless Cost, Runway, and Inventory Microservice in Rust.
//!
//! Rationale & Decisions:
//! - Provides zero-idle-cost AWS spend tracking, promotional credit runway forecasting,
//!   and active tag-governed resource inventory.
//! - Engineered for high readability, simple modular structure, and human-friendly code.
//! - Exposes both Python-compatible interfaces, native Rust HTTP/CLI endpoints, and Model Context Protocol (MCP) tools.

pub mod billing;
pub mod collector;
pub mod mcp;
pub mod metrics;
pub mod paginator;
pub mod resources;
pub mod store;
pub mod web;

pub use billing::{
    calculate_budget_plan, calculate_credit_runway, evaluate_daily_cost_baseline, BudgetPlan, CreditRunway,
    DailyCostBaseline,
};
pub use collector::seed_sample_data_if_empty;
pub use metrics::{LatencySummary, LatencyTracker, ServiceLatency};
pub use paginator::{get_paginated_records, PaginatedRecord, PaginatedResponse};
pub use resources::{parse_arn, ResourceItem};
pub use store::{
    get_service_acronym, AppTagBreakdown, BudgetInfo, CostSummary, DailyCostPayload, DailyRecord, FrugalityStore,
    Settings, SubCostItem, Top5ServiceItem, TopServiceSummary,
};
pub use web::{
    get_engine_switch_urls, get_process_comm, get_service_icon_svg, handle_request,
    handle_request_full, handle_request_with_host, render_dashboard_html, render_settings_html, render_sparkline,
    HttpResponse,
};
