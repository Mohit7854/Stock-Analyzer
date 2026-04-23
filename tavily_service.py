"""
Shared Tavily helpers with throttling and graceful degradation controls.
"""

from __future__ import annotations

import os
import time
from typing import Any

from tavily import TavilyClient

DEFAULT_ENABLED_AGENTS = "1,3,5"
_PROVIDER_BLOCK_REASON: str | None = None

_QUOTA_HINTS = (
    "usage limit",
    "plan's set usage limit",
    "quota",
    "rate limit",
    "too many requests",
    "429",
)
_AUTH_HINTS = (
    "unauthorized",
    "forbidden",
    "invalid api key",
    "invalid key",
    "401",
    "403",
)
_NETWORK_HINTS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "service unavailable",
    "gateway",
)


def _clean_search_depth(raw: str | None) -> str:
    value = str(raw or "basic").strip().lower()
    return value if value in {"basic", "advanced"} else "basic"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return max(minimum, default)
    try:
        value = int(str(raw).strip())
    except Exception:
        return max(minimum, default)
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return max(minimum, default)
    try:
        value = float(str(raw).strip())
    except Exception:
        return max(minimum, default)
    return max(minimum, value)


def _normalize_agent_id(agent_id: int | str) -> str:
    raw = str(agent_id or "").strip().lower()
    if raw.startswith("agent"):
        raw = raw.replace("agent", "", 1).strip()
    return raw


def _parse_enabled_agents(raw: str | None) -> list[str]:
    text = (raw or DEFAULT_ENABLED_AGENTS).strip()
    if not text:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for token in text.split(","):
        item = _normalize_agent_id(token)
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def classify_tavily_exception(exc: Exception) -> str:
    text = str(exc or "").lower()

    if any(hint in text for hint in _QUOTA_HINTS):
        return "quota"
    if any(hint in text for hint in _AUTH_HINTS):
        return "auth"
    if any(hint in text for hint in _NETWORK_HINTS):
        return "network"
    return "unknown"


def get_tavily_policy() -> dict[str, Any]:
    enabled_agents = _parse_enabled_agents(os.environ.get("TAVILY_ENABLED_AGENTS"))
    fail_open = _env_bool("TAVILY_FAIL_OPEN", True)
    max_retries = _env_int("TAVILY_MAX_RETRIES", 1, minimum=1)
    min_delay_seconds = _env_float("TAVILY_MIN_DELAY_SECONDS", 1.5, minimum=0.0)
    retry_backoff_base = _env_float("TAVILY_RETRY_BACKOFF_BASE", 1.0, minimum=0.0)
    search_depth = _clean_search_depth(os.environ.get("TAVILY_SEARCH_DEPTH"))

    return {
        "enabled_agents": enabled_agents,
        "enabled_agent_names": [f"agent{x}" for x in enabled_agents],
        "fail_open": fail_open,
        "max_retries": max_retries,
        "min_delay_seconds": min_delay_seconds,
        "retry_backoff_base": retry_backoff_base,
        "search_depth": search_depth,
        "required": bool(enabled_agents) and not fail_open,
    }


def _query_cap(agent_id: str, mode: str, quick_default: int, deep_default: int) -> int:
    key = f"TAVILY_{(mode or 'quick').strip().upper()}_QUERY_CAP_AGENT{agent_id}"
    default = deep_default if (mode or "quick").strip().lower() == "deep" else quick_default
    return _env_int(key, default, minimum=1)


