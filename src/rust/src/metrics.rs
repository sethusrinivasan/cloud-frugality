//! Performance instrumentation and latency tracking for Cloud Frugality.
//!
//! Rationale & Decisions:
//! - Tracks granular execution time of external dependencies (AWS APIs, S3 reads, DuckDB/memory queries).
//! - Sub-millisecond precision allows detecting database cold-resumes vs warm queries.
//! - Aggregates operations by service with percentage share for transparency in the dashboard.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// An individual instrumented operation with duration in milliseconds.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperationRecord {
    pub service: String,
    pub operation: String,
    pub duration_ms: f64,
}

/// Breakdown of operations and total latency for a specific service.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceLatency {
    pub service: String,
    pub calls: usize,
    pub total_ms: f64,
    pub percent: f64,
    pub sub_operations: Vec<SubOperation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubOperation {
    pub operation: String,
    pub total_ms: f64,
}

/// Comprehensive summary of recorded performance metrics.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LatencySummary {
    pub total_ms: f64,
    pub total_calls: usize,
    pub cold_resume: bool,
    pub tls_version: Option<String>,
    pub tls_cipher: Option<String>,
    pub database_status: String,
    pub services: Vec<ServiceLatency>,
}

/// In-memory tracker for operational latency during request handling.
#[derive(Debug, Clone, Default)]
pub struct LatencyTracker {
    operations: Vec<OperationRecord>,
    pub cold_resume: bool,
    pub tls_version: Option<String>,
    pub tls_cipher: Option<String>,
}

impl LatencyTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record an operation's latency in milliseconds.
    pub fn record(&mut self, service: &str, operation: &str, duration_ms: f64) {
        self.operations.push(OperationRecord {
            service: service.to_string(),
            operation: operation.to_string(),
            duration_ms: (duration_ms * 100.0).round() / 100.0,
        });
    }

    /// Produce an aggregated summary of all recorded operations.
    pub fn summary(&self) -> LatencySummary {
        let total_ms: f64 = self.operations.iter().map(|op| op.duration_ms).sum();
        let total_ms_rounded = (total_ms * 100.0).round() / 100.0;

        // Group operations by service name preserving call counts and sub-operations
        let mut by_service: HashMap<String, (usize, f64, Vec<SubOperation>)> = HashMap::new();
        for op in &self.operations {
            let entry = by_service
                .entry(op.service.clone())
                .or_insert_with(|| (0, 0.0, Vec::new()));
            entry.0 += 1;
            entry.1 += op.duration_ms;
            entry.2.push(SubOperation {
                operation: op.operation.clone(),
                total_ms: op.duration_ms,
            });
        }

        let mut services: Vec<ServiceLatency> = by_service
            .into_iter()
            .map(|(svc, (calls, svc_total, subs))| {
                let svc_total_round = (svc_total * 100.0).round() / 100.0;
                let pct = if total_ms > 0.0 {
                    ((svc_total / total_ms * 100.0) * 10.0).round() / 10.0
                } else {
                    0.0
                };
                ServiceLatency {
                    service: svc,
                    calls,
                    total_ms: svc_total_round,
                    percent: pct,
                    sub_operations: subs,
                }
            })
            .collect();

        // Sort services descending by total execution time
        services.sort_by(|a, b| b.total_ms.partial_cmp(&a.total_ms).unwrap_or(std::cmp::Ordering::Equal));

        let db_status = if self.cold_resume {
            "Cold Resume (0 -> 0.5 ACU)".to_string()
        } else {
            "Warm".to_string()
        };

        LatencySummary {
            total_ms: total_ms_rounded,
            total_calls: self.operations.len(),
            cold_resume: self.cold_resume,
            tls_version: self.tls_version.clone(),
            tls_cipher: self.tls_cipher.clone(),
            database_status: db_status,
            services,
        }
    }
}
