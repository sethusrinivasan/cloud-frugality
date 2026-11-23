use cloud_frugality::resources::{parse_arn, ResourceItem};
use std::collections::HashMap;

#[test]
fn test_parse_arn() {
    let (svc1, rtype1) = parse_arn("arn:aws:lambda:us-east-2:123456789012:function:my-function");
    assert_eq!(svc1, "lambda");
    assert_eq!(rtype1, "function");

    let (svc2, rtype2) = parse_arn("arn:aws:rds:us-east-2:123456789012:cluster:my-cluster");
    assert_eq!(svc2, "rds");
    assert_eq!(rtype2, "cluster");

    let (svc3, rtype3) = parse_arn("arn:aws:s3:::my-bucket");
    assert_eq!(svc3, "s3");
    assert_eq!(rtype3, "my-bucket");
}

#[test]
fn test_resource_item_creation() {
    let mut tags = HashMap::new();
    tags.insert("ApplicationName".to_string(), "PaymentGateway".to_string());
    tags.insert("Frugality".to_string(), "true".to_string());

    let item = ResourceItem::new(
        "arn:aws:lambda:us-east-2:123456789012:function:payment-processor",
        "us-east-2",
        &tags,
        Some("2026-11-20T10:00:00Z".to_string()),
    );

    assert_eq!(item.service, "lambda");
    assert_eq!(item.resource_type, "function");
    assert_eq!(item.application_name, "PaymentGateway");
    assert!(item.tags.contains("Frugality"));
}