def _search_with_retry(
    client: TavilyClient,
    query: str,
    max_results: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    attempts = int(policy.get("max_retries", 1) or 1)
    backoff_base = float(policy.get("retry_backoff_base", 1.0) or 0.0)

    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return client.search(
                query=query,
                search_depth=str(policy.get("search_depth") or "basic"),
                max_results=max_results,
                include_answer=True,
            )
        except Exception as exc:
            last_exc = exc
            kind = classify_tavily_exception(exc)
            if kind in {"quota", "auth"}:
                break
            if attempt == attempts - 1:
                break

            delay = backoff_base * (2**attempt)
            if delay > 0:
                time.sleep(delay)

    if last_exc is None:
        raise RuntimeError("Unknown Tavily search failure.")
    raise last_exc


def fetch_tavily_context(
    *,
    agent_id: int | str,
    mode: str,
    queries: list[str],
    max_results: int,
    snippet_len: int,
    quick_cap_default: int = 1,
    deep_cap_default: int = 2,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    global _PROVIDER_BLOCK_REASON

    policy = get_tavily_policy()
    agent_norm = _normalize_agent_id(agent_id)
    mode_norm = (mode or "quick").strip().lower()
    query_cap = _query_cap(agent_norm, mode_norm, quick_cap_default, deep_cap_default)
    selected_queries = [q.strip() for q in queries if q and q.strip()][:query_cap]

    meta: dict[str, Any] = {
        "agent": f"agent{agent_norm}",
        "mode": mode_norm,
        "enabled": agent_norm in (policy.get("enabled_agents") or []),
        "query_cap": query_cap,
        "configured": bool((os.environ.get("TAVILY_API_KEY") or "").strip()),
        "attempted_queries": 0,
        "successful_queries": 0,
        "failed_queries": 0,
        "degraded": False,
        "warnings": [],
        "status": "ok",
    }

    if not selected_queries:
        meta["status"] = "no_queries"
        return {}, meta

    if not meta["enabled"]:
        meta["status"] = "disabled"
        return {}, meta

    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        if policy.get("required"):
            raise ValueError("TAVILY_API_KEY environment variable is required (TAVILY_FAIL_OPEN=false).")
        meta["status"] = "missing_key"
        meta["degraded"] = True
        meta["warnings"].append("TAVILY_API_KEY is not set; Tavily context skipped.")
        return {}, meta

    if _PROVIDER_BLOCK_REASON and policy.get("fail_open"):
        meta["status"] = "provider_unavailable"
        meta["degraded"] = True
        if _PROVIDER_BLOCK_REASON == "quota":
            meta["warnings"].append("Tavily quota reached; Tavily is temporarily disabled for this process.")
        elif _PROVIDER_BLOCK_REASON == "auth":
            meta["warnings"].append("Tavily authentication failed; Tavily is disabled until key is corrected.")
        else:
            meta["warnings"].append("Tavily is temporarily unavailable in this process.")
        return {}, meta

    out: dict[str, dict[str, Any]] = {}
    client = TavilyClient(api_key=api_key)

    for idx, query in enumerate(selected_queries):
        if idx > 0 and float(policy.get("min_delay_seconds", 0.0) or 0.0) > 0:
            time.sleep(float(policy.get("min_delay_seconds", 0.0) or 0.0))

        meta["attempted_queries"] += 1
        try:
            response = _search_with_retry(client, query, max_results=max_results, policy=policy)
            rows = response.get("results", []) if isinstance(response, dict) else []
            payload = {
                "answer": response.get("answer", "") if isinstance(response, dict) else "",
                "results": [
                    {
                        "title": str(item.get("title", "")),
                        "content": str(item.get("content", ""))[:snippet_len],
                    }
                    for item in rows[:max_results]
                    if isinstance(item, dict)
                ],
            }
            out[query] = payload
            meta["successful_queries"] += 1
        except Exception as exc:
            meta["failed_queries"] += 1
            meta["degraded"] = True
            kind = classify_tavily_exception(exc)
            if kind in {"quota", "auth"}:
                _PROVIDER_BLOCK_REASON = kind
            if kind == "quota":
                msg = "Tavily quota reached; skipped Tavily enrichment for this run."
            elif kind == "auth":
                msg = "Tavily authentication failed; check TAVILY_API_KEY."
            elif kind == "network":
                msg = "Tavily temporarily unavailable; continuing without Tavily context."
            else:
                msg = "Tavily request failed; continuing without Tavily context."

            if msg not in meta["warnings"]:
                meta["warnings"].append(msg)

            if not policy.get("fail_open"):
                raise RuntimeError(f"Failed to fetch Tavily context for '{query}': {exc}") from exc

            out[query] = {"answer": "", "results": []}
            if kind in {"quota", "auth"}:
                remaining = len(selected_queries) - idx - 1
                if remaining > 0:
                    meta["warnings"].append(
                        f"Skipped remaining {remaining} Tavily queries after {kind} error to reduce usage."
                    )
                break

    if meta["failed_queries"] > 0 and meta["successful_queries"] == 0:
        meta["status"] = "failed_all"
    elif meta["failed_queries"] > 0:
        meta["status"] = "partial"

    return out, meta
