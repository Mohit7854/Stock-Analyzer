"""
Agent 2 - Technical Analyst Agent
Uses Yahoo Finance indicators as the source of technical signals.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import json

from llm_client import _llm
from tavily_service import fetch_tavily_context

TAG = "Agent 2"


def fetch_market_commentary(ticker: str, company: str, mode: str = "quick") -> tuple[dict, dict]:

    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    if deep:
        queries = [
            f"{company} {ticker} analyst commentary outlook",
            f"{company} {ticker} technical setup support resistance trend",
            f"{company} options activity implied volatility positioning",
        ]
        max_results = 4
        snippet_len = 520
    else:
        queries = [f"{company} {ticker} analyst commentary outlook"]
        max_results = 3
        snippet_len = 320

    out, meta = fetch_tavily_context(
        agent_id=2,
        mode=mode,
        queries=queries,
        max_results=max_results,
        snippet_len=snippet_len,
        quick_cap_default=1,
        deep_cap_default=1,
    )

    if deep:
        return out, meta
    return next(iter(out.values()), {}), meta


def analyze_technicals(ticker: str, company: str, stock_data: dict, tavily_context: dict, mode: str = "quick") -> str:
    technical_metrics = {
        "price": stock_data.get("price"),
        "ma20": stock_data.get("ma20"),
        "ma50": stock_data.get("ma50"),
        "ma200": stock_data.get("ma200"),
        "rsi14": stock_data.get("rsi14"),
        "macd": stock_data.get("macd"),
        "macd_signal": stock_data.get("macd_signal"),
        "macd_hist": stock_data.get("macd_hist"),
        "bb_upper": stock_data.get("bb_upper"),
        "bb_mid": stock_data.get("bb_mid"),
        "bb_lower": stock_data.get("bb_lower"),
        "support_20d": stock_data.get("support_20d"),
        "resistance_20d": stock_data.get("resistance_20d"),
        "low_52w": stock_data.get("low_52w"),
        "high_52w": stock_data.get("high_52w"),
        "avg_volume_20d": stock_data.get("avg_volume_20d"),
        "latest_volume": stock_data.get("latest_volume"),
    }

    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"
    sections = (
        "### 1. Trend Structure Across Timeframes\n"
        "### 2. Support/Resistance Map and Invalidation\n"
        "### 3. Momentum and Participation Diagnostics\n"
        "### 4. Volatility and Range Behavior\n"
        "### 5. Signal Confluence Matrix\n"
        "### 6. Trade Plan (Entry, Stop, Targets)\n"
        "### 7. 2-Week and 3-Month Scenario Paths\n"
        "### 8. Summary"
        if deep
        else
        "### 1. Trend Structure\n"
        "### 2. Support and Resistance\n"
        "### 3. Momentum (RSI, MACD, Bollinger)\n"
        "### 4. Breakout / Breakdown Assessment\n"
        "### 5. Trade Setup\n"
        "### 6. Summary"
    )

    prompt = f"""You are a technical equity analyst.

Stock: {ticker} ({company})

YAHOO TECHNICAL DATA:
{json.dumps(technical_metrics, indent=2)}

TAVILY CONTEXT:
{json.dumps(tavily_context, indent=2)[:4200 if deep else 2500]}

Write:

## Technical Analysis Report - {ticker}

{sections}

{"Use detailed numeric reasoning and provide concrete trigger levels." if deep else "Be concise, direct, and practical."}

