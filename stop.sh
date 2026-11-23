#!/usr/bin/env bash
# stop.sh — Gracefully stop Cloud Frugality local development servers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.server.pid"

echo "=================================================================="
echo "  Stopping Cloud Frugality Local Servers"
echo "=================================================================="

STOPPED=false

# 1. Kill by PID file if present
if [ -f "${PID_FILE}" ]; then
  SERVER_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -n "${SERVER_PID}" ]; then
    if kill -0 "${SERVER_PID}" 2>/dev/null; then
      echo "🛑 Stopping server process (PID: ${SERVER_PID})..."
      pkill -P "${SERVER_PID}" 2>/dev/null || true
      kill "${SERVER_PID}" 2>/dev/null || true
      sleep 0.5
      if kill -0 "${SERVER_PID}" 2>/dev/null; then
        kill -9 "${SERVER_PID}" 2>/dev/null || true
      fi
      STOPPED=true
    fi
  fi
  rm -f "${PID_FILE}"
fi

# 2. Free ports 8090 and 8091
for port in 8090 8091; do
  PIDS="$(lsof -ti :${port} 2>/dev/null || true)"
  if [ -n "${PIDS}" ]; then
    echo "🛑 Freeing port ${port} (PID: ${PIDS})..."
    kill ${PIDS} 2>/dev/null || true
    sleep 0.3
    lsof -ti :${port} 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    STOPPED=true
  fi
done

# 3. Clean up any lingering serve_local or target/debug/cloud-frugality serve
pkill -f "scripts/serve_local.py" 2>/dev/null || true
pkill -f "cloud-frugality serve" 2>/dev/null || true

if [ "${STOPPED}" = true ]; then
  echo "✅ Cloud Frugality local servers have been cleanly stopped."
else
  echo "ℹ️  No running Cloud Frugality server processes found."
fi
echo "=================================================================="
