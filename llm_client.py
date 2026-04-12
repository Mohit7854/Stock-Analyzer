"""
llm_client.py - Shared Gemini API client for all agents.
"""

from __future__ import annotations

import os
import time

import requests

GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT", "180"))
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "4"))
RETRY_BASE_SECONDS = float(os.environ.get("GEMINI_RETRY_BASE_SECONDS", "1.5"))
_ACTIVE_API_VERSION = (os.environ.get("GEMINI_API_VERSION", "v1beta") or "v1beta").strip()
_FALLBACK_MODELS_RAW = os.environ.get(
    "GEMINI_MODEL_FALLBACKS",
    "gemini-2.0-flash,gemini-1.5-flash-latest,gemini-1.5-flash,gemini-1.5-pro",
)


def _sanitize_error(text: str) -> str:
    out = text or ""
    if GEMINI_API_KEY:
        out = out.replace(GEMINI_API_KEY, "***")
    return out


def _api_versions() -> list[str]:
    preferred = (os.environ.get("GEMINI_API_VERSION", _ACTIVE_API_VERSION) or "v1beta").strip()
    out: list[str] = []
    for version in (preferred, "v1beta", "v1"):
        if version and version not in out:
            out.append(version)
    return out


def _model_path(model_name: str) -> str:
    return model_name if model_name.startswith("models/") else f"models/{model_name}"


def _strip_model_prefix(model_name: str) -> str:
    return model_name.split("/", 1)[1] if model_name.startswith("models/") else model_name


def _candidate_models() -> list[str]:
    raw: list[str] = [MODEL]
    raw.extend(x.strip() for x in _FALLBACK_MODELS_RAW.split(","))

    out: list[str] = []
    seen: set[str] = set()
    for name in raw:
        n = _strip_model_prefix((name or "").strip())
        if not n:
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _model_exists(model_name: str, api_version: str) -> tuple[bool, str]:
    url = f"{GEMINI_BASE_URL}/{api_version}/{_model_path(model_name)}"
    try:
        resp = requests.get(url, params={"key": GEMINI_API_KEY}, timeout=15)
    except Exception as exc:
        return False, _sanitize_error(str(exc))

    if resp.status_code == 200:
        return True, ""
    if resp.status_code in (400, 404):
        return False, ""

    snippet = _sanitize_error((resp.text or "")[:260])
    return False, f"HTTP {resp.status_code}: {snippet}"


def _list_models(api_version: str) -> tuple[list[str], str]:
    url = f"{GEMINI_BASE_URL}/{api_version}/models"
    try:
        resp = requests.get(url, params={"key": GEMINI_API_KEY}, timeout=15)
    except Exception as exc:
        return [], _sanitize_error(str(exc))

    if resp.status_code != 200:
        snippet = _sanitize_error((resp.text or "")[:260])
        return [], f"HTTP {resp.status_code}: {snippet}"

    try:
        payload = resp.json()
    except Exception:
        return [], "Failed to parse Gemini models list response."

    names = [m.get("name", "") for m in payload.get("models", []) if isinstance(m, dict)]
    return names, ""


def _pick_best_model(available: list[str]) -> str:
    if not available:
        return ""

    available_clean = {_strip_model_prefix(x): x for x in available if isinstance(x, str) and x}

    for candidate in _candidate_models():
        if candidate in available_clean:
            return candidate

    for name in available_clean:
        if name.startswith("gemini-") and "flash" in name:
            return name

    for name in available_clean:
        if name.startswith("gemini-"):
            return name

    return ""


