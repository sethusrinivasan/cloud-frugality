use cloud_frugality::collector::seed_sample_data_if_empty;
use cloud_frugality::mcp::handle_mcp_message;
use cloud_frugality::store::FrugalityStore;
use serde_json::json;

#[test]
fn test_mcp_protocol_initialize_and_tools_list() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_mcp_test1_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));

    // 1. initialize
    let init_req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    });
    let init_resp = handle_mcp_message(&init_req, &store).expect("Response");
    assert_eq!(init_resp["id"], 1);
    assert_eq!(init_resp["result"]["serverInfo"]["name"], "cloud-frugality-rust");

    // 2. ping
    let ping_req = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping"
    });
    let ping_resp = handle_mcp_message(&ping_req, &store).expect("Response");
    assert_eq!(ping_resp["id"], 2);

    // 3. tools/list
    let list_req = json!({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list"
    });
    let list_resp = handle_mcp_message(&list_req, &store).expect("Response");
    let tools = list_resp["result"]["tools"].as_array().expect("Tools array");
    let tool_names: Vec<&str> = tools.iter().map(|t| t["name"].as_str().unwrap()).collect();
    assert!(tool_names.contains(&"get_health"));
    assert!(tool_names.contains(&"get_cost_summary"));
    assert!(tool_names.contains(&"query_paginated_costs"));
    assert!(tool_names.contains(&"get_settings"));
    assert!(tool_names.contains(&"update_settings"));

    let _ = std::fs::remove_dir_all(&temp_dir);
}

#[test]
fn test_mcp_tools_execution() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_mcp_test2_{}", std::process::id()));
    let store = FrugalityStore::new(Some(temp_dir.clone()));
    seed_sample_data_if_empty(&store);

    // 1. Execute get_health
    let health_req = json!({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "get_health",
            "arguments": {}
        }
    });
    let health_resp = handle_mcp_message(&health_req, &store).expect("Response");
    let content = health_resp["result"]["content"][0]["text"].as_str().unwrap();
    assert!(content.contains("healthy"));
    assert!(content.contains("rust"));

    // 2. Execute get_cost_summary
    let cost_req = json!({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "get_cost_summary",
            "arguments": {"window_days": 30}
        }
    });
    let cost_resp = handle_mcp_message(&cost_req, &store).expect("Response");
    let cost_content = cost_resp["result"]["content"][0]["text"].as_str().unwrap();
    assert!(cost_content.contains("window_gross_usd"));
    assert!(cost_content.contains("top_services"));

    // 3. Execute query_paginated_costs
    let pag_req = json!({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "query_paginated_costs",
            "arguments": {
                "page": 1,
                "page_size": 5,
                "sort_by": "date",
                "sort_order": "desc"
            }
        }
    });
    let pag_resp = handle_mcp_message(&pag_req, &store).expect("Response");
    let pag_content = pag_resp["result"]["content"][0]["text"].as_str().unwrap();
    let parsed: serde_json::Value = serde_json::from_str(pag_content).unwrap();
    assert_eq!(parsed["total"], 1_000_000);
    assert_eq!(parsed["pageSize"], 5);

    // 4. Execute get_settings & update_settings
    let upd_req = json!({
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {
            "name": "update_settings",
            "arguments": {
                "daily_baseline_usd": 2.50,
                "budget_type": "monthly_credits"
            }
        }
    });
    let upd_resp = handle_mcp_message(&upd_req, &store).expect("Response");
    let upd_content = upd_resp["result"]["content"][0]["text"].as_str().unwrap();
    assert!(upd_content.contains("2.5"));

    let _ = std::fs::remove_dir_all(&temp_dir);
}
