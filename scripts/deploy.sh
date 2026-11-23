#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Deploying Cloud Frugality ==="
cd "${PROJECT_ROOT}/infra"

CDK_BIN="/home/home/github/box_hackathon/agent/infra/cdk/node_modules/.bin/cdk"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

export CDK_DEFAULT_ACCOUNT="596090776030"
export CDK_DEFAULT_REGION="us-east-2"

${CDK_BIN} deploy CloudFrugalityStack \
  --app "${PYTHON_BIN} app.py" \
  --require-approval never

echo "=== Cloud Frugality Deployed Successfully ==="
