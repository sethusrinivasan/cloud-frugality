#!/usr/bin/env bash
# run_tests.sh — Execute complete multi-engine test suite across Rust, Python, and AWS Emulator
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/scripts/verify_local.sh" "$@"
