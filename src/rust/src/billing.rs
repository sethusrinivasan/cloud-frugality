//! Multi-source billing, budget tracking, and promotional credit accounting.
//!
//! Rationale & Decisions:
//! - Pre-credit gross consumption tracks real AWS resource usage rather than masking spend behind promotional credits.
//! - Runway projection dynamically evaluates whether spend burn rate ("exhaustion") or calendar expiry ("expiry")
//!   is the binding bottleneck, preventing unexpected surprises when credits lapse.
//! - Daily baseline thresholds use a 70% heuristic (Green < 70%, Yellow 70%-100%, Red > 100%)
//!   to provide immediate visual feedback on spending health against a target daily budget.

use chrono::{Datelike, NaiveDate, Utc};
use serde::{Deserialize, Serialize};

/// Represents credit runway projections under dual constraints (spend rate vs. calendar cutoff).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CreditRunway {
    /// Identifies which constraint binds first: "exhaustion" (high burn) or "expiry" (calendar date).
    pub binding_limit: Option<String>,
    /// Projected days until remaining credits hit zero at current burn rate.
    pub days_until_exhaustion: Option<i64>,
    /// Calendar days remaining until promotional credits officially expire.
    pub days_until_expiry: Option<i64>,
    /// Dollars of promotional credit wasted if expiry arrives before exhaustion.
    pub credit_waste_if_expiry_binds_usd: Option<f64>,
    /// Average daily gross burn rate in USD used for the projection.
    pub avg_daily_gross_usd: f64,
}

/// Evaluates whether credit exhaustion or calendar expiration will occur first.
pub fn calculate_credit_runway(
    credits_remaining: Option<f64>,
    credits_expiry: Option<&str>,
    avg_daily_gross: f64,
) -> CreditRunway {
    let today = Utc::now().date_naive();

    // 1. Calculate calendar days until credit expiry
    let days_exp = credits_expiry.and_then(|exp_str| {
        let prefix = if exp_str.len() >= 10 { &exp_str[..10] } else { exp_str };
        NaiveDate::parse_from_str(prefix, "%Y-%m-%d").ok().map(|exp_date| {
            (exp_date - today).num_days().max(0)
        })
    });

    // 2. Calculate burn days until exhaustion (requiring positive burn rate > $0.0001)
    let days_exh = match credits_remaining {
        Some(rem) if avg_daily_gross > 0.0001 => Some((rem / avg_daily_gross) as i64),
        _ => None,
    };

    // 3. Determine the binding limit and calculate credit waste if expiry binds first
    let mut binding_limit = None;
    let mut credit_waste = None;

    match (days_exh, days_exp) {
        (Some(exh), Some(exp)) => {
            if exh < exp {
                binding_limit = Some("exhaustion".to_string());
            } else {
                binding_limit = Some("expiry".to_string());
                if let Some(rem) = credits_remaining {
                    let projected_burn = avg_daily_gross * (exp as f64);
                    let waste = (rem - projected_burn).max(0.0);
                    credit_waste = Some((waste * 100.0).round() / 100.0);
                }
            }
        }
        (Some(_), None) => {
            binding_limit = Some("exhaustion".to_string());
        }
        (None, Some(_exp)) => {
            binding_limit = Some("expiry".to_string());
            if let Some(rem) = credits_remaining {
                credit_waste = Some(rem);
            }
        }
        (None, None) => {}
    }

    CreditRunway {
        binding_limit,
        days_until_exhaustion: days_exh,
        days_until_expiry: days_exp,
        credit_waste_if_expiry_binds_usd: credit_waste,
        avg_daily_gross_usd: (avg_daily_gross * 10000.0).round() / 10000.0,
    }
}

/// Baseline cost health status for a single day.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DailyCostBaseline {
    pub gross_usd: f64,
    pub baseline_usd: f64,
    pub yellow_threshold_usd: f64,
    pub color: String,
    pub css_class: String,
    pub description: String,
}

