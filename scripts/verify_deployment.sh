#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
PYTEST_BIN="${PROJECT_ROOT}/.venv/bin/pytest"

export PATH="${HOME}/.local/bin:${HOME}/.pulumi/bin:${PATH}"

echo "=== Running Offline Unit & Integration Tests ==="
${PYTEST_BIN} \
  "${PROJECT_ROOT}/tests/test_billing.py" \
  "${PROJECT_ROOT}/tests/test_store.py" \
  "${PROJECT_ROOT}/tests/test_web.py" \
  "${PROJECT_ROOT}/tests/test_resources.py" \
  -v

echo "=== Running Deployment & Microservice Integrity Audit ==="
if [ -n "${COST_WEB_URL:-}" ] || pulumi stack output web_url --cwd "${PROJECT_ROOT}/infra" &>/dev/null; then
  ${PYTHON_BIN} "${PROJECT_ROOT}/tests/test_live_audit.py"
else
  echo "⚡ No remote live URL or Pulumi stack detected. Running AWS Emulator validation instead..."
  ${PYTEST_BIN} "${PROJECT_ROOT}/tests/test_aws_emulator.py" -v
fi

echo "=== All Deployment Verification Audits Passed! ==="
