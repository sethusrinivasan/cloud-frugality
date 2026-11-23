use chrono::{Duration, Utc};
use cloud_frugality::billing::{
    calculate_budget_plan, calculate_credit_runway, evaluate_daily_cost_baseline,
};

#[test]
fn test_credit_expiry_binds_when_burn_is_low() {
    let today = Utc::now().date_naive();
    let expiry = (today + Duration::days(60)).format("%Y-%m-%d").to_string();

    let runway = calculate_credit_runway(Some(100.0), Some(&expiry), 0.50);
    assert_eq!(runway.binding_limit.as_deref(), Some("expiry"));
    assert_eq!(runway.days_until_exhaustion, Some(200));
    assert_eq!(runway.days_until_expiry, Some(60));
    // Waste: 100 - (0.50 * 60) = 70.0
    assert_eq!(runway.credit_waste_if_expiry_binds_usd, Some(70.0));
}

#[test]
fn test_credit_exhaustion_binds_when_burn_is_high() {
    let today = Utc::now().date_naive();
    let expiry = (today + Duration::days(60)).format("%Y-%m-%d").to_string();

    let runway = calculate_credit_runway(Some(100.0), Some(&expiry), 5.0);
    assert_eq!(runway.binding_limit.as_deref(), Some("exhaustion"));
    assert_eq!(runway.days_until_exhaustion, Some(20));
    assert_eq!(runway.days_until_expiry, Some(60));
    assert_eq!(runway.credit_waste_if_expiry_binds_usd, None);
}

#[test]
fn test_zero_burn_rate() {
    let today = Utc::now().date_naive();
    let expiry = (today + Duration::days(30)).format("%Y-%m-%d").to_string();

    let runway = calculate_credit_runway(Some(50.0), Some(&expiry), 0.0);
    assert_eq!(runway.binding_limit.as_deref(), Some("expiry"));
    assert_eq!(runway.days_until_exhaustion, None);
    assert_eq!(runway.credit_waste_if_expiry_binds_usd, Some(50.0));
}

#[test]
fn test_daily_cost_baseline_thresholds() {
    let baseline = 1.00;

    // Red: > baseline
    let red_eval = evaluate_daily_cost_baseline(1.25, baseline);
    assert_eq!(red_eval.color, "red");
    assert_eq!(red_eval.css_class, "cost-red");

    // Yellow: >= 0.70 of baseline (0.70 to 1.00)
    let yellow_eval = evaluate_daily_cost_baseline(0.85, baseline);
    assert_eq!(yellow_eval.color, "yellow");
    assert_eq!(yellow_eval.css_class, "cost-yellow");

    // Green: < 0.70 of baseline (< 0.70)
    let green_eval = evaluate_daily_cost_baseline(0.45, baseline);
    assert_eq!(green_eval.color, "green");
    assert_eq!(green_eval.css_class, "cost-green");
}

#[test]
fn test_budget_plan_fixed_option() {
    let today = Utc::now().date_naive();
    let expiry = (today + Duration::days(90)).format("%Y-%m-%d").to_string();

    let plan = calculate_budget_plan("fixed", 500.0, &expiry, 2.50, 50.0);
    assert_eq!(plan.budget_type, "fixed");
    assert_eq!(plan.budgeted_usd, 500.0);
    assert_eq!(plan.remaining_usd, 450.0);
    assert_eq!(plan.days_available, 90);
    assert_eq!(plan.days_until_exhaustion, Some(180));
    assert_eq!(plan.binding_limit.as_deref(), Some("expiry"));
}

#[test]
fn test_budget_plan_monthly_credits_option() {
    let plan = calculate_budget_plan("monthly", 60.0, "1", 1.50, 15.0);
    assert_eq!(plan.budget_type, "monthly");
    assert_eq!(plan.budgeted_usd, 60.0);
    assert_eq!(plan.remaining_usd, 45.0);
    assert_eq!(plan.reset_day_of_month, Some(1));
    assert!(plan.days_available > 0);
    assert_eq!(plan.days_until_exhaustion, Some(30));
}
