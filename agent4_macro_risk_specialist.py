"""
Agent 4 - Macro & Risk Specialist Agent
Focuses on macroeconomic context, regulatory risks, and industry-wide headwinds.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import json

from llm_client import _llm
from tavily_service import fetch_tavily_context

TAG = "Agent 4"


def fetch_macro_context(ticker: str, company: str, sector: str, mode: str = "quick") -> tuple[dict, dict]:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    if deep:
        queries = [
            f"current macroeconomic impact on {sector} sector 2024 2025",
            f"regulatory risks and legal challenges for {company} {ticker}",
            f"interest rate sensitivity and inflation impact on {company}",
            f"geopolitical risks affecting {sector} industry",
        ]
        max_results = 4
        snippet_len = 540
    else:
        queries = [
            f"macroeconomic and regulatory outlook for {company} {ticker}",
            f"major risks for {sector} sector this year",
        ]
        max_results = 2
        snippet_len = 320

    out, meta = fetch_tavily_context(
        agent_id=4,
        mode=mode,
        queries=queries,
        max_results=max_results,
        snippet_len=snippet_len,
        quick_cap_default=1,
        deep_cap_default=2,
    )
    return out, meta


def analyze_macro_risks(ticker: str, company: str, sector: str, stock_data: dict, tavily_context: dict, mode: str = "quick") -> str:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    sections = (
        "### 1. Macroeconomic Environment\n"
        "### 2. Regulatory and Legal Landscape\n"
        "### 3. Sector-Specific Headwinds\n"
        "### 4. Geopolitical and External Shocks\n"
        "### 5. Risk Mitigation and Resilience\n"
        "### 6. Macro Rating"
        if deep
        else
        "### 1. Macro & Sector Context\n"
        "### 2. Key Regulatory Risks\n"
        "### 3. External Headwinds\n"
        "### 4. Macro Rating"
    )

    prompt = f"""You are a Macro Risk Specialist.

Stock: {ticker} ({company})
Sector: {sector}

YAHOO DATA SNAPSHOT:
{json.dumps({"beta": stock_data.get("beta"), "market_cap": stock_data.get("market_cap")}, indent=2)}

TAVILY MACRO CONTEXT:
{json.dumps(tavily_context, indent=2)[:5000 if deep else 2500]}

Write:

## Macro & Risk Analysis Report - {ticker}

{sections}

{"Provide a detailed assessment of how broader economic shifts and regulatory changes impact this specific company." if deep else "Be concise and focus on high-impact external risks."}

End with exactly one line:
MACRO RATING: STABLE|CAUTION|CRITICAL"""

    try:
        return _llm(
            prompt,
            max_tokens=1500 if deep else 800,
            agent_tag=TAG,
            system=(
                "You are a senior macro strategist focusing on systemic risks, regulatory shifts, and economic cycles."
                if deep else
                "Be direct and risk-focused."
            ),
        )
    except Exception:
        return (
            f"## Macro & Risk Analysis Report - {ticker}\n\n"
            f"### 1. Macro & Sector Context\n"
            f"Sector={sector}. Broad market conditions and interest rate environment are primary drivers.\n\n"
            f"### 2. Key Regulatory Risks\n"
            f"Standard industry regulations apply. Monitor for sector-specific policy shifts.\n\n"
            f"### 3. External Headwinds\n"
            f"Inflation and supply chain stability remain key external variables.\n\n"
            f"### 4. Macro Rating\n"
            f"MACRO RATING: STABLE"
        )


def run(agent3_output: dict, mode: str = "quick") -> dict:
    ticker = agent3_output["ticker"]
    company = agent3_output["company"]
    stock_data = agent3_output.get("stock_data", {})
    sector = stock_data.get("sector", "Unknown")

    print(f"\n[Agent 4] Loading macro and risk context for {ticker}...")
    tavily_context, tavily_meta = fetch_macro_context(ticker, company, sector, mode=mode)
    
    if tavily_meta.get("enabled"):
        print(f"[Agent 4] Tavily queries used: {int(tavily_meta.get('successful_queries', 0) or 0)}/{int(tavily_meta.get('attempted_queries', 0) or 0)}")
    else:
        print("[Agent 4] Tavily disabled by policy for this agent.")

    print(f"[Agent 4] Running macro risk analysis...")
    report = analyze_macro_risks(ticker, company, sector, stock_data, tavily_context, mode=mode)

    return {
        **agent3_output,
        "macro_context": tavily_context,
        "macro_context_meta": tavily_meta,
        "macro_report": report,
        "macro_context_queries_used": int(tavily_meta.get("successful_queries", 0) or 0),
        "macro_context_warnings": tavily_meta.get("warnings", []),
    }


if __name__ == "__main__":
    stub = {
        "ticker": "RELIANCE.NS",
        "company": "Reliance Industries Limited",
        "stock_data": {"sector": "Energy", "beta": 0.9},
    }
    out = run(stub)
    print("\n" + "=" * 60)
    print(out["macro_report"])
