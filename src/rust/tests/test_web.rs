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

#[test]
fn test_paginated_api_endpoints() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_pag_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));
    seed_sample_data_if_empty(&store);

    // 1. Basic pagination on /ai/resource/paginated
    let resp = handle_request("GET", "/ai/resource/paginated?page=1&pageSize=10", "", "", &store);
    assert_eq!(resp.status_code, 200);
    let val: serde_json::Value = serde_json::from_str(&resp.body).expect("Valid JSON");
    assert_eq!(val["code"], 200);
    assert_eq!(val["message"], "success");
    assert_eq!(val["data"]["total"], 1_000_000);
    assert_eq!(val["data"]["page"], 1);
    assert_eq!(val["data"]["pageSize"], 10);
    assert_eq!(val["data"]["totalPages"], 100_000);
    assert_eq!(val["data"]["hasNext"], true);
    assert_eq!(val["data"]["hasPrev"], false);

    let records = val["data"]["records"].as_array().expect("Records array");
    assert_eq!(records.len(), 10);
    let first = &records[0];
    assert!(first.get("date").is_some());
    assert!(first.get("region").is_some());
    assert!(first.get("workload_type").is_some());
    assert!(first.get("gross_usd").is_some());
    assert!(first.get("color_class").is_some());
    assert!(first.get("status_label").is_some());
    assert!(first.get("top_5_services").is_some());

    // 2. /api/resource/paginated alias
    let resp_alias = handle_request("GET", "/api/resource/paginated?page=2&pageSize=5", "", "", &store);
    assert_eq!(resp_alias.status_code, 200);
    let val_alias: serde_json::Value = serde_json::from_str(&resp_alias.body).expect("Valid JSON");
    assert_eq!(val_alias["data"]["page"], 2);
    assert_eq!(val_alias["data"]["pageSize"], 5);
    assert_eq!(val_alias["data"]["hasPrev"], true);

    // 3. Sorting by date asc
    let resp_asc = handle_request("GET", "/ai/resource/paginated?page=1&pageSize=5&sort_by=date&sort_order=asc", "", "", &store);
    assert_eq!(resp_asc.status_code, 200);
    let val_asc: serde_json::Value = serde_json::from_str(&resp_asc.body).expect("Valid JSON");
    let recs_asc = val_asc["data"]["records"].as_array().unwrap();
    assert_eq!(recs_asc.len(), 5);

    // 4. Date filtering
    let resp_date = handle_request(
        "GET",
        "/ai/resource/paginated?start_date=2026-11-20&end_date=2026-11-22&pageSize=20",
        "",
        "",
        &store,
    );
    assert_eq!(resp_date.status_code, 200);
    let val_date: serde_json::Value = serde_json::from_str(&resp_date.body).expect("Valid JSON");
    for rec in val_date["data"]["records"].as_array().unwrap() {
        let d = rec["date"].as_str().unwrap();
        assert!(d >= "2026-11-20" && d <= "2026-11-22");
    }

    // 5. Invalid sort field returns 400 JSON
    let resp_bad = handle_request("GET", "/ai/resource/paginated?sort_by=invalid_col", "", "", &store);
    assert_eq!(resp_bad.status_code, 400);
    let val_bad: serde_json::Value = serde_json::from_str(&resp_bad.body).unwrap();
    assert_eq!(val_bad["code"], 400);

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_legacy_ai_resource_and_daily_selection() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_leg_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));
    seed_sample_data_if_empty(&store);

    // 1. Default /ai/resource returns daily records (with date field)
    let resp_daily = handle_request("GET", "/ai/resource", "", "", &store);
    assert_eq!(resp_daily.status_code, 200);
    let val_daily: serde_json::Value = serde_json::from_str(&resp_daily.body).unwrap();
    assert_eq!(val_daily["code"], 200);
    assert_eq!(val_daily["data"]["resource"], "daily");
    let recs = val_daily["data"]["records"].as_array().unwrap();
    assert!(!recs.is_empty());
    assert!(recs[0].get("date").is_some(), "Daily records must contain date field");

    // 2. Explicit resource=services returns top_services
    let resp_srv = handle_request("GET", "/ai/resource?resource=services", "", "", &store);
    assert_eq!(resp_srv.status_code, 200);
    let val_srv: serde_json::Value = serde_json::from_str(&resp_srv.body).unwrap();
    assert_eq!(val_srv["data"]["resource"], "services");
    let srv_recs = val_srv["data"]["records"].as_array().unwrap();
    assert!(!srv_recs.is_empty());
    assert!(srv_recs[0].get("service").is_some());
    assert!(srv_recs[0].get("acronym").is_some());

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_unknown_api_routes_return_404_json_not_html() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_404_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));

    // 1. Unknown /ai/ route
    let resp_ai = handle_request("GET", "/ai/resource/unknown_endpoint", "", "", &store);
    assert_eq!(resp_ai.status_code, 404);
    assert!(resp_ai.headers.iter().any(|(k, v)| k.eq_ignore_ascii_case("content-type") && v.contains("application/json")));
    assert!(!resp_ai.body.contains("<!DOCTYPE html>"));
    assert!(resp_ai.body.contains("404"));

    // 2. Unknown /api/ route
    let resp_api = handle_request("GET", "/api/does_not_exist", "", "", &store);
    assert_eq!(resp_api.status_code, 404);
    assert!(resp_api.headers.iter().any(|(k, v)| k.eq_ignore_ascii_case("content-type") && v.contains("application/json")));
    assert!(!resp_api.body.contains("<!DOCTYPE html>"));

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_discovery_endpoints() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_disc_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));

    // 1. Well-known agent configuration
    let resp = handle_request("GET", "/.well-known/agent-configuration.json", "", "", &store);
    assert_eq!(resp.status_code, 200);
    let val: serde_json::Value = serde_json::from_str(&resp.body).unwrap();
    assert_eq!(val["name"], "Cloud Frugality AI Resource Engine");
    assert!(val.get("live_endpoints").is_some());
    assert!(val.get("mcp_server").is_some());

    // 2. /api/discovery
    let resp2 = handle_request("GET", "/api/discovery", "", "", &store);
    assert_eq!(resp2.status_code, 200);

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_gzip_compression_support() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_gzip_test_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));

    let headers = vec![("Accept-Encoding".to_string(), "gzip, deflate".to_string())];
    let resp = cloud_frugality::web::handle_request_full(
        "GET",
        "/ai/resource/paginated?page=1&pageSize=100",
        "",
        "",
        "",
        "",
        &headers,
        &store,
    );
    assert_eq!(resp.status_code, 200);
    assert!(resp.is_base64_encoded);
    assert!(resp.headers.iter().any(|(k, v)| k.eq_ignore_ascii_case("content-encoding") && v == "gzip"));
    assert!(resp.raw_bytes.is_some());

    let _ = std::fs::remove_dir_all(&temp_dir);
}
