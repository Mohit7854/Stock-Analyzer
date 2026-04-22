"""
Agent 1 - Market Research Agent
Uses Yahoo Finance for stock data and Tavily for recent narrative context.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tavily import TavilyClient

from llm_client import _llm
from market_data import get_stock_snapshot, resolve_ticker as yahoo_resolve_ticker

TAG = "Agent 1"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
if not TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY environment variable is required.")
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

def _retry_tavily_search(query: str, max_retries: int = 3, base_delay: float = 1.0) -> dict:
    """Execute Tavily search with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            return tavily_client.search(query=query, search_depth="advanced", max_results=4, include_answer=True)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Tavily search failed after {max_retries} attempts: {str(exc)}") from exc
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)

_INTENT_STOPWORDS = {
    "i", "want", "need", "show", "me", "the", "a", "an", "for", "to", "of", "and",
    "stock", "shares", "company", "price", "analysis", "please", "said", "buy", "in",
    "on", "about", "one",
}


def _extract_json_object(raw: str) -> dict:
    cleaned = (raw or "").replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _heuristic_ticker_candidates(text: str) -> list[str]:
    stop = {
        "i", "want", "need", "show", "me", "the", "a", "an", "for", "to", "of", "and",
        "stock", "shares", "company", "price", "analysis", "please", "said",
    }
    out: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9.&-]*", text or ""):
        t = token.strip().strip(".").upper()
        if not t:
            continue
        if t.lower() in stop:
            continue
        if 2 <= len(t) <= 10 and re.fullmatch(r"[A-Z0-9]+", t):
            out.append(t)
    return out


def _clean_company_phrase(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9.&-]+", text or "")
    cleaned = [t for t in tokens if t and t.lower() not in _INTENT_STOPWORDS]
    return " ".join(cleaned[:6]).strip()


def _ticker_with_exchange_hint(ticker_hint: str, exchange_hint: str) -> str:
    t = (ticker_hint or "").strip().upper()
    ex = (exchange_hint or "").strip().upper()
    if not t:
        return ""
    if "." in t:
        return t
    if ex == "NSE":
        return f"{t}.NS"
    if ex == "BSE":
        return f"{t}.BO"
    return ""


def inspect_user_input_with_llm(user_input: str) -> dict:
    """
    Always send raw user text to Gemini first so it can infer ticker/company intent.
    """
    prompt = f"""Interpret the user's stock query and infer ticker intent.

User query: "{user_input}"

Return ONLY valid JSON:
{{
  "ticker_hint": "<best ticker guess like MRF or AAPL or RELIANCE>",
  "company_hint": "<best company name guess>",
  "exchange_hint": "<NSE|BSE|NASDAQ|NYSE|etc>",
  "normalized_query": "<clean short query for finance lookup>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "reasoning": "<one sentence>"
}}

If unsure, use empty strings but still return valid JSON."""

    try:
        raw = _llm(
            prompt,
            max_tokens=220,
            agent_tag=TAG,
            system="You map natural-language stock requests to likely ticker/company hints and return strict JSON.",
        )
    except Exception as exc:
        return {
            "ticker_hint": "",
            "company_hint": "",
            "exchange_hint": "",
            "normalized_query": user_input.strip(),
            "confidence": "LOW",
            "reasoning": "Ticker interpretation service temporarily unavailable; using deterministic resolver.",
            "_raw_hint_text": "",
        }
    parsed = _extract_json_object(raw)
    if not parsed:
        parsed = {
            "ticker_hint": "",
            "company_hint": "",
            "exchange_hint": "",
            "normalized_query": user_input.strip(),
            "confidence": "LOW",
            "reasoning": "Could not parse structured ticker hint; using fallback resolution.",
        }
    parsed["_raw_hint_text"] = raw
    return parsed


def resolve_ticker(user_input: str) -> tuple[dict, dict, str]:
    hint = inspect_user_input_with_llm(user_input)

    ticker_hint = (hint.get("ticker_hint") or "").strip()
    company_hint = (hint.get("company_hint") or "").strip()
    exchange_hint = (hint.get("exchange_hint") or "").strip()
    normalized_query = (hint.get("normalized_query") or "").strip()

    exchange_applied_ticker = _ticker_with_exchange_hint(ticker_hint, exchange_hint)
    cleaned_user_phrase = _clean_company_phrase(user_input)
    user_text_candidates = _heuristic_ticker_candidates(user_input)

    candidates = [
        exchange_applied_ticker,
        f"{ticker_hint} {company_hint}".strip(),
        company_hint,
        cleaned_user_phrase,
        normalized_query,
        user_input,
        ticker_hint,
        *user_text_candidates,
    ]

    seen: set[str] = set()
    ordered_candidates: list[str] = []
    for candidate in candidates:
        c = candidate.strip()
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered_candidates.append(c)

    last_error: Exception | None = None
    for candidate in ordered_candidates:
        try:
            resolved = yahoo_resolve_ticker(candidate)
            return resolved, hint, candidate
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("Unable to resolve ticker from user input.")


