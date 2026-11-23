#!/usr/bin/env bash
# verify_tla.sh — Model check TLA+ formal specifications using TLC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

JAR_PATH="${PROJECT_ROOT}/formal_spec/tools/tla2tools.jar"

if [[ ! -f "${JAR_PATH}" ]]; then
  echo "❌ tla2tools.jar not found at ${JAR_PATH}"
  exit 1
fi

if ! command -v java &>/dev/null; then
  echo "❌ java runtime not found in PATH"
  exit 1
fi

echo "====================================================="
echo "  TLA+ Formal Verification via TLC Model Checker"
echo "  Spec: formal_spec/EngineSwitch.tla"
echo "====================================================="

cd "${PROJECT_ROOT}/formal_spec"
java -XX:+UseParallelGC -cp tools/tla2tools.jar tlc2.TLC -config EngineSwitch.cfg EngineSwitch.tla -nowarning

# Cleanup trace exploration and TLC state artifacts
rm -f EngineSwitch_TTrace_*.tla
rm -rf "${PROJECT_ROOT}/states" states

echo "✅ TLA+ Formal Invariants Verified: Zero localhost leakage on remote deployments!"
