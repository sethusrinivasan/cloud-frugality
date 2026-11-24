//! Cloud Frugality CLI and Standalone Server in Rust.
//!
//! Rationale & Decisions:
//! - Provides a standalone zero-dependency HTTP server using standard library `TcpListener`
//!   to avoid heavyweight async frameworks when running locally or on modest edge instances.
//! - Includes a `request` subcommand outputting structured JSON (`statusCode`, `headers`, `body`)
//!   which allows Python web servers or Lambda harnesses to delegate directly to this binary
//!   when the dashboard engine toggle is switched to Rust.

use std::collections::HashMap;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process;

use cloud_frugality::collector::seed_sample_data_if_empty;
use cloud_frugality::store::FrugalityStore;
use cloud_frugality::web::handle_request_full;

fn main() {
    let store = FrugalityStore::new(None);
    seed_sample_data_if_empty(&store);

    // If executed inside an AWS Lambda custom runtime environment (provided.al2023)
    if let Ok(runtime_api) = env::var("AWS_LAMBDA_RUNTIME_API") {
        run_lambda_runtime(&runtime_api, &store);
        return;
    }

    let args: Vec<String> = env::args().collect();
    let command = args.get(1).map(|s| s.as_str()).unwrap_or("serve");

    match command {
        "mcp" => {
            cloud_frugality::mcp::run_mcp_stdio_server(&store);
        }
        "serve" => {
            let port = args.get(2).and_then(|p| p.parse::<u16>().ok()).unwrap_or(8090);
            run_server(port, store);
        }
        "request" => {
            // Invoked by Python or external callers:
            // cloud-frugality request --method GET --path / [--query "..."] [--body "..."] [--content-type "..."]
            let mut method = "GET".to_string();
            let mut path = "/".to_string();
            let mut query = String::new();
            let mut body = String::new();
            let mut content_type = String::new();
            let mut host = String::new();

            let mut i = 2;
            while i < args.len() {
                match args[i].as_str() {
                    "--method" if i + 1 < args.len() => {
                        method = args[i + 1].clone();
                        i += 2;
                    }
                    "--path" if i + 1 < args.len() => {
                        path = args[i + 1].clone();
                        i += 2;
                    }
                    "--query" if i + 1 < args.len() => {
                        query = args[i + 1].clone();
                        i += 2;
                    }
                    "--body" if i + 1 < args.len() => {
                        body = args[i + 1].clone();
                        i += 2;
                    }
                    "--content-type" if i + 1 < args.len() => {
                        content_type = args[i + 1].clone();
                        i += 2;
                    }
                    "--host" if i + 1 < args.len() => {
                        host = args[i + 1].clone();
                        i += 2;
                    }
                    _ => {
                        i += 1;
                    }
                }
            }

            let resp = handle_request_full(&method, &path, &query, &body, &content_type, &host, &[], &store);
            let headers_map: HashMap<String, String> = resp.headers.into_iter().collect();
            let out_json = serde_json::json!({
                "statusCode": resp.status_code,
                "headers": headers_map,
                "body": resp.body,
                "isBase64Encoded": resp.is_base64_encoded,
            });
            println!("{}", serde_json::to_string(&out_json).unwrap());
        }
        "summary" => {
            let summary = store.query_cost_summary(30);
            println!("============================================================");
            println!("  Cloud Frugality Summary (Rust Native Engine)");
            println!("============================================================");
            println!("Window Days Recorded: {}", summary.days_recorded);
            println!("Gross Pre-Credit Spend: ${:.2}", summary.window_gross_usd);
            println!("Net Billed Cash:        ${:.2}", summary.window_net_usd);
            println!("Credits/Budget Remaining: ${:.2}", summary.budget.remaining_usd);
            println!("Days Available in Cycle:  {} days", summary.budget.days_available);
            println!("Tracked AWS Resources:    {}", summary.resource_count);
            println!("Top Services Count:       {}", summary.top_services.len());
        }
        "verify" => {
            let summary = store.query_cost_summary(30);
            assert!(summary.days_recorded > 0, "No daily costs recorded");
            assert!(summary.window_gross_usd > 0.0, "Window gross spend must be positive");
            assert!(summary.resource_count > 0, "Resource count must be positive");
            println!("Verification succeeded: 100% healthy Rust microservice state.");
        }
        "help" | "--help" | "-h" => {
            println!("Usage: cloud-frugality [COMMAND] [OPTIONS]");
            println!();
            println!("Commands:");
            println!("  serve [PORT]       Start local HTTP server (default: 8090)");
            println!("  request [OPTS]     Execute a single HTTP request and output JSON response");
            println!("  summary            Print 30-day spending and runway summary");
            println!("  verify             Run quick integrity sanity check");
        }
        unknown => {
            eprintln!("Unknown command: {}", unknown);
            eprintln!("Run 'cloud-frugality help' for usage instructions.");
            process::exit(1);
        }
    }
}