/// Evaluates a day's gross spend against the configured daily baseline.
pub fn evaluate_daily_cost_baseline(gross_usd: f64, baseline_usd: f64) -> DailyCostBaseline {
    let yellow_thresh = ((0.70 * baseline_usd) * 10000.0).round() / 10000.0;

    let (color, css_class, desc) = if gross_usd > baseline_usd {
        ("red", "cost-red", "Exceeds daily baseline")
    } else if gross_usd >= yellow_thresh {
        ("yellow", "cost-yellow", "Within 70% threshold of baseline")
    } else {
        ("green", "cost-green", "Under 70% of daily baseline")
    };

    DailyCostBaseline {
        gross_usd: (gross_usd * 10000.0).round() / 10000.0,
        baseline_usd: (baseline_usd * 10000.0).round() / 10000.0,
        yellow_threshold_usd: yellow_thresh,
        color: color.to_string(),
        css_class: css_class.to_string(),
        description: desc.to_string(),
    }
}

/// Dynamic budget plan projection (Fixed budget or Monthly credits reset).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BudgetPlan {
    pub budget_type: String,
    pub budgeted_usd: f64,
    pub remaining_usd: f64,
    pub days_available: i64,
    pub expiry_date: Option<String>,
    pub reset_day_of_month: Option<u32>,
    pub next_reset_date: Option<String>,
    pub days_until_exhaustion: Option<i64>,
    pub binding_limit: Option<String>,
    pub avg_daily_burn_usd: f64,
}

pub fn calculate_budget_plan(
    budget_type: &str,
    amount: f64,
    expiry_or_reset: &str,
    avg_daily_burn: f64,
    current_burn_to_date: f64,
) -> BudgetPlan {
    let today = Utc::now().date_naive();
    let remaining = ((amount - current_burn_to_date).max(0.0) * 100.0).round() / 100.0;
    let days_exhaustion = if avg_daily_burn > 0.0001 {
        Some((remaining / avg_daily_burn) as i64)
    } else {
        None
    };

    if budget_type == "fixed" {
        let exp_prefix = if expiry_or_reset.len() >= 10 { &expiry_or_reset[..10] } else { expiry_or_reset };
        let days_avail = NaiveDate::parse_from_str(exp_prefix, "%Y-%m-%d")
            .ok()
            .map(|exp_date| (exp_date - today).num_days().max(0))
            .unwrap_or(0);

        let binding = match days_exhaustion {
            Some(exh) => Some(if exh < days_avail { "exhaustion".to_string() } else { "expiry".to_string() }),
            None => Some("expiry".to_string()),
        };

        BudgetPlan {
            budget_type: "fixed".to_string(),
            budgeted_usd: (amount * 100.0).round() / 100.0,
            remaining_usd: remaining,
            days_available: days_avail,
            expiry_date: Some(expiry_or_reset.to_string()),
            reset_day_of_month: None,
            next_reset_date: None,
            days_until_exhaustion: days_exhaustion,
            binding_limit: binding,
            avg_daily_burn_usd: (avg_daily_burn * 10000.0).round() / 10000.0,
        }
    } else {
        let raw_day: u32 = expiry_or_reset.parse().unwrap_or(1);
        let reset_day = raw_day.clamp(1, 31);

        let cur_year = today.year();
        let cur_month = today.month();

        let next_reset = if today.day() < reset_day {
            NaiveDate::from_ymd_opt(cur_year, cur_month, reset_day.min(28))
                .unwrap_or(today)
        } else {
            let (next_year, next_month) = if cur_month == 12 {
                (cur_year + 1, 1)
            } else {
                (cur_year, cur_month + 1)
            };
            NaiveDate::from_ymd_opt(next_year, next_month, reset_day.min(28))
                .unwrap_or(today)
        };

        let days_avail = (next_reset - today).num_days().max(0);

        BudgetPlan {
            budget_type: "monthly".to_string(),
            budgeted_usd: (amount * 100.0).round() / 100.0,
            remaining_usd: remaining,
            days_available: days_avail,
            expiry_date: None,
            reset_day_of_month: Some(reset_day),
            next_reset_date: Some(next_reset.format("%Y-%m-%d").to_string()),
            days_until_exhaustion: days_exhaustion,
            binding_limit: None,
            avg_daily_burn_usd: (avg_daily_burn * 10000.0).round() / 10000.0,
        }
    }
}
