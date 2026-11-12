#!/usr/bin/env bash
# Local startup: create venv, install deps, start vCore (macOS / Linux)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

log() { printf '[start] %s\n' "$*"; }
fail() { printf '[start] ERROR: %s\n' "$*" >&2; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found. Install Python 3.11+ (e.g. brew install python@3.12 / apt install python3 python3-venv)"
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11+ required (found ${PY_VER})"

if [[ ! -d .venv ]]; then
  log "Creating virtualenv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

log "Installing dependencies ..."
pip install -q --upgrade pip
pip install -q -e ".[dev]"

mkdir -p uploads

if [[ ! -f .env ]]; then
  log "Creating .env from .env.example ..."
  cp .env.example .env
fi

if [[ -f customer.xlsx ]]; then
  log "Sample file found: customer.xlsx (auto-loaded on startup via .env)"
else
  log "No customer.xlsx in project root — upload via Web UI after start"
fi

PORT="$(grep -E '^VCENTEREMU_PORT=' .env 2>/dev/null | cut -d= -f2- || echo 8181)"
HOST="$(grep -E '^VCENTEREMU_HOST=' .env 2>/dev/null | cut -d= -f2- || echo 127.0.0.1)"
PORT="${PORT:-8181}"
HOST="${HOST:-127.0.0.1}"

echo ""
echo "============================================"
echo " vCore — local server"
echo "============================================"
echo " Web UI:  http://${HOST}:${PORT}/"
echo " API:     http://${HOST}:${PORT}/rest/"
echo " Health:  http://${HOST}:${PORT}/health"
echo ""
echo " Stop with Ctrl+C"
echo " Smoke test: bash scripts/smoke-test-mac.sh"
echo "============================================"
echo ""

exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload --env-file .env
