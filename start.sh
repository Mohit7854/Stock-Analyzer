#!/usr/bin/env bash
set -euo pipefail

export GROQ_MODEL="${GROQ_MODEL:-llama-3.3-70b-versatile}"
export GROQ_TIMEOUT="${GROQ_TIMEOUT:-60}"
export GROQ_BASE_URL="${GROQ_BASE_URL:-https://api.groq.com/openai/v1}"

if [[ -z "${GROQ_API_KEY:-}" ]]; then
  echo "GROQ_API_KEY is required."
  exit 1
fi

echo "Starting API server on port ${PORT:-8000}"
exec python3 -m uvicorn api_service:app --host 0.0.0.0 --port "${PORT:-8000}"