def fetch_news_context(ticker: str, company: str, mode: str = "quick") -> dict:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    if deep:
        queries = [
            f"{company} {ticker} latest stock news sentiment",
            f"{company} quarterly results guidance margin commentary",
            f"{company} sector demand outlook and competitive positioning",
            f"{company} regulatory developments and key risks",
            f"{company} analyst target revisions institutional flows",
        ]
        max_results = 4
        snippet_len = 540
    else:
        queries = [
            f"{company} {ticker} latest stock news sentiment",
            f"{company} major developments this week",
        ]
        max_results = 2
        snippet_len = 320

    out: dict[str, dict] = {}

    def _fetch_one(q: str) -> tuple[str, dict]:
        try:
            r = _retry_tavily_search(q)
            return q, {
                "answer": r.get("answer", ""),
                "results": [
                    {"title": x.get("title", ""), "content": (x.get("content", "")[:snippet_len])}
                    for x in r.get("results", [])
                ],
            }
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch Tavily context for '{q}': {str(exc)}") from exc

    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
        futures = [pool.submit(_fetch_one, q) for q in queries]
        for fut in as_completed(futures):
            q, payload = fut.result()
            out[q] = payload

    return out


def _summarize_news_context(news_data: dict, max_points: int = 5) -> list[str]:
    points: list[str] = []
    if not isinstance(news_data, dict):
        return points

    for payload in news_data.values():
        if not isinstance(payload, dict):
            continue
        answer = str(payload.get("answer", "")).strip()
        if answer:
            points.append(answer[:180])

        results = payload.get("results") or []
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                if title:
                    points.append(title[:140])
                if len(points) >= max_points:
                    break

        if len(points) >= max_points:
            break

    deduped: list[str] = []
    seen: set[str] = set()
    for p in points:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
        if len(deduped) >= max_points:
            break

    return deduped


