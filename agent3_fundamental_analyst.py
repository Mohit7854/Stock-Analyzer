"""
Agent 3 - Fundamental Analyst Agent
Uses Yahoo Finance fundamentals and Tavily for catalysts/risks context.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tavily import TavilyClient

from llm_client import _llm

TAG = "Agent 3"
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


def fetch_fundamental_context(ticker: str, company: str, mode: str = "quick") -> dict:

    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    if deep:
        queries = [
            f"{company} earnings outlook and catalysts",
            f"{company} business risks and industry headwinds",
            f"{company} management commentary strategy execution",
            f"{company} competitive landscape market share trends",
            f"{company} valuation debate bull bear thesis",
        ]
        max_results = 3
        snippet_len = 540
    else:
        queries = [
            f"{company} earnings outlook and catalysts",
            f"{company} business risks and industry headwinds",
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


def analyze_fundamentals(ticker: str, company: str, stock_data: dict,
                         technical_report: str, tavily_context: dict, mode: str = "quick") -> str:
    fundamentals = {
        "market_cap": stock_data.get("market_cap"),
        "trailing_pe": stock_data.get("trailing_pe"),
        "forward_pe": stock_data.get("forward_pe"),
        "price_to_book": stock_data.get("price_to_book"),
        "ev_to_ebitda": stock_data.get("ev_to_ebitda"),
        "revenue_growth_pct": stock_data.get("revenue_growth_pct"),
        "earnings_growth_pct": stock_data.get("earnings_growth_pct"),
        "profit_margin_pct": stock_data.get("profit_margin_pct"),
        "debt_to_equity": stock_data.get("debt_to_equity"),
        "free_cash_flow": stock_data.get("free_cash_flow"),
        "return_on_equity_pct": stock_data.get("return_on_equity_pct"),
        "dividend_yield_pct": stock_data.get("dividend_yield_pct"),
        "sector": stock_data.get("sector"),
        "industry": stock_data.get("industry"),
    }

    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"
    sections = (
        "### 1. Business Quality and Moat\n"
        "### 2. Valuation Decomposition\n"
        "### 3. Financial Strength and Cash-Flow Durability\n"
        "### 4. Growth Drivers and Execution Risks\n"
        "### 5. Sector Positioning and Cyclical Sensitivity\n"
        "### 6. Catalyst Calendar and Downside Triggers\n"
        "### 7. Investment Thesis with Disconfirming Evidence"
        if deep
        else
        "### 1. Valuation\n"
        "### 2. Financial Health\n"
        "### 3. Growth and Earnings Quality\n"
        "### 4. Moat and Industry Position\n"
        "### 5. Catalysts and Risks\n"
        "### 6. Investment Thesis"
    )

    prompt = f"""You are a fundamental equity analyst.

Stock: {ticker} ({company})

YAHOO FUNDAMENTAL DATA:
{json.dumps(fundamentals, indent=2)}

TECHNICAL REPORT SNIPPET:
{technical_report[-1800:] if deep else technical_report[-1000:]}

TAVILY CONTEXT:
{json.dumps(tavily_context, indent=2)[:5200 if deep else 2800]}

Write:

## Fundamental Analysis Report - {ticker}

{sections}

{"Go deep on evidence quality and explicitly state what could invalidate the thesis." if deep else "Be concise and practical."}

