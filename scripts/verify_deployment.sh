#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

echo "=== Running Offline Unit Tests ==="
${PYTHON_BIN} -c "
import tests.test_billing as tb
tb.test_credit_expiry_binds_when_burn_is_low()
tb.test_credit_exhaustion_binds_when_burn_is_high()
tb.test_zero_burn_rate()
tb.test_missing_credits_data()
print('test_billing PASS')

import tests.test_web as tw
tw.test_latency_tracker()
tw.test_render_html_contains_frugality_branding()
tw.test_healthz_endpoint()
print('test_web PASS')

import tests.test_resources as tr
tr.test_parse_arn()
tr.test_sweep_resources()
print('test_resources PASS')
"

echo "=== Running Live AWS & Microservice Integrity Audit ==="
${PYTHON_BIN} "${PROJECT_ROOT}/tests/test_live_audit.py"
