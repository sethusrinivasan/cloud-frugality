#!/usr/bin/env bash
# start.sh — Launch Cloud Frugality local development servers (Python :8090, Rust :8091)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PID_FILE="${SCRIPT_DIR}/.server.pid"
LOG_FILE="${SCRIPT_DIR}/server.log"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
[ -x "${PYTHON_BIN}" ] || PYTHON_BIN="python3"

FOREGROUND=false
ENGINE="both"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--foreground)
      FOREGROUND=true
      shift
      ;;
    --engine)
      ENGINE="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./start.sh [-f|--foreground] [--engine {python|rust|both}]"
      echo "  Starts Cloud Frugality local servers (Python on :8090, Rust on :8091)."
      echo "  By default, runs in background and records PID in .server.pid."
      echo "  Use -f/--foreground to run directly in the terminal."
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run './start.sh --help' for usage."
      exit 1
      ;;
  esac
done

# Check if already running
if [ -f "${PID_FILE}" ]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -n "${OLD_PID}" ] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "⚠️  Cloud Frugality server is already running (PID: ${OLD_PID})."
    echo "   Python Dashboard: http://localhost:8090/"
    echo "   Rust Dashboard:   http://localhost:8091/"
    echo "   Live Logs:        tail -f ${LOG_FILE}"
    echo "   To stop:          ./stop.sh"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

# Clean up any lingering processes on ports 8090 and 8091
for port in 8090 8091; do
  if lsof -ti :${port} &>/dev/null; then
    echo "⚡ Port ${port} is occupied; releasing port..."
    lsof -ti :${port} | xargs -r kill -9 2>/dev/null || true
    sleep 0.5
  fi
done

echo "=================================================================="
echo "  Starting Cloud Frugality Multi-Engine Environment"
echo "=================================================================="

if [ "${FOREGROUND}" = true ]; then
  exec "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/serve_local.py" --engine "${ENGINE}"
fi

# Run in background detached
if command -v setsid &>/dev/null; then
  setsid "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/serve_local.py" --engine "${ENGINE}" </dev/null > "${LOG_FILE}" 2>&1 &
  SERVER_PID=$!
else
  nohup "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/serve_local.py" --engine "${ENGINE}" </dev/null > "${LOG_FILE}" 2>&1 &
  SERVER_PID=$!
  disown "${SERVER_PID}" 2>/dev/null || true
fi
echo "${SERVER_PID}" > "${PID_FILE}"

echo "🚀 Background server launched (PID: ${SERVER_PID})."
echo "⏳ Waiting for health endpoints to come alive..."

READY=false
for i in {1..25}; do
  if [ "${ENGINE}" = "rust" ]; then
    if curl -fs "http://127.0.0.1:8091/healthz" &>/dev/null; then
      READY=true; break
    fi
  elif [ "${ENGINE}" = "python" ]; then
    if curl -fs "http://127.0.0.1:8090/healthz" &>/dev/null; then
      READY=true; break
    fi
  else
    if curl -fs "http://127.0.0.1:8090/healthz" &>/dev/null && curl -fs "http://127.0.0.1:8091/healthz" &>/dev/null; then
      READY=true; break
    fi
  fi
  sleep 0.4
done

if [ "${READY}" = true ]; then
  echo "✅ Servers are up and healthy!"
  echo "------------------------------------------------------------------"
  [ "${ENGINE}" != "rust" ]   && echo "  🐍 Python Dashboard: http://localhost:8090/"
  [ "${ENGINE}" != "python" ] && echo "  🦀 Rust Dashboard:   http://localhost:8091/"
  echo "  📄 Live Logs:        tail -f ${LOG_FILE}"
  echo "  🛑 Stop Servers:     ./stop.sh"
  echo "=================================================================="
else
  echo "⚠️  Servers did not respond in time. Recent log output:"
  tail -n 25 "${LOG_FILE}" 2>/dev/null || true
  exit 1
fi
