//! AWS Resource ARN parsing and inventory tracking.
//!
//! Rationale & Decisions:
//! - Cloud Frugality inspects resources tagged across the entire account to maintain an active inventory.
//! - ARN parsing decomposes standard AWS format (`arn:partition:service:region:account-id:resource-type/resource-id`)
//!   to isolate the service family and specific resource type without third-party regex overhead.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Deconstructs a standard AWS ARN into its service name and resource type.
///
/// Handles both colon-delimited (`arn:aws:rds:us-east-2:123456789012:cluster:my-cluster`)
/// and slash-delimited (`arn:aws:lambda:us-east-2:123456789012:function:my-function`) formats.
pub fn parse_arn(arn: &str) -> (String, String) {
    let parts: Vec<&str> = arn.splitn(6, ':').collect();
    let service = if parts.len() > 2 { parts[2] } else { "unknown" };
    let tail = if parts.len() > 5 { parts[5] } else { "" };

    // Resource type is either before the first slash or before the next colon
    let rtype = if let Some(idx) = tail.find(|c| c == '/' || c == ':') {
        &tail[..idx]
    } else if !tail.is_empty() {
        tail
    } else {
        service
    };

    (service.to_string(), rtype.to_string())
}

/// Discovered AWS resource metadata with frugality and application tagging.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ResourceItem {
    pub arn: String,
    pub service: String,
    pub resource_type: String,
    pub region: String,
    pub application_name: String,
    pub tags: String,
    pub created_at: Option<String>,
}

impl ResourceItem {
    /// Create a new resource item derived from ARN and tag collection.
    pub fn new(arn: &str, region: &str, tags_map: &HashMap<String, String>, created_at: Option<String>) -> Self {
        let (service, rtype) = parse_arn(arn);
        let app_name = tags_map
            .get("ApplicationName")
            .or_else(|| tags_map.get("Project"))
            .cloned()
            .unwrap_or_else(|| "Frugality".to_string());

        let tags_json = serde_json::to_string(tags_map).unwrap_or_else(|_| "{}".to_string());

        Self {
            arn: arn.to_string(),
            service,
            resource_type: rtype,
            region: region.to_string(),
            application_name: app_name,
            tags: tags_json,
            created_at,
        }
    }
}
