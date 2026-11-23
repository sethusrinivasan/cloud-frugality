use cloud_frugality::collector::seed_sample_data_if_empty;
use cloud_frugality::metrics::LatencyTracker;
use cloud_frugality::store::FrugalityStore;
use cloud_frugality::web::{
    get_engine_switch_urls, handle_request, handle_request_with_host, render_sparkline,
};

#[test]
fn test_latency_tracker() {
    let mut tracker = LatencyTracker::new();
    tracker.record("Frugality Storage Engine", "Read S3 Object", 5.25);
    tracker.record("Frugality Storage Engine", "Aggregate Daily Spend", 2.10);
    tracker.record("AWS Resource Groups", "tag:GetResources", 15.0);

    let summary = tracker.summary();
    assert_eq!(summary.total_calls, 3);
    assert!(summary.total_ms >= 22.0);
    assert_eq!(summary.services.len(), 2);
    assert_eq!(summary.database_status, "Warm");
}

#[test]
fn test_sparkline_svg_generation() {
    let vals = vec![0.5, 1.2, 0.8, 1.5, 0.9];
    let svg = render_sparkline(&vals, 120, 26, "#3fb950");
    assert!(svg.contains("<svg"));
    assert!(svg.contains("<polyline"));
    assert!(svg.contains("<circle"));
}

#[test]
fn test_web_dashboard_and_healthz() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_web_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));
    seed_sample_data_if_empty(&store);

    // 1. Healthz endpoint
    let health_resp = handle_request("GET", "/healthz", "", "", &store);
    assert_eq!(health_resp.status_code, 200);
    assert!(health_resp.body.contains("healthy"));
    assert!(health_resp.body.contains("Frugality"));
    assert!(health_resp.body.contains("rust"));

    // 2. Dashboard root
    let dash_resp = handle_request("GET", "/", "", "", &store);
    assert_eq!(dash_resp.status_code, 200);
    assert!(dash_resp.body.contains("Cloud Frugality"));
    assert!(dash_resp.body.contains("Rust Engine"));
    assert!(dash_resp.body.contains("Breakdown by AWS Region"));
    assert!(dash_resp.body.contains("Top Services Spend"));
    assert!(dash_resp.body.contains("Daily Cost History"));
    assert!(dash_resp.body.contains("engine-switcher"));

    // 3. API costs
    let api_resp = handle_request("GET", "/api/costs", "", "", &store);
    assert_eq!(api_resp.status_code, 200);
    assert!(api_resp.body.contains("window_gross_usd"));
    assert!(api_resp.body.contains("region_breakdown"));
    assert!(api_resp.body.contains("latency_breakdown"));

    // 4. Remote request resolution: no localhost leakage
    let remote_host = "2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws";
    let remote_resp = handle_request_with_host("GET", "/", "", "", remote_host, &store);
    assert_eq!(remote_resp.status_code, 200);
    assert!(!remote_resp.body.contains("http://localhost"));
    assert!(!remote_resp.body.contains("127.0.0.1"));

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_engine_switch_url_resolution() {
    // 1. Local resolution
    let (py_local, rust_local) = get_engine_switch_urls("localhost:8091");
    assert_eq!(py_local, "http://localhost:8090/");
    assert_eq!(rust_local, "http://localhost:8091/");

    // 2. Remote resolution without env vars
    let (py_rem, rust_rem) = get_engine_switch_urls("2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws");
    assert_eq!(py_rem, "/?engine=python");
    assert_eq!(rust_rem, "/?engine=rust");
    assert!(!py_rem.contains("localhost"));
    assert!(!rust_rem.contains("localhost"));
}