def synthesize_market_summary(ticker: str, company: str, stock_data: dict, news_data: dict, mode: str = "quick") -> str:
    metrics = {
        "price": stock_data.get("price"),
        "currency": stock_data.get("currency"),
        "day_change_pct": stock_data.get("day_change_pct"),
        "month_change_pct": stock_data.get("month_change_pct"),
        "quarter_change_pct": stock_data.get("quarter_change_pct"),
        "avg_volume_20d": stock_data.get("avg_volume_20d"),
        "latest_volume": stock_data.get("latest_volume"),
        "rsi14": stock_data.get("rsi14"),
        "ma50": stock_data.get("ma50"),
        "ma200": stock_data.get("ma200"),
        "beta": stock_data.get("beta"),
        "volatility_annual_pct": stock_data.get("volatility_annual_pct"),
    }

    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"
    context_cap = 6500 if deep else 3500

    sections = (
        "### 1. Multi-Timeframe Trend Decomposition\n"
        "### 2. Participation and Volume Regime\n"
        "### 3. Sentiment and News Heatmap\n"
        "### 4. Macro/Sector Linkage\n"
        "### 5. Bull/Base/Bear Path (30-90 days)\n"
        "### 6. Watchpoints and Trigger Levels\n"
        "### 7. Trend Summary"
        if deep
        else
        "### 1. Price Trend Analysis\n"
        "### 2. Volume Analysis\n"
        "### 3. News Sentiment\n"
        "### 4. Technical Indicators\n"
        "### 5. Trend Summary"
    )

    style = (
        "Be detailed, evidence-driven, and explicit with numbers. Include concrete triggers and scenario conditions."
        if deep
        else
        "Use the provided numbers directly. Keep it concise and practical."
    )

    prompt = f"""You are a market research analyst.

Stock: {ticker} ({company})

YAHOO FINANCE METRICS:
{json.dumps(metrics, indent=2)}

TAVILY CONTEXT:
{json.dumps(news_data, indent=2)[:context_cap]}

Write:

## Market Data Report - {ticker} ({company})

{sections}

{style}

End with exactly one line:
TREND: BULLISH
or TREND: BEARISH
or TREND: NEUTRAL"""

    try:
        return _llm(
            prompt,
            max_tokens=1500 if deep else 900,
            agent_tag=TAG,
            system=(
                "You are an institutional market strategist. Prioritize depth, evidence hierarchy, and clear scenario logic."
                if deep else
                "You are a concise equity analyst."
            ),
        )
    except Exception:
        price = stock_data.get("price")
        ma50 = stock_data.get("ma50")
        ma200 = stock_data.get("ma200")
        rsi = stock_data.get("rsi14")
        day = stock_data.get("day_change_pct")
        month = stock_data.get("month_change_pct")
        quarter = stock_data.get("quarter_change_pct")
        vol = stock_data.get("latest_volume")
        avg_vol = stock_data.get("avg_volume_20d")

        trend = "NEUTRAL"
        if isinstance(price, (int, float)) and isinstance(ma50, (int, float)) and isinstance(ma200, (int, float)):
            if price > ma50 > ma200:
                trend = "BULLISH"
            elif price < ma50 < ma200:
                trend = "BEARISH"
        elif isinstance(month, (int, float)):
            trend = "BULLISH" if month > 1 else "BEARISH" if month < -1 else "NEUTRAL"

        news_points = _summarize_news_context(news_data, max_points=6 if deep else 3)
        news_note = (
            "\n".join(f"- {x}" for x in news_points)
            if news_points else
            "- External context unavailable; sentiment confidence is reduced."
        )

        if deep:
            return (
                f"## Market Data Report - {ticker} ({company})\n\n"
                f"### 1. Multi-Timeframe Trend Decomposition\n"
                f"Price={price}, Day={day}%, 1M={month}%, 3M={quarter}%, MA50={ma50}, MA200={ma200}.\n\n"
                f"### 2. Participation and Volume Regime\n"
                f"Latest volume={vol}, 20D average volume={avg_vol}. Participation quality is inferred from volume vs average-volume spread.\n\n"
                f"### 3. Sentiment and News Heatmap\n"
                f"{news_note}\n\n"
                f"### 4. Macro/Sector Linkage\n"
                f"Beta={stock_data.get('beta')} and annualized volatility={stock_data.get('volatility_annual_pct')}% indicate sensitivity to broader risk-on/risk-off moves.\n\n"
                f"### 5. Bull/Base/Bear Path (30-90 days)\n"
                f"Bull: price holds above MA50 with rising participation. Base: range-bound around MA50. Bear: loss of MA50 with RSI deterioration.\n\n"
                f"### 6. Watchpoints and Trigger Levels\n"
                f"Watch MA50/MA200 relationship, RSI14={rsi}, and sustained deviation of volume from 20D average.\n\n"
                f"### 7. Trend Summary\n"
                f"Trend inference is based on moving-average alignment, RSI regime, return profile, and participation context.\n\n"
                f"TREND: {trend}"
            )

        return (
            f"## Market Data Report - {ticker} ({company})\n\n"
            f"### 1. Price Trend Analysis\n"
            f"Price: {price} | Day change: {day}% | 1M change: {month}%\n\n"
            f"### 2. Volume Analysis\n"
            f"20D avg volume: {stock_data.get('avg_volume_20d')} | Latest volume: {stock_data.get('latest_volume')}\n\n"
            f"### 3. News Sentiment\n"
            f"{news_note}\n\n"
            f"### 4. Technical Indicators\n"
            f"MA50: {ma50} | MA200: {ma200} | RSI14: {rsi}\n\n"
            f"### 5. Trend Summary\n"
            f"Trend inference is based on moving-average alignment, RSI regime, and recent return profile.\n\n"
            f"TREND: {trend}"
        )


def run(user_input: str, mode: str = "quick") -> dict:
    print(f"\n[Agent 1] Inspecting user input with Gemini for: '{user_input}'")
    resolved, hint, used_query = resolve_ticker(user_input)
    ticker = resolved["ticker"]

    stock_data = get_stock_snapshot(ticker)
    company = stock_data.get("company") or resolved.get("company") or ticker

    if hint:
        print(
            f"[Agent 1] Gemini hint -> ticker='{hint.get('ticker_hint', '')}' "
            f"company='{hint.get('company_hint', '')}' "
            f"confidence='{hint.get('confidence', '')}'"
        )
    print(f"[Agent 1] Yahoo resolver query used -> '{used_query}'")
    print(f"[Agent 1] Resolved -> {ticker} ({company}) [{resolved.get('confidence', 'MEDIUM')}]")
    print(f"[Agent 1] Fetching Tavily context...")
    news_data = fetch_news_context(ticker, company, mode=mode)

    print(f"[Agent 1] Writing market report...")
    report = synthesize_market_summary(ticker, company, stock_data, news_data, mode=mode)

    return {
        "ticker": ticker,
        "company": company,
        "exchange": resolved.get("exchange", ""),
        "confidence": resolved.get("confidence", ""),
        "reasoning": resolved.get("reasoning", ""),
        "llm_ticker_interpretation": hint,
        "gemini_ticker_interpretation": hint,
        "stock_data": stock_data,
        "market_context": news_data,
        "market_report": report,
        "research_depth": mode,
        "context_queries_used": len(news_data) if isinstance(news_data, dict) else 0,
    }


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "MRF"
    out = run(q)
    print("\n" + "=" * 64)
    print(f"TICKER : {out['ticker']}")
    print(f"COMPANY: {out['company']}")
    print("=" * 64)
    print(out["market_report"])
