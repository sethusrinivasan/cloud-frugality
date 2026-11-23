#!/usr/bin/env bash
# Deploy Cloud Frugality infrastructure to AWS using Pulumi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PATH="${HOME}/.pulumi/bin:${PATH}"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

if ! command -v pulumi &>/dev/null; then
  echo "❌ pulumi CLI not found in PATH or ~/.pulumi/bin."
  echo "Run: curl -fsSL https://get.pulumi.com | sh"
  exit 1
fi

echo "====================================================="
echo "  Deploying Cloud Frugality via Pulumi"
echo "  Pulumi Version: $(pulumi version)"
echo "====================================================="

# 1. Pre-compile Rust binary for AL2023 Lambda deployment
if command -v cargo &>/dev/null; then
  echo "🦀 Pre-compiling Rust microservice binary for AL2023 deployment..."
  (cd "${PROJECT_ROOT}/src/rust" && cargo build --release --quiet)
  mkdir -p "${PROJECT_ROOT}/build/lambda_rust"
  cp "${PROJECT_ROOT}/src/rust/target/release/cloud-frugality" "${PROJECT_ROOT}/build/lambda_rust/bootstrap"
  chmod +x "${PROJECT_ROOT}/build/lambda_rust/bootstrap"
  cp "${PROJECT_ROOT}/build/lambda_rust/bootstrap" "${PROJECT_ROOT}/src/rust/bootstrap"
fi

# 2. Package Python Lambda deployment directory
echo "🐍 Preparing Python Lambda deployment package..."
mkdir -p "${PROJECT_ROOT}/build/lambda_python"
cp "${PROJECT_ROOT}/src/python/"*.py "${PROJECT_ROOT}/build/lambda_python/"
if [[ -f "${PROJECT_ROOT}/src/schema.sql" ]]; then
  cp "${PROJECT_ROOT}/src/schema.sql" "${PROJECT_ROOT}/build/lambda_python/"
fi

if [[ ! -d "${PROJECT_ROOT}/build/lambda_python/duckdb" ]]; then
  echo "📦 Vendoring duckdb for AWS Lambda Python runtime..."
  PYTHON_LAMBDA_BIN="/home/home/.local/bin/python3.12"
  if ! command -v "${PYTHON_LAMBDA_BIN}" &>/dev/null; then
    PYTHON_LAMBDA_BIN="python3"
  fi
  "${PYTHON_LAMBDA_BIN}" -m pip install duckdb -t "${PROJECT_ROOT}/build/lambda_python" --quiet
fi

cd "${PROJECT_ROOT}/infra"

STACK_NAME="${PULUMI_STACK:-dev}"
export PULUMI_CONFIG_PASSPHRASE="${PULUMI_CONFIG_PASSPHRASE:-cloud-frugality-dev-passphrase}"

# Select or initialize the stack
if ! pulumi stack select "${STACK_NAME}" 2>/dev/null; then
  echo "⚡ Initializing Pulumi stack '${STACK_NAME}'..."
  pulumi stack init "${STACK_NAME}"
fi

# Ensure AWS region is configured
pulumi config set aws:region "${AWS_REGION:-us-east-2}"

# Handle optional --refresh flag
if [[ "${*:-}" =~ "--refresh"|-r ]]; then
  echo "🔄 Refreshing existing AWS cloud resource state..."
  pulumi refresh --yes
fi

# Deploy infrastructure
echo "🚀 Executing 'pulumi up --yes'..."
pulumi up --yes "$@"

echo "====================================================="
echo "  Deployment Complete! Active Stack Outputs:"
echo "====================================================="
pulumi stack output

echo "✅ Cloud Frugality deployed successfully."
