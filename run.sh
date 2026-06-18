#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Creating virtual environment…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Installing / updating dependencies…"
pip install --quiet --upgrade -r requirements.txt

HOST="${BCV_HOST:-127.0.0.1}"
PORT="${BCV_PORT:-8000}"

# BCV_VERIFY_SSL defaults to FALSE for a frictionless dev experience
# (sandboxed/minimal Python builds often have a broken system CA store).
# For production with a proper CA bundle, set BCV_VERIFY_SSL=true.
export BCV_VERIFY_SSL="${BCV_VERIFY_SSL:-false}"

echo "→ Starting BCV Scraper on http://${HOST}:${PORT}  (BCV_VERIFY_SSL=${BCV_VERIFY_SSL})"
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload

