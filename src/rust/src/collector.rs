//! Daily AWS cost and resource collector for Cloud Frugality.
//!
//! Rationale & Decisions:
//! - Aggregates AWS Cost Explorer, Free Tier plan state, and active resource inventory.
//! - Can seed realistic sample serverless data when running offline or in cold bootstrap environments
//!   so that dashboards and reporting functions are immediately testable.

use chrono::{Duration, Utc};
use std::collections::HashMap;

use crate::billing::calculate_credit_runway;
use crate::resources::ResourceItem;
use crate::store::{DailyCostPayload, FrugalityStore};

/// Seeds realistic 30-day AWS serverless spend data if the store is empty.
pub fn seed_sample_data_if_empty(store: &FrugalityStore) {
    let is_aws = std::env::var("AWS_LAMBDA_FUNCTION_NAME").is_ok()
        || std::env::var("AWS_EXECUTION_ENV").is_ok()
        || std::env::var("LAMBDA_TASK_ROOT").is_ok();
    if is_aws {
        return;
    }

    if !store.list_all_daily_costs().is_empty() {
        return;
    }

    let today = Utc::now().date_naive();
    let mut sample_records = Vec::new();

    for i in 1..=30 {
        let d = (today - Duration::days(i as i64)).format("%Y-%m-%d").to_string();

        let ddb_cost = ((0.24 + (i % 5) as f64 * 0.02) * 10000.0).round() / 10000.0;
        let lam_cost = ((0.10 + (i % 3) as f64 * 0.015) * 10000.0).round() / 10000.0;
        let s3_cost = ((0.06 + (i % 4) as f64 * 0.01) * 10000.0).round() / 10000.0;
        let cw_cost = ((0.04 + (i % 2) as f64 * 0.01) * 10000.0).round() / 10000.0;
        let r53_cost = ((0.02 + (i % 3) as f64 * 0.005) * 10000.0).round() / 10000.0;
        let gross = ((ddb_cost + lam_cost + s3_cost + cw_cost + r53_cost) * 10000.0).round() / 10000.0;

        let mut svcs = HashMap::new();
        svcs.insert("Amazon DynamoDB".to_string(), ddb_cost);
        svcs.insert("AWS Lambda".to_string(), lam_cost);
        svcs.insert("Amazon Simple Storage Service".to_string(), s3_cost);
        svcs.insert("AmazonCloudWatch".to_string(), cw_cost);
        svcs.insert("Amazon Route 53".to_string(), r53_cost);

        let mut subcosts = HashMap::new();

        let mut ddb_subs = HashMap::new();
        ddb_subs.insert("On-Demand Read/Write Capacity".to_string(), ((ddb_cost * 0.65) * 10000.0).round() / 10000.0);
        ddb_subs.insert("TimedStorage-ByteHrs".to_string(), ((ddb_cost * 0.25) * 10000.0).round() / 10000.0);
        ddb_subs.insert("PointInTimeRecovery".to_string(), ((ddb_cost * 0.10) * 10000.0).round() / 10000.0);
        subcosts.insert("Amazon DynamoDB".to_string(), ddb_subs);

        let mut lam_subs = HashMap::new();
        lam_subs.insert("ARM Graviton provided.al2023 Invocations".to_string(), ((lam_cost * 0.70) * 10000.0).round() / 10000.0);
        lam_subs.insert("Sub-millisecond Compute".to_string(), ((lam_cost * 0.30) * 10000.0).round() / 10000.0);
        subcosts.insert("AWS Lambda".to_string(), lam_subs);

        let mut s3_subs = HashMap::new();
        s3_subs.insert("S3 Express One Zone Storage".to_string(), ((s3_cost * 0.60) * 10000.0).round() / 10000.0);
        s3_subs.insert("PutObject API".to_string(), ((s3_cost * 0.40) * 10000.0).round() / 10000.0);
        subcosts.insert("Amazon Simple Storage Service".to_string(), s3_subs);

        let mut cw_subs = HashMap::new();
        cw_subs.insert("High-Resolution Vended Logs".to_string(), ((cw_cost * 0.60) * 10000.0).round() / 10000.0);
        cw_subs.insert("Dashboard Metrics".to_string(), ((cw_cost * 0.40) * 10000.0).round() / 10000.0);
        subcosts.insert("AmazonCloudWatch".to_string(), cw_subs);

        let mut r53_subs = HashMap::new();
        r53_subs.insert("HostedZone DNS Queries".to_string(), ((r53_cost * 0.70) * 10000.0).round() / 10000.0);
        r53_subs.insert("HealthChecks".to_string(), ((r53_cost * 0.30) * 10000.0).round() / 10000.0);
        subcosts.insert("Amazon Route 53".to_string(), r53_subs);

        let mut app_tags = HashMap::new();
        app_tags.insert("CloudFrugality-Rust".to_string(), ((gross * 0.60) * 10000.0).round() / 10000.0);
        app_tags.insert("Microservice-Cargo".to_string(), ((gross * 0.25) * 10000.0).round() / 10000.0);
        app_tags.insert("EdgeGateway".to_string(), ((gross * 0.15) * 10000.0).round() / 10000.0);

        let mut regions = HashMap::new();
        regions.insert("us-east-2".to_string(), ((gross * 0.60) * 10000.0).round() / 10000.0);
        regions.insert("us-west-2".to_string(), ((gross * 0.30) * 10000.0).round() / 10000.0);
        regions.insert("global".to_string(), ((gross * 0.10) * 10000.0).round() / 10000.0);

        let expiry_date = (today + Duration::days(150)).format("%Y-%m-%d").to_string();
        let rem_credits = ((60.0 - (gross * (i as f64))) * 100.0).round() / 100.0;
        let runway = calculate_credit_runway(Some(rem_credits), Some(&expiry_date), gross);

        sample_records.push(DailyCostPayload {
            date: d,
            unblended_usd: gross,
            blended_usd: gross,
            net_usd: 0.0,
            credit_usd: -gross,
            gross_usd: gross,
            services: svcs,
            service_subcosts: subcosts,
            app_tags,
            regions,
            plan_type: Some("AWS Free Tier & Promotional Credit".to_string()),
            credits_granted_usd: Some(60.0),
            credits_remaining_usd: Some(rem_credits),
            credits_expiry: Some(expiry_date),
            projection: Some(serde_json::to_value(runway).unwrap()),
        });
    }

    for record in sample_records {
        store.save_daily_cost(record);
    }

    // Seed sample resource inventory
    let mut tags = HashMap::new();
    tags.insert("Frugality".to_string(), "true".to_string());
    tags.insert("Project".to_string(), "Frugality".to_string());
    tags.insert("ApplicationName".to_string(), "Frugality".to_string());

    let past_date = (today - Duration::days(35)).format("%Y-%m-%d").to_string();

    let inv = vec![
        ResourceItem::new(
            "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-collector",
            "us-east-2",
            &tags,
            Some(past_date.clone()),
        ),
        ResourceItem::new(
            "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-web",
            "us-east-2",
            &tags,
            Some(past_date.clone()),
        ),
        ResourceItem::new(
            "arn:aws:s3:::cloud-frugality-data",
            "us-east-2",
            &tags,
            Some(past_date),
        ),
    ];
    store.save_inventory(&inv);
}
