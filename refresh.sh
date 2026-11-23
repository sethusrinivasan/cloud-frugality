#!/usr/bin/env bash
# refresh.sh — Refresh AWS cloud state and audit live microservice deployment
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.pulumi/bin:${PATH}"

STACK_NAME="${PULUMI_STACK:-dev}"
export PULUMI_CONFIG_PASSPHRASE="${PULUMI_CONFIG_PASSPHRASE:-cloud-frugality-dev-passphrase}"

echo "====================================================="
echo "  Refreshing Cloud Frugality AWS Infrastructure"
echo "====================================================="

cd "${SCRIPT_DIR}/infra"

if ! pulumi stack select "${STACK_NAME}" 2>/dev/null; then
  echo "⚠️ Pulumi stack '${STACK_NAME}' not found. Run ./deploy.sh first."
  exit 1
fi

echo "🔄 Synchronizing local state with live AWS cloud resources (pulumi refresh)..."
pulumi refresh --yes

echo ""
echo "📊 Current Active Stack Outputs:"
pulumi stack output

# Handle optional --update / -u flag to apply any pending changes
if [[ "${*:-}" =~ "--update"|-u|"--deploy" ]]; then
  echo ""
  echo "🚀 Applying pending infrastructure updates (pulumi up)..."
  cd "${SCRIPT_DIR}"
  ./deploy.sh
fi

echo ""
echo "🔍 Auditing live deployment operational integrity..."
cd "${SCRIPT_DIR}"
./scripts/verify_deployment.sh

echo "====================================================="
echo "  ✅ AWS Deployment Refresh & Verification Complete!"
echo "====================================================="
