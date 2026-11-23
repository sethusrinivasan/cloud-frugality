#!/usr/bin/env bash
# test.sh — Convenience alias to run the full Cloud Frugality test suite
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run_tests.sh" "$@"