def check_gemini() -> tuple[bool, str]:
    global MODEL
    global _ACTIVE_API_VERSION

    if not GEMINI_API_KEY:
        return False, "GEMINI_API_KEY is not set. Add it to your environment or .env file."

    last_problem = ""
    for candidate in _candidate_models():
        for api_version in _api_versions():
            ok, problem = _model_exists(candidate, api_version)
            if ok:
                MODEL = candidate
                _ACTIVE_API_VERSION = api_version
                return True, f"Gemini API is ready with model '{MODEL}' ({_ACTIVE_API_VERSION})."
            if problem:
                last_problem = problem

    discovered: list[str] = []
    for api_version in _api_versions():
        names, problem = _list_models(api_version)
        if names:
            discovered = names
            best = _pick_best_model(names)
            if best:
                MODEL = best
                _ACTIVE_API_VERSION = api_version
                return True, f"Gemini API is ready with auto-selected model '{MODEL}' ({_ACTIVE_API_VERSION})."
        if problem:
            last_problem = problem

    msg = "Could not connect to Gemini API or validate a usable model."
    if discovered:
        sample = ", ".join(_strip_model_prefix(x) for x in discovered[:5])
        msg += f" Available models example: {sample}."
    else:
        msg += " Set GEMINI_MODEL to an available model like gemini-2.0-flash."
    if last_problem:
        msg += f" Details: {last_problem}"
    return False, msg


def _llm(
    prompt: str,
    max_tokens: int = 1200,
    agent_tag: str = "Agent",
    system: str = "You are a helpful financial analyst assistant.",
) -> str:
    global MODEL
    global _ACTIVE_API_VERSION

    if not GEMINI_API_KEY:
        raise RuntimeError(f"[{agent_tag}] GEMINI_API_KEY is missing.")

    combined_prompt = f"System instructions:\n{system}\n\nUser request:\n{prompt}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": combined_prompt},
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": int(max_tokens),
            "temperature": 0.2,
        },
    }

    soft_errors: list[str] = []
    for candidate in _candidate_models():
        model_path = _model_path(candidate)
        for api_version in _api_versions():
            url = f"{GEMINI_BASE_URL}/{api_version}/{model_path}:generateContent"
            resp = None
            last_transport_error = ""
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = requests.post(
                        url,
                        params={"key": GEMINI_API_KEY},
                        json=payload,
                        timeout=TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    last_transport_error = _sanitize_error(str(exc))
                    if attempt < MAX_RETRIES:
                        wait_s = RETRY_BASE_SECONDS * (2 ** attempt)
                        time.sleep(wait_s)
                        continue
                    break

                if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                    wait_s = RETRY_BASE_SECONDS * (2 ** attempt)
                    time.sleep(wait_s)
                    continue

                break

            if resp is None:
                if last_transport_error:
                    soft_errors.append(last_transport_error)
                continue

            if resp.status_code in (400, 404):
                soft_errors.append(f"{candidate}@{api_version}:HTTP {resp.status_code}")
                continue

            if resp.status_code == 429:
                soft_errors.append(f"{candidate}@{api_version}:rate_limited")
                continue

            if resp.status_code >= 300:
                snippet = _sanitize_error((resp.text or "")[:260])
                raise RuntimeError(
                    f"[{agent_tag}] Gemini request failed with HTTP {resp.status_code}: {snippet}"
                )

            try:
                data = resp.json()
            except Exception as exc:
                raise RuntimeError(
                    f"[{agent_tag}] Gemini returned invalid JSON: {_sanitize_error(str(exc))}"
                ) from exc

            candidates = data.get("candidates") or []
            if not candidates:
                feedback = data.get("promptFeedback")
                raise RuntimeError(f"[{agent_tag}] Gemini returned no candidates. Feedback: {feedback}")

            parts = ((candidates[0].get("content") or {}).get("parts") or [])
            content = "".join((p.get("text") or "") for p in parts if isinstance(p, dict)).strip()
            if not content:
                finish_reason = candidates[0].get("finishReason", "UNKNOWN")
                raise RuntimeError(
                    f"[{agent_tag}] Empty response from Gemini model '{candidate}' (finishReason={finish_reason})."
                )

            MODEL = candidate
            _ACTIVE_API_VERSION = api_version
            return content

    detail = "; ".join(soft_errors[:4])
    raise RuntimeError(
        f"[{agent_tag}] Gemini request failed for configured models."
        + (f" Tried: {detail}" if detail else "")
    )
