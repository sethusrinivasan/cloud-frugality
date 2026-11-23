#!/usr/bin/env bash
# deploy.sh — Deploy or update Cloud Frugality infrastructure to AWS using Pulumi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/scripts/deploy.sh" "$@"