End with exactly these two lines:
FUNDAMENTAL VIEW: BUY|HOLD|SELL
HORIZON: SHORT|MEDIUM|LONG"""

    try:
        return _llm(
            prompt,
            max_tokens=1700 if deep else 900,
            agent_tag=TAG,
            system=(
                "You are a senior buy-side fundamental analyst. Write detailed, evidence-weighted research with balanced bull and bear logic."
                if deep else
                "Be specific and data-driven."
            ),
        )
    except Exception:
        growth = stock_data.get("revenue_growth_pct")
        earnings = stock_data.get("earnings_growth_pct")
        pe = stock_data.get("trailing_pe")
        debt = stock_data.get("debt_to_equity")
        margin = stock_data.get("profit_margin_pct")

        score = 0
        if isinstance(growth, (int, float)):
            score += 1 if growth > 8 else -1 if growth < 0 else 0
        if isinstance(earnings, (int, float)):
            score += 1 if earnings > 8 else -1 if earnings < 0 else 0
        if isinstance(margin, (int, float)):
            score += 1 if margin > 10 else -1 if margin < 3 else 0
        if isinstance(debt, (int, float)):
            score += 1 if debt < 80 else -1 if debt > 180 else 0
        if isinstance(pe, (int, float)):
            score += 1 if 5 <= pe <= 30 else -1 if pe > 45 else 0

        if score >= 2:
            view = "BUY"
            horizon = "LONG"
        elif score <= -2:
            view = "SELL"
            horizon = "SHORT"
        else:
            view = "HOLD"
            horizon = "MEDIUM"

        if deep:
            return (
                f"## Fundamental Analysis Report - {ticker}\n\n"
                f"### 1. Business Quality and Moat\n"
                f"Sector={stock_data.get('sector')}, Industry={stock_data.get('industry')}. Business durability is inferred from profitability, growth consistency, and capital structure resilience.\n\n"
                f"### 2. Valuation Decomposition\n"
                f"Trailing PE={pe}, Forward PE={stock_data.get('forward_pe')}, Price-to-book={stock_data.get('price_to_book')}, EV/EBITDA={stock_data.get('ev_to_ebitda')}.\n\n"
                f"### 3. Financial Strength and Cash-Flow Durability\n"
                f"Debt/Equity={debt}, Free cash flow={stock_data.get('free_cash_flow')}, ROE={stock_data.get('return_on_equity_pct')}%, Margin={margin}%.\n\n"
                f"### 4. Growth Drivers and Execution Risks\n"
                f"Revenue growth={growth}%, Earnings growth={earnings}%. Track conversion of growth to cash flow and margin stability.\n\n"
                f"### 5. Sector Positioning and Cyclical Sensitivity\n"
                f"Beta and balance-sheet leverage shape cyclicality and drawdown behavior during sector stress.\n\n"
                f"### 6. Catalyst Calendar and Downside Triggers\n"
                f"Near-term catalysts include earnings cadence, guidance revisions, and margin trajectory. Downside triggers include growth deceleration and valuation derating.\n\n"
                f"### 7. Investment Thesis with Disconfirming Evidence\n"
                f"Deterministic fundamental score={score}. Thesis confidence should be reduced when growth momentum and valuation comfort diverge.\n\n"
                f"FUNDAMENTAL VIEW: {view}\n"
                f"HORIZON: {horizon}"
            )

        return (
            f"## Fundamental Analysis Report - {ticker}\n\n"
            f"### 1. Valuation\n"
            f"Trailing PE={pe}, Price-to-book={stock_data.get('price_to_book')}.\n\n"
            f"### 2. Financial Health\n"
            f"Debt/Equity={debt}, Free cash flow={stock_data.get('free_cash_flow')}.\n\n"
            f"### 3. Growth and Earnings Quality\n"
            f"Revenue growth={growth}%, Earnings growth={earnings}%, Margin={margin}%.\n\n"
            f"### 4. Moat and Industry Position\n"
            f"Sector={stock_data.get('sector')}, Industry={stock_data.get('industry')}.\n\n"
            f"### 5. Catalysts and Risks\n"
            f"Catalyst-risk balance is inferred from growth quality, balance-sheet profile, and valuation stretch.\n\n"
            f"### 6. Investment Thesis\n"
            f"Deterministic fundamental score={score}.\n\n"
            f"FUNDAMENTAL VIEW: {view}\n"
            f"HORIZON: {horizon}"
        )


def run(agent2_output: dict, mode: str = "quick") -> dict:
    ticker = agent2_output["ticker"]
    company = agent2_output["company"]
    stock_data = agent2_output.get("stock_data", {})
    technical_report = agent2_output.get("technical_report", "")

    print(f"\n[Agent 3] Fetching Tavily fundamental context for {ticker}...")
    tavily_context = fetch_fundamental_context(ticker, company, mode=mode)

    print(f"[Agent 3] Running fundamental analysis...")
    report = analyze_fundamentals(ticker, company, stock_data, technical_report, tavily_context, mode=mode)

    return {
        **agent2_output,
        "fundamental_context": tavily_context,
        "fundamental_report": report,
        "research_depth": mode,
        "fundamental_context_queries_used": len(tavily_context) if isinstance(tavily_context, dict) else 0,
    }


if __name__ == "__main__":
    stub = {
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "stock_data": {"trailing_pe": 30.0, "revenue_growth_pct": 8.0, "debt_to_equity": 120.0},
        "technical_report": "SIGNAL: HOLD\nCONFIDENCE: MEDIUM",
    }
    out = run(stub)
    print("\n" + "=" * 60)
    print(out["fundamental_report"])
