"""
llm_client.py - Shared Groq API client for all agents (OpenAI-compatible).
"""

from __future__ import annotations

import os
import time
from threading import Lock

import requests

GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TIMEOUT_SECONDS = int(os.environ.get("GROQ_TIMEOUT", "60"))
MAX_RETRIES = int(os.environ.get("GROQ_MAX_RETRIES", "3"))
RETRY_BASE_SECONDS = float(os.environ.get("GROQ_RETRY_BASE_SECONDS", "1.0"))
MIN_CALL_INTERVAL_SECONDS = float(os.environ.get("GROQ_MIN_CALL_INTERVAL_SECONDS", "1.0"))
MAX_RETRY_DELAY_SECONDS = float(os.environ.get("GROQ_MAX_RETRY_DELAY_SECONDS", "60"))
RATE_LIMIT_MIN_WAIT_SECONDS = float(os.environ.get("GROQ_RATE_LIMIT_MIN_WAIT_SECONDS", "10"))
FAIL_FAST_ON_429 = str(os.environ.get("GROQ_FAIL_FAST_ON_429", "true")).strip().lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_COOLDOWN_SECONDS = float(os.environ.get("GROQ_RATE_LIMIT_COOLDOWN_SECONDS", "60"))

_FALLBACK_MODELS_RAW = os.environ.get(
    "GROQ_MODEL_FALLBACKS",
    "llama-3.3-70b-versatile,llama-3.1-70b-versatile,mixtral-8x7b-32768",
)

_LLM_RATE_LOCK = Lock()
_LAST_LLM_CALL_TS = 0.0
_RATE_LIMIT_BLOCK_UNTIL = 0.0


def _sanitize_error(text: str) -> str:
    out = text or ""
    if GROQ_API_KEY:
        out = out.replace(GROQ_API_KEY, "***")
    return out


def _candidate_models() -> list[str]:
    raw: list[str] = [MODEL]
    raw.extend(x.strip() for x in _FALLBACK_MODELS_RAW.split(","))

    out: list[str] = []
    seen: set[str] = set()
    for name in raw:
        n = (name or "").strip()
        if not n:
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _respect_min_call_interval() -> None:
    global _LAST_LLM_CALL_TS

    wait_for = 0.0
    with _LLM_RATE_LOCK:
        now = time.time()
        elapsed = now - _LAST_LLM_CALL_TS
        if MIN_CALL_INTERVAL_SECONDS > 0 and elapsed < MIN_CALL_INTERVAL_SECONDS:
            wait_for = MIN_CALL_INTERVAL_SECONDS - elapsed

    if wait_for > 0:
        time.sleep(wait_for)


def _mark_call_timestamp() -> None:
    global _LAST_LLM_CALL_TS
    with _LLM_RATE_LOCK:
        _LAST_LLM_CALL_TS = time.time()


def _retry_after_seconds(resp: requests.Response) -> float:
    retry_after = (resp.headers or {}).get("Retry-After")
    if not retry_after:
        return 0.0

    try:
        seconds = float(str(retry_after).strip())
    except Exception:
        return 0.0
    if seconds <= 0:
        return 0.0
    return min(seconds, max(1.0, MAX_RETRY_DELAY_SECONDS))


def _set_rate_limit_cooldown(wait_s: float = 0.0) -> None:
    global _RATE_LIMIT_BLOCK_UNTIL

    hold = max(wait_s, RATE_LIMIT_COOLDOWN_SECONDS)
    if hold <= 0:
        return
    _RATE_LIMIT_BLOCK_UNTIL = max(_RATE_LIMIT_BLOCK_UNTIL, time.time() + hold)


def _clear_rate_limit_cooldown() -> None:
    global _RATE_LIMIT_BLOCK_UNTIL
    _RATE_LIMIT_BLOCK_UNTIL = 0.0


def _is_rate_limited_now() -> bool:
    return time.time() < _RATE_LIMIT_BLOCK_UNTIL


