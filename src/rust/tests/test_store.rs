use cloud_frugality::collector::seed_sample_data_if_empty;
use cloud_frugality::store::{get_service_acronym, FrugalityStore};
use std::fs;

#[test]
fn test_service_acronym_formation() {
    assert_eq!(get_service_acronym("Amazon Relational Database Service"), "RDS");
    assert_eq!(get_service_acronym("AmazonCloudWatch"), "CW");
    assert_eq!(get_service_acronym("Amazon Simple Storage Service"), "S3");
    assert_eq!(get_service_acronym("AWS Lambda"), "LAM");
    assert_eq!(get_service_acronym("Amazon Elastic Compute Cloud - Compute"), "EC2");
    assert_eq!(get_service_acronym("Amazon DynamoDB"), "DDB");
    assert_eq!(get_service_acronym("AWS Key Management Service"), "KMS");
}

#[test]
fn test_frugality_store_lifecycle_and_analytics() {
    let temp_dir = std::env::temp_dir().join(format!("frugality_test_{}", std::process::id()));
    let _ = fs::create_dir_all(&temp_dir);

    let store = FrugalityStore::new(Some(temp_dir.clone()));
    seed_sample_data_if_empty(&store);

    let summary = store.query_cost_summary(30);
    assert_eq!(summary.days_recorded, 30);
    assert!(summary.window_gross_usd > 0.0);
    assert_eq!(summary.window_net_usd, 0.0);
    assert_eq!(summary.resource_count, 3);
    assert!(!summary.top_services.is_empty());
    assert!(!summary.daily.is_empty());

    // Settings update
    let mut current_settings = store.get_settings();
    current_settings.daily_baseline_usd = 2.50;
    current_settings.monthly_credit_amount = 75.00;
    store.save_settings(current_settings);

    let updated = store.get_settings();
    assert_eq!(updated.daily_baseline_usd, 2.50);
    assert_eq!(updated.monthly_credit_amount, 75.00);

    let _ = fs::remove_dir_all(&temp_dir);
}
