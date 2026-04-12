#!/usr/bin/env bash
set -euo pipefail

export GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.0-flash}"
export GEMINI_TIMEOUT="${GEMINI_TIMEOUT:-180}"
export GEMINI_BASE_URL="${GEMINI_BASE_URL:-https://generativelanguage.googleapis.com}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY is required."
  exit 1
fi

echo "Starting API server on port ${PORT:-8000}"
exec python3 -m uvicorn api_service:app --host 0.0.0.0 --port "${PORT:-8000}"