def check_groq() -> tuple[bool, str]:
    """Check connection to Groq API."""
    global MODEL

    if not GROQ_API_KEY:
        return False, "GROQ_API_KEY is not set. Add it to your environment or .env file."

    url = f"{GROQ_BASE_URL}/models"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id") for m in data.get("data", [])]
            if MODEL in models:
                return True, f"Groq API is ready with model '{MODEL}'."
            elif models:
                # Fallback to first available if requested model not found
                return True, f"Groq API is ready. Available models: {', '.join(models[:3])}..."
            return True, "Groq API is reachable."
        else:
            snippet = _sanitize_error((resp.text or "")[:260])
            return False, f"Groq API returned HTTP {resp.status_code}: {snippet}"
    except Exception as exc:
        return False, f"Failed to connect to Groq API: {_sanitize_error(str(exc))}"

# Alias for backward compatibility if needed, though we will update references
def check_gemini() -> tuple[bool, str]:
    return check_groq()


def _llm(
    prompt: str,
    max_tokens: int = 1200,
    agent_tag: str = "Agent",
    system: str = "You are a helpful financial analyst assistant.",
) -> str:
    global MODEL

    if not GROQ_API_KEY:
        raise RuntimeError(f"[{agent_tag}] GROQ_API_KEY is missing.")

    if _is_rate_limited_now():
        raise RuntimeError(f"[{agent_tag}] Groq is temporarily rate-limited; retry after cooldown.")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": int(max_tokens),
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    soft_errors: list[str] = []
    
    # Try with candidate models if primary fails
    for candidate in _candidate_models():
        payload["model"] = candidate
        url = f"{GROQ_BASE_URL}/chat/completions"
        
        resp = None
        last_transport_error = ""
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                _respect_min_call_interval()
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=TIMEOUT_SECONDS,
                )
                _mark_call_timestamp()
            except Exception as exc:
                last_transport_error = _sanitize_error(str(exc))
                if attempt < MAX_RETRIES:
                    wait_s = RETRY_BASE_SECONDS * (2 ** attempt)
                    wait_s = min(wait_s, max(1.0, MAX_RETRY_DELAY_SECONDS))
                    time.sleep(wait_s)
                    continue
                break

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                wait_s = RETRY_BASE_SECONDS * (2 ** attempt)
                wait_s = min(wait_s, max(1.0, MAX_RETRY_DELAY_SECONDS))
                if resp.status_code == 429:
                    header_wait = _retry_after_seconds(resp)
                    _set_rate_limit_cooldown(header_wait)
                    if FAIL_FAST_ON_429:
                        break
                    wait_s = max(wait_s, RATE_LIMIT_MIN_WAIT_SECONDS, header_wait)
                time.sleep(wait_s)
                continue

            break

        if resp is None:
            if last_transport_error:
                soft_errors.append(last_transport_error)
            continue

        if resp.status_code in (400, 404):
            soft_errors.append(f"{candidate}:HTTP {resp.status_code}")
            continue

        if resp.status_code == 429:
            _set_rate_limit_cooldown(_retry_after_seconds(resp))
            soft_errors.append(f"{candidate}:rate_limited")
            continue

        if resp.status_code >= 300:
            snippet = _sanitize_error((resp.text or "")[:260])
            raise RuntimeError(
                f"[{agent_tag}] Groq request failed with HTTP {resp.status_code}: {snippet}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"[{agent_tag}] Groq returned invalid JSON: {_sanitize_error(str(exc))}"
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"[{agent_tag}] Groq returned no choices. Data: {data}")

        content = choices[0].get("message", {}).get("content", "").strip()
        if not content:
            finish_reason = choices[0].get("finish_reason", "UNKNOWN")
            raise RuntimeError(
                f"[{agent_tag}] Empty response from Groq model '{candidate}' (finish_reason={finish_reason})."
            )

        MODEL = candidate
        _clear_rate_limit_cooldown()
        return content

    detail = "; ".join(soft_errors[:4])
    raise RuntimeError(
        f"[{agent_tag}] Groq request failed for configured models."
        + (f" Tried: {detail}" if detail else "")
    )