End with exactly these two lines:
SIGNAL: BUY|HOLD|SELL
CONFIDENCE: HIGH|MEDIUM|LOW"""

    try:
        return _llm(
            prompt,
            max_tokens=1500 if deep else 800,
            agent_tag=TAG,
            system=(
                "You are a senior technical strategist writing institutional-grade analysis with explicit evidence and scenario framing."
                if deep else
                "Be concrete and concise."
            ),
        )
    except Exception:
        price = stock_data.get("price")
        ma50 = stock_data.get("ma50")
        ma200 = stock_data.get("ma200")
        rsi = stock_data.get("rsi14")
        macd = stock_data.get("macd")
        macd_signal = stock_data.get("macd_signal")
        support = stock_data.get("support_20d")
        resistance = stock_data.get("resistance_20d")

        score = 0
        if isinstance(price, (int, float)) and isinstance(ma50, (int, float)):
            score += 1 if price > ma50 else -1
        if isinstance(ma50, (int, float)) and isinstance(ma200, (int, float)):
            score += 1 if ma50 > ma200 else -1
        if isinstance(rsi, (int, float)):
            if rsi < 35:
                score += 1
            elif rsi > 70:
                score -= 1
        if isinstance(macd, (int, float)) and isinstance(macd_signal, (int, float)):
            score += 1 if macd > macd_signal else -1

        if score >= 2:
            signal = "BUY"
            confidence = "MEDIUM"
        elif score <= -2:
            signal = "SELL"
            confidence = "MEDIUM"
        else:
            signal = "HOLD"
            confidence = "LOW"

        if deep:
            return (
                f"## Technical Analysis Report - {ticker}\n\n"
                f"### 1. Trend Structure Across Timeframes\n"
                f"Price={price}, MA20={stock_data.get('ma20')}, MA50={ma50}, MA200={ma200}. Trend state is inferred from MA stacking and price location.\n\n"
                f"### 2. Support/Resistance Map and Invalidation\n"
                f"Support={support}, Resistance={resistance}. A break beyond these levels with volume expansion shifts the tactical regime.\n\n"
                f"### 3. Momentum and Participation Diagnostics\n"
                f"RSI14={rsi}, MACD={macd}, MACD signal={macd_signal}, 20D avg volume={stock_data.get('avg_volume_20d')}, latest volume={stock_data.get('latest_volume')}.\n\n"
                f"### 4. Volatility and Range Behavior\n"
                f"Bollinger bands: upper={stock_data.get('bb_upper')}, mid={stock_data.get('bb_mid')}, lower={stock_data.get('bb_lower')}. 52W range: low={stock_data.get('low_52w')} high={stock_data.get('high_52w')}.\n\n"
                f"### 5. Signal Confluence Matrix\n"
                f"Deterministic composite score={score}. Positive score implies bullish confluence; negative score implies bearish confluence.\n\n"
                f"### 6. Trade Plan (Entry, Stop, Targets)\n"
                f"Entry bias={signal}. Use support/resistance pivots for stop and target placement; tighten risk when momentum diverges from trend.\n\n"
                f"### 7. 2-Week and 3-Month Scenario Paths\n"
                f"2-week path driven by momentum and breakout confirmation. 3-month path driven by trend persistence vs mean-reversion failure.\n\n"
                f"### 8. Summary\n"
                f"Technical conviction derives from trend, momentum, and participation confluence.\n\n"
                f"SIGNAL: {signal}\n"
                f"CONFIDENCE: {confidence}"
            )

        return (
            f"## Technical Analysis Report - {ticker}\n\n"
            f"### 1. Trend Structure\n"
            f"Price={price}, MA50={ma50}, MA200={ma200}.\n\n"
            f"### 2. Support and Resistance\n"
            f"Support={stock_data.get('support_20d')}, Resistance={stock_data.get('resistance_20d')}.\n\n"
            f"### 3. Momentum (RSI, MACD, Bollinger)\n"
            f"RSI14={rsi}, MACD={macd}, Signal={macd_signal}.\n\n"
            f"### 4. Breakout / Breakdown Assessment\n"
            f"Setup is inferred from MA structure, RSI regime, and MACD crossover behavior.\n\n"
            f"### 5. Trade Setup\n"
            f"Bias={signal}.\n\n"
            f"### 6. Summary\n"
            f"Deterministic technical score={score}.\n\n"
            f"SIGNAL: {signal}\n"
            f"CONFIDENCE: {confidence}"
        )


def run(agent1_output: dict, mode: str = "quick") -> dict:
    ticker = agent1_output["ticker"]
    company = agent1_output["company"]
    stock_data = agent1_output.get("stock_data", {})

    print(f"\n[Agent 2] Loading technical context for {ticker}...")
    tavily_context, tavily_meta = fetch_market_commentary(ticker, company, mode=mode)
    if tavily_meta.get("enabled"):
        print(
            f"[Agent 2] Tavily queries used: {int(tavily_meta.get('successful_queries', 0) or 0)}"
            f"/{int(tavily_meta.get('attempted_queries', 0) or 0)}"
        )
    else:
        print("[Agent 2] Tavily disabled by policy for this agent (Yahoo-only).")
    if tavily_meta.get("warnings"):
        for warning in tavily_meta.get("warnings", []):
            print(f"[Agent 2] Tavily note: {warning}")

    print(f"[Agent 2] Running technical analysis...")
    report = analyze_technicals(ticker, company, stock_data, tavily_context, mode=mode)

    return {
        **agent1_output,
        "technical_context": tavily_context,
        "technical_context_meta": tavily_meta,
        "technical_report": report,
        "research_depth": mode,
        "technical_context_queries_used": int(tavily_meta.get("successful_queries", 0) or 0),
        "technical_context_queries_attempted": int(tavily_meta.get("attempted_queries", 0) or 0),
        "technical_context_warnings": tavily_meta.get("warnings", []),
        "tavily_degraded": bool(
            agent1_output.get("tavily_degraded", False) or tavily_meta.get("degraded", False)
        ),
    }


if __name__ == "__main__":
    stub = {
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "stock_data": {"price": 180.0, "ma50": 175.0, "ma200": 165.0, "rsi14": 58.0},
        "market_report": "TREND: BULLISH",
    }
    out = run(stub)
    print("\n" + "=" * 60)
    print(out["technical_report"])
