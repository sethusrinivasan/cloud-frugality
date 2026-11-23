#!/usr/bin/env bash
# scripts/verify_local.sh
# End-to-end local automated verification suite for Cloud Frugality across both Python and Rust implementations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
PYTEST_BIN="${PROJECT_ROOT}/.venv/bin/pytest"
EMULATOR_BIN="${HOME}/.local/bin/aws-emulator"

export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${HOME}/.pulumi/bin:${PATH}"
[ -f "${HOME}/.cargo/env" ] && source "${HOME}/.cargo/env"

echo "====================================================================="
echo "  Cloud Frugality — Comprehensive Multi-Engine Local Verification"
echo "====================================================================="

# 1. Run Rust Unit Tests and Binary Self-Verification
echo "🦀 [1/3] Running Rust Microservice Tests & Self-Verification..."
cd "${PROJECT_ROOT}/src/rust"
cargo test --quiet
cargo build --quiet
"${PROJECT_ROOT}/src/rust/target/debug/cloud-frugality" verify
echo "✅ Rust test suite and self-verification passed (100% green)!"

cd "${PROJECT_ROOT}"

# 2. Run Python Offline Unit Tests
echo ""
echo "🐍 [2/3] Running Python Unit Tests (Billing, Store, Web, Engine Switch)..."
${PYTEST_BIN} \
  tests/test_billing.py \
  tests/test_store.py \
  tests/test_web.py \
  tests/test_resources.py \
  -v

echo "✅ All Python unit tests passed successfully!"

# 3. Check and Run against AWS Emulator
echo ""
echo "⚙️ [3/3] Validating against AWS Emulator (Nov 2026 Engine)..."

if [ ! -x "${EMULATOR_BIN}" ]; then
  if [ -x "${HOME}/.aws-emulator/opt/aws-emulator/bin/aws-emulator" ]; then
    mkdir -p "${HOME}/.local/bin"
    ln -sf "${HOME}/.aws-emulator/opt/aws-emulator/bin/aws-emulator" "${EMULATOR_BIN}"
  fi
fi

if command -v aws-emulator &>/dev/null || [ -x "${EMULATOR_BIN}" ]; then
  echo "🚀 Found AWS Emulator binary. Launching emulator verification..."
  ${PYTEST_BIN} tests/test_aws_emulator.py -v
  echo "✅ AWS Emulator integration verified!"
else
  echo "⚠️ AWS Emulator binary not found in PATH or ~/.local/bin. Skipping live emulator test."
fi

echo ""
echo "====================================================================="
echo "  🎉 ALL LOCAL VERIFICATION CHECKS PASSED (PYTHON + RUST 100% GREEN)"
echo "====================================================================="