/// Runs a simple multi-request local HTTP server using standard library TCP sockets.
fn run_server(port: u16, store: FrugalityStore) {
    let addr = format!("0.0.0.0:{}", port);
    let listener = TcpListener::bind(&addr).unwrap_or_else(|e| {
        eprintln!("Failed to bind to {}: {}", addr, e);
        process::exit(1);
    });

    println!("============================================================");
    println!("  Cloud Frugality Rust Server running on http://localhost:{}", port);
    println!("  Health Check: http://localhost:{}/healthz", port);
    println!("  Dashboard:    http://localhost:{}/", port);
    println!("  Settings:     http://localhost:{}/settings", port);
    println!("============================================================");

    for stream in listener.incoming() {
        if let Ok(stream) = stream {
            handle_client(stream, &store);
        }
    }
}

fn handle_client(mut stream: TcpStream, store: &FrugalityStore) {
    let mut buffer = [0u8; 8192];
    let bytes_read = match stream.read(&mut buffer) {
        Ok(n) if n > 0 => n,
        _ => return,
    };

    let request_str = String::from_utf8_lossy(&buffer[..bytes_read]);
    let mut lines = request_str.lines();
    let first_line = lines.next().unwrap_or("");
    let mut parts = first_line.split_whitespace();
    let method = parts.next().unwrap_or("GET");
    let full_path = parts.next().unwrap_or("/");

    let mut path_parts = full_path.splitn(2, '?');
    let path = path_parts.next().unwrap_or("/");
    let query_str = path_parts.next().unwrap_or("");

    // Extract Headers, Content-Type, Host, and Body
    let mut content_type = String::new();
    let mut host = String::new();
    let mut headers = Vec::new();

    for line in request_str.lines().skip(1) {
        if line.trim().is_empty() {
            break;
        }
        if let Some(idx) = line.find(':') {
            let k = line[..idx].trim().to_string();
            let v = line[idx + 1..].trim().to_string();
            let k_low = k.to_lowercase();
            if k_low == "content-type" {
                content_type = v.clone();
            } else if k_low == "host" {
                host = v.clone();
            }
            headers.push((k, v));
        }
    }

    let body = if let Some(idx) = request_str.find("\r\n\r\n") {
        &request_str[idx + 4..]
    } else {
        ""
    };

    let response = handle_request_full(method, path, query_str, body, &content_type, &host, &headers, store);

    let status_line = match response.status_code {
        200 => "HTTP/1.1 200 OK",
        204 => "HTTP/1.1 204 No Content",
        400 => "HTTP/1.1 400 Bad Request",
        404 => "HTTP/1.1 404 Not Found",
        500 => "HTTP/1.1 500 Internal Server Error",
        _ => "HTTP/1.1 200 OK",
    };

    let (body_bytes, body_len) = if let Some(ref raw) = response.raw_bytes {
        (raw.as_slice(), raw.len())
    } else {
        (response.body.as_bytes(), response.body.len())
    };

    let mut header_lines = String::new();
    for (k, v) in &response.headers {
        header_lines.push_str(&format!("{}: {}\r\n", k, v));
    }
    header_lines.push_str(&format!("Content-Length: {}\r\n", body_len));
    header_lines.push_str("Connection: close\r\n");

    let header_reply = format!("{}\r\n{}\r\n", status_line, header_lines);
    let _ = stream.write_all(header_reply.as_bytes());
    let _ = stream.write_all(body_bytes);
    let _ = stream.flush();
}

/// Custom runtime event loop for AWS Lambda (AL2023).
fn run_lambda_runtime(api: &str, store: &FrugalityStore) {
    eprintln!("Lambda custom runtime active. Polling: {}", api);
    loop {
        let (request_id, event_str) = match get_next_invocation(api) {
            Ok(pair) => pair,
            Err(e) => {
                eprintln!("Error polling Lambda runtime API: {}", e);
                std::thread::sleep(std::time::Duration::from_millis(50));
                continue;
            }
        };

        let (method, path, query, body, content_type, host, headers) = parse_lambda_event(&event_str);
        let resp = handle_request_full(&method, &path, &query, &body, &content_type, &host, &headers, store);

        let headers_map: HashMap<String, String> = resp.headers.into_iter().collect();
        let lambda_res = serde_json::json!({
            "statusCode": resp.status_code,
            "headers": headers_map,
            "body": resp.body,
            "isBase64Encoded": resp.is_base64_encoded,
        });

        let res_body = serde_json::to_string(&lambda_res).unwrap_or_default();
        if let Err(e) = post_invocation_response(api, &request_id, &res_body) {
            eprintln!("Error posting invocation response {}: {}", request_id, e);
        }
    }
}

