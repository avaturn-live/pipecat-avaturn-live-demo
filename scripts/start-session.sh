#!/usr/bin/env bash
#
# Smoke-test the session broker without the browser.
#
#     ./scripts/start-session.sh
#
# Prints { "session_id": "...", "token": "..." } if the broker is reachable
# and AVATURN_API_KEY is wired up correctly.
set -euo pipefail

HOST="${HOST:-http://localhost:8000}"

curl -sS -X POST "$HOST/api/sessions" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