fn get_next_invocation(api: &str) -> Result<(String, String), String> {
    let mut stream = TcpStream::connect(api).map_err(|e| format!("Connect error: {}", e))?;
    let req = format!(
        "GET /2018-06-01/runtime/invocation/next HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        api
    );
    stream.write_all(req.as_bytes()).map_err(|e| format!("Write error: {}", e))?;

    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).map_err(|e| format!("Read error: {}", e))?;

    let response_str = String::from_utf8_lossy(&buf);
    let sep = "\r\n\r\n";
    let (headers_str, body_str) = match response_str.find(sep) {
        Some(idx) => (&response_str[..idx], &response_str[idx + sep.len()..]),
        None => return Err("Invalid HTTP response: header separator not found".to_string()),
    };

    let mut request_id = String::new();
    for line in headers_str.lines() {
        let lower = line.to_lowercase();
        if lower.starts_with("lambda-runtime-aws-request-id:") {
            if let Some(val) = line.split(':').nth(1) {
                request_id = val.trim().to_string();
            }
        }
    }

    if request_id.is_empty() {
        return Err("Missing lambda-runtime-aws-request-id header".to_string());
    }

    Ok((request_id, body_str.to_string()))
}

fn post_invocation_response(api: &str, request_id: &str, body: &str) -> Result<(), String> {
    let mut stream = TcpStream::connect(api).map_err(|e| format!("Connect error: {}", e))?;
    let req = format!(
        "POST /2018-06-01/runtime/invocation/{}/response HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        request_id,
        api,
        body.len(),
        body
    );
    stream.write_all(req.as_bytes()).map_err(|e| format!("Write error: {}", e))?;
    let mut resp = Vec::new();
    let _ = stream.read_to_end(&mut resp);
    Ok(())
}

fn parse_lambda_event(event_str: &str) -> (String, String, String, String, String, String, Vec<(String, String)>) {
    if let Ok(val) = serde_json::from_str::<serde_json::Value>(event_str) {
        if val.get("source").and_then(|s| s.as_str()) == Some("scheduled") {
            return (
                "GET".to_string(),
                "/healthz".to_string(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                Vec::new(),
            );
        }

        let method = val
            .pointer("/requestContext/http/method")
            .and_then(|v| v.as_str())
            .or_else(|| val.get("httpMethod").and_then(|v| v.as_str()))
            .unwrap_or("GET")
            .to_string();

        let raw_path = val
            .get("rawPath")
            .and_then(|v| v.as_str())
            .or_else(|| val.pointer("/requestContext/http/path").and_then(|v| v.as_str()))
            .or_else(|| val.get("path").and_then(|v| v.as_str()))
            .unwrap_or("/")
            .to_string();

        let mut path_parts = raw_path.splitn(2, '?');
        let path = path_parts.next().unwrap_or("/").to_string();
        let path_query = path_parts.next().unwrap_or("").to_string();

        let raw_query_string = val
            .get("rawQueryString")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                if let Some(params) = val.get("queryStringParameters").and_then(|p| p.as_object()) {
                    params
                        .iter()
                        .map(|(k, v)| format!("{}={}", k, v.as_str().unwrap_or("")))
                        .collect::<Vec<_>>()
                        .join("&")
                } else {
                    path_query
                }
            });

        let mut headers = Vec::new();
        let mut ct = String::new();
        let mut host = String::new();

        if let Some(hdrs) = val.get("headers").and_then(|h| h.as_object()) {
            for (k, v) in hdrs {
                if let Some(s) = v.as_str() {
                    let k_low = k.to_lowercase();
                    if k_low == "content-type" {
                        ct = s.to_string();
                    } else if k_low == "host" {
                        host = s.to_string();
                    }
                    headers.push((k.clone(), s.to_string()));
                }
            }
        }

        let body = val
            .get("body")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        (method, path, raw_query_string, body, ct, host, headers)
    } else {
        (
            "GET".to_string(),
            "/".to_string(),
            String::new(),
            String::new(),
            String::new(),
            String::new(),
            Vec::new(),
        )
    }
}
