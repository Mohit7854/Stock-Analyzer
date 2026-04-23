"""
run.py - Master Orchestrator
Pipeline:
    Agent 1 (Market) -> Agent 2 (Technical) ->
    Agent 3 (Fundamental) -> Agent 4 (Macro & Risk) ->
    Agent 5 (Investment Advisor)

Also supports two-stock comparison:
    - Two positional queries: python run.py "asian paints" "mrf"
    - Natural text: python run.py "compare asian paints and mrf"
"""

from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root, regardless of current working directory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import os
import sys
import json
import re
import argparse
import time
from datetime import datetime

# Ensure the agents directory is on the path when running from elsewhere
sys.path.insert(0, str(Path(__file__).parent))

import agent1_market_research
import agent2_technical_analyst
import agent3_fundamental_analyst
import agent4_macro_risk_specialist
import agent5_investment_advisor
import llm_client
from llm_client import _llm
from llm_client import check_groq
from tavily_service import get_tavily_policy


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
DIM    = "\033[2m"

def banner(text: str, color: str = CYAN) -> None:
    width = 64
    print(f"\n{color}{BOLD}{'─' * width}{RESET}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(f"{color}{BOLD}{'─' * width}{RESET}")

def step(agent_num: int, name: str) -> None:
    print(f"\n{YELLOW}{BOLD}▶  Agent {agent_num} — {name}{RESET}")

def ok(msg: str) -> None:
    print(f"{GREEN}✓  {msg}{RESET}")

def info(msg: str) -> None:
    print(f"{DIM}   {msg}{RESET}")

def error(msg: str) -> None:
    print(f"{RED}✗  {msg}{RESET}")


# ---------------------------------------------------------------------------
# Validate environment
# ---------------------------------------------------------------------------
def check_env() -> bool:
    ok_groq, message = check_groq()
    if not ok_groq:
        error(message)
        return False

    ok(message)
    policy = get_tavily_policy()
    enabled = policy.get("enabled_agent_names") or []
    info(
        "Tavily policy"
        + f" | enabled_agents={','.join(enabled) if enabled else 'none'}"
        + f" | fail_open={policy.get('fail_open')}"
        + f" | max_retries={policy.get('max_retries')}"
        + f" | min_delay_seconds={policy.get('min_delay_seconds')}"
        + f" | search_depth={policy.get('search_depth')}"
    )

    tavily_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not tavily_key:
        if policy.get("required"):
            error("TAVILY_API_KEY is required when TAVILY_FAIL_OPEN=false.")
            return False
        info("TAVILY_API_KEY is not set; Tavily context will be skipped where optional.")
    else:
        ok("TAVILY_API_KEY is configured.")
    return True


# ---------------------------------------------------------------------------
# Save report to file
# ---------------------------------------------------------------------------
def save_report(output: dict) -> Path | None:
    reports_dir = Path(__file__).parent / "reports"
    try:
        reports_dir.mkdir(exist_ok=True)
    except Exception:
        # Fallback to /tmp for serverless environments like Vercel
        reports_dir = Path("/tmp/reports")
        try:
            reports_dir.mkdir(exist_ok=True)
        except Exception:
            return None

    ticker    = output.get("ticker", "UNKNOWN")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = reports_dir / f"{ticker}_{timestamp}.md"

    # ... existing lines logic ...
    lines = [
        f"# Stock Analysis Report — {ticker} ({output.get('company', '')})",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "---",
        "",
        "## Agent 1 — Market Research",
        output.get("market_report", ""),
        "",
        "---",
        "",
        "## Agent 2 — Technical Analysis",
        output.get("technical_report", ""),
        "",
        "---",
        "",
        "## Agent 3 — Fundamental Analysis",
        output.get("fundamental_report", ""),
        "",
        "---",
        "",
        "## Agent 4 — Macro & Risk Analysis",
        output.get("macro_report", ""),
        "",
        "---",
        "",
        "## Agent 5 — Final Investment Report",
        output.get("final_report", ""),
        "",
    ]

    try:
        filename.write_text("\n".join(lines), encoding="utf-8")
        return filename
    except Exception:
        return None


def save_comparison_report(output_a: dict, output_b: dict, comparison_report: str) -> Path | None:
    reports_dir = Path(__file__).parent / "reports"
    try:
        reports_dir.mkdir(exist_ok=True)
    except Exception:
        reports_dir = Path("/tmp/reports")
        try:
            reports_dir.mkdir(exist_ok=True)
        except Exception:
            return None

    t1 = output_a.get("ticker", "A")
    t2 = output_b.get("ticker", "B")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = reports_dir / f"COMPARE_{t1}_VS_{t2}_{timestamp}.md"

    lines = [
        f"# Stock Comparison Report - {t1} vs {t2}",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "---",
        "",
        f"## {t1} Final Report",
        output_a.get("final_report", ""),
        "",
        "---",
        "",
        f"## {t2} Final Report",
        output_b.get("final_report", ""),
        "",
        "---",
        "",
        "## Comparison Report",
        comparison_report,
        "",
    ]

    try:
        filename.write_text("\n".join(lines), encoding="utf-8")
        return filename
    except Exception:
        return None


def _extract_json_object(raw: str) -> dict:
    cleaned = (raw or "").replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        obj = json.loads(cleaned)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _heuristic_compare_split(text: str) -> tuple[bool, list[str]]:
    lower = (text or "").lower().strip()
    if not lower:
        return False, []

    cleaned = re.sub(r"\b(compare|comparison|analyse|analyze)\b", " ", lower)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?")

    if " vs " in cleaned:
        parts = [p.strip(" .,!?") for p in cleaned.split(" vs ", 1)]
        if len(parts) == 2 and all(parts):
            return True, parts

    if " versus " in cleaned:
        parts = [p.strip(" .,!?") for p in cleaned.split(" versus ", 1)]
        if len(parts) == 2 and all(parts):
            return True, parts

    if " and " in cleaned:
        parts = [p.strip(" .,!?") for p in cleaned.split(" and ", 1)]
        if len(parts) == 2 and all(parts):
            return True, parts

    if "," in cleaned:
        parts = [p.strip(" .,!?") for p in cleaned.split(",") if p.strip(" .,!?")]
        if len(parts) == 2:
            return True, parts

    return False, []


def detect_comparison_request(text: str) -> tuple[bool, list[str]]:
    prompt = f"""Determine if the user wants to compare TWO stocks.

User input: "{text}"

Return only valid JSON:
{{
  "is_comparison": true or false,
  "stock_1": "<first stock phrase>",
  "stock_2": "<second stock phrase>"
}}

If not comparison, return empty strings for stock_1 and stock_2.
"""

    try:
        raw = _llm(prompt, max_tokens=120, agent_tag="Comparator", system="You extract stock comparison intent.")
        parsed = _extract_json_object(raw)
    except Exception:
        parsed = {}

    if parsed:
        is_cmp = bool(parsed.get("is_comparison"))
        s1 = str(parsed.get("stock_1", "")).strip()
        s2 = str(parsed.get("stock_2", "")).strip()
        if is_cmp and s1 and s2:
            return True, [s1, s2]

    return _heuristic_compare_split(text)


def detect_single_vs_multi_stock(raw_queries: list[str]) -> tuple[str, list[str]]:
    """
    Controller/router for single-stock vs comparison mode.
    Returns:
      ("single", [query])
      ("multi", [query_a, query_b])
    """
    cleaned = [q.strip() for q in raw_queries if q and q.strip()]
    if not cleaned:
        return "single", []

    if len(cleaned) >= 2:
        return "multi", [cleaned[0], cleaned[1]]

    is_cmp, parsed = detect_comparison_request(cleaned[0])
    if is_cmp and len(parsed) == 2 and parsed[0].strip() and parsed[1].strip():
        return "multi", [parsed[0].strip(), parsed[1].strip()]

    return "single", [cleaned[0]]


def _extract_rubric_score(output: dict) -> int | None:
    rubric = output.get("rubric", {}) if isinstance(output, dict) else {}
    if not isinstance(rubric, dict):
        return None
    try:
        value = int(round(float(rubric.get("normalized_score"))))
    except Exception:
        return None
    return max(0, min(100, value))


def _deterministic_comparison_choice(output_a: dict, output_b: dict) -> tuple[str, str, dict]:
    t1 = str(output_a.get("ticker", "A")).upper()
    t2 = str(output_b.get("ticker", "B")).upper()

    s1 = output_a.get("structured_output", {}) or {}
    s2 = output_b.get("structured_output", {}) or {}

    c1 = int(s1.get("conviction", 5) or 5)
    c2 = int(s2.get("conviction", 5) or 5)

    risk_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    r1 = risk_rank.get(str(s1.get("risk", "MEDIUM")).upper(), 2)
    r2 = risk_rank.get(str(s2.get("risk", "MEDIUM")).upper(), 2)

    rub1 = _extract_rubric_score(output_a)
    rub2 = _extract_rubric_score(output_b)

    basis = "conviction_risk"
    confidence = "LOW"
    winner = t1

    if rub1 is not None and rub2 is not None:
        delta = rub1 - rub2
        if abs(delta) >= 3:
            winner = t1 if delta > 0 else t2
            basis = "rubric_delta"
            confidence = "HIGH" if abs(delta) >= 14 else "MEDIUM" if abs(delta) >= 7 else "LOW"
        else:
            if c1 > c2:
                winner = t1
                confidence = "MEDIUM" if c1 - c2 >= 2 else "LOW"
            elif c2 > c1:
                winner = t2
                confidence = "MEDIUM" if c2 - c1 >= 2 else "LOW"
            else:
                winner = t1 if r1 <= r2 else t2
                confidence = "LOW"
            basis = "conviction_risk_after_rubric_tie"
    else:
        if c1 > c2:
            winner = t1
            confidence = "MEDIUM" if c1 - c2 >= 2 else "LOW"
        elif c2 > c1:
            winner = t2
            confidence = "MEDIUM" if c2 - c1 >= 2 else "LOW"
        else:
            winner = t1 if r1 <= r2 else t2
            confidence = "LOW"
        basis = "conviction_risk"

    rubric_delta = None
    if rub1 is not None and rub2 is not None:
        rubric_delta = rub1 - rub2

    meta = {
        "deterministic_basis": basis,
        "rubric_score_a": rub1,
        "rubric_score_b": rub2,
        "rubric_delta": rubric_delta,
        "conviction_a": c1,
        "conviction_b": c2,
        "risk_rank_a": r1,
        "risk_rank_b": r2,
    }
    return winner, confidence, meta


def build_comparison_report(query_a: str, query_b: str, output_a: dict, output_b: dict, mode: str = "quick") -> str:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    t1 = output_a.get("ticker", "A")
    t2 = output_b.get("ticker", "B")
    c1 = output_a.get("company", t1)
    c2 = output_b.get("company", t2)

    metrics = {
        t1: {
            "company": c1,
            "price": output_a.get("stock_data", {}).get("price"),
            "market_cap": output_a.get("stock_data", {}).get("market_cap"),
            "trailing_pe": output_a.get("stock_data", {}).get("trailing_pe"),
            "rsi14": output_a.get("stock_data", {}).get("rsi14"),
            "ma50": output_a.get("stock_data", {}).get("ma50"),
            "ma200": output_a.get("stock_data", {}).get("ma200"),
            "revenue_growth_pct": output_a.get("stock_data", {}).get("revenue_growth_pct"),
            "earnings_growth_pct": output_a.get("stock_data", {}).get("earnings_growth_pct"),
            "rubric_score_100": _extract_rubric_score(output_a),
            "rubric_grade": (output_a.get("rubric", {}) or {}).get("grade"),
        },
        t2: {
            "company": c2,
            "price": output_b.get("stock_data", {}).get("price"),
            "market_cap": output_b.get("stock_data", {}).get("market_cap"),
            "trailing_pe": output_b.get("stock_data", {}).get("trailing_pe"),
            "rsi14": output_b.get("stock_data", {}).get("rsi14"),
            "ma50": output_b.get("stock_data", {}).get("ma50"),
            "ma200": output_b.get("stock_data", {}).get("ma200"),
            "revenue_growth_pct": output_b.get("stock_data", {}).get("revenue_growth_pct"),
            "earnings_growth_pct": output_b.get("stock_data", {}).get("earnings_growth_pct"),
            "rubric_score_100": _extract_rubric_score(output_b),
            "rubric_grade": (output_b.get("rubric", {}) or {}).get("grade"),
        },
    }

    sections = (
        "### Overview\n"
        "### Signal Comparison\n"
        "### Relative Strength and Quality Attribution\n"
        "### Risk and Drawdown Comparison\n"
        "### Scenario Matrix (Bull/Base/Bear with assumptions)\n"
        "### Allocation Framework (Core vs Satellite)\n"
        "### What Would Invalidate the Choice\n"
        "### Final Comparative Verdict"
        if deep
        else
        "### Overview\n"
        "### Signal Comparison\n"
        "### Relative Strength\n"
        "### Risk Comparison\n"
        "### Scenario Analysis (Bull/Base/Bear)\n"
        "### Capital Allocation Decision\n"
        "### Final Comparative Verdict"
    )

    prompt = f"""Compare two stocks and provide a clear decision report.

Original user comparison request:
- A: {query_a}
- B: {query_b}

Key metrics:
{json.dumps(metrics, indent=2)}

Stock A final report ({t1}):
{output_a.get('final_report', '')[-2200:] if deep else output_a.get('final_report', '')[-1400:]}

Stock B final report ({t2}):
{output_b.get('final_report', '')[-2200:] if deep else output_b.get('final_report', '')[-1400:]}

Write:
## Stock Comparison Report
{sections}

Rules:
- You must choose one outperformer (no tie).
- Base the choice on risk-adjusted return, not upside alone.
 - Use stock-level rubric score delta (quality proxy) as a tiebreaker when performance/risk looks close.
{"- Provide deeper attribution and explicit invalidation conditions for the winner." if deep else ""}

End with exactly these two lines:
OUTPERFORMER: {t1}|{t2}
CONFIDENCE: HIGH|MEDIUM|LOW
"""

    try:
        return _llm(
            prompt,
            max_tokens=1700 if deep else 1000,
            agent_tag="Comparator",
            system=(
                "You are a rigorous portfolio strategist. Provide deep, evidence-weighted comparative analysis with clear decision logic."
                if deep else
                "You are a practical equity comparison analyst."
            ),
        )
    except Exception:
        s1 = output_a.get("structured_output", {}) or {}
        s2 = output_b.get("structured_output", {}) or {}
        c1 = s1.get("conviction", "-")
        c2 = s2.get("conviction", "-")
        r1 = s1.get("risk", "-")
        r2 = s2.get("risk", "-")
        rub1 = _extract_rubric_score(output_a)
        rub2 = _extract_rubric_score(output_b)
        delta_text = "N/A" if rub1 is None or rub2 is None else str(rub1 - rub2)

        return (
            f"## Stock Comparison Report\n"
            f"### Overview\n"
            f"Comparative synthesis uses deterministic ranking from available structured signals.\n\n"
            f"### Signal Comparison\n"
            f"- {t1}: verdict={s1.get('verdict', '-')} conviction={c1} risk={r1}\n"
            f"- {t2}: verdict={s2.get('verdict', '-')} conviction={c2} risk={r2}\n\n"
            f"### Rubric Differential\n"
            f"- {t1}: rubric={rub1 if rub1 is not None else '-'}\n"
            f"- {t2}: rubric={rub2 if rub2 is not None else '-'}\n"
            f"- Delta ({t1} - {t2})={delta_text}\n\n"
            f"### Relative Strength and Quality Attribution\n"
            f"Deterministic rank uses rubric delta first (when available), then conviction, then lower risk.\n\n"
            f"### Risk and Drawdown Comparison\n"
            f"{t1} risk={r1}; {t2} risk={r2}. The lower risk tier receives preference when expected return profiles are comparable.\n\n"
            f"### Scenario Matrix (Bull/Base/Bear with assumptions)\n"
            f"Bull: stronger signal alignment and estimate revisions. Base: mixed execution with stable risk. Bear: thesis break under weaker growth/momentum.\n\n"
            f"### Allocation Framework (Core vs Satellite)\n"
            f"Allocate incrementally to the deterministic winner and keep the other as tactical/satellite exposure until signal quality improves.\n\n"
            f"### What Would Invalidate the Choice\n"
            f"A sustained drop in conviction or adverse risk-tier migration invalidates the current leader.\n\n"
            f"### Final Comparative Verdict\n"
            f"Relative winner selected from conviction profile and downside risk balance."
        )


def parse_comparison_outcome(report: str, output_a: dict, output_b: dict) -> tuple[str, str, dict]:
    t1 = output_a.get("ticker", "A")
    t2 = output_b.get("ticker", "B")

    winner = ""
    confidence = "MEDIUM"

    m_winner = re.search(r"OUTPERFORMER\s*:\s*([A-Z0-9.\-]+)", report or "", flags=re.IGNORECASE)
    if m_winner:
        winner = m_winner.group(1).strip().upper()

    m_conf = re.search(r"CONFIDENCE\s*:\s*(HIGH|MEDIUM|LOW)", report or "", flags=re.IGNORECASE)
    if m_conf:
        confidence = m_conf.group(1).strip().upper()

    det_winner, det_confidence, meta = _deterministic_comparison_choice(output_a, output_b)

    valid_winners = {str(t1).upper(), str(t2).upper()}
    if winner not in valid_winners:
        winner = det_winner
        confidence = det_confidence
        meta["winner_basis"] = meta.get("deterministic_basis", "deterministic")
    else:
        if not m_conf:
            confidence = det_confidence

        if str(winner).upper() == str(det_winner).upper():
            meta["winner_basis"] = "llm_with_deterministic_support"
        else:
            rubric_delta = meta.get("rubric_delta")
            if isinstance(rubric_delta, (int, float)) and abs(rubric_delta) >= 18 and meta.get("deterministic_basis") == "rubric_delta":
                winner = det_winner
                confidence = det_confidence
                meta["winner_basis"] = "rubric_delta_override"
            else:
                meta["winner_basis"] = "llm_primary"

    meta["winner"] = winner
    meta["confidence"] = confidence
    return winner, confidence, meta


def enforce_comparison_verdict_lines(report: str, winner: str, confidence: str) -> str:
    cleaned = re.sub(r"OUTPERFORMER\s*:\s*.*$", "", report or "", flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"CONFIDENCE\s*:\s*.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = cleaned.rstrip()
    return (
        cleaned
        + "\n\n"
        + f"OUTPERFORMER: {winner}\n"
        + f"CONFIDENCE: {confidence}"
    ).strip()


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
def run_pipeline(user_input: str,
                 save: bool = False,
                 mode: str = "quick") -> dict:
    """
    Execute the full 4-agent pipeline for one stock query.

    Returns:
        {
            "output":      dict,   ← all agent outputs combined
            "elapsed":     float,  ← total seconds
        }
    """
    start = time.time()

    mode = (mode or "quick").strip().lower()
    if mode not in {"quick", "deep"}:
        mode = "quick"

    pipeline_warnings: list[str] = []

    # ── Agent 1 ────────────────────────────────────────────────────────────
    step(1, "Market Data Research  [Yahoo Finance + Tavily(optional) + Groq]")
    try:
        a1 = agent1_market_research.run(user_input, mode=mode)
        ok(f"Ticker resolved → {a1['ticker']} ({a1['company']})  "
           f"[{a1['confidence']} confidence]")
        info(a1.get("reasoning", ""))
        if mode == "deep":
            info(
                "Deep context queries"
                + f" attempted={a1.get('context_queries_attempted', 0)}"
                + f" used={a1.get('context_queries_used', 0)}"
            )
        for warning in a1.get("context_warnings", []) or []:
            msg = f"Agent 1: {warning}"
            pipeline_warnings.append(msg)
            info(msg)
    except Exception as e:
        error(f"Agent 1 failed: {e}")
        raise

    # ── Agent 2 ────────────────────────────────────────────────────────────
    step(2, "Technical Analyst  [Yahoo Finance + Groq | Tavily optional]")
    try:
        a2 = agent2_technical_analyst.run(a1, mode=mode)
        ok("Technical analysis complete")
        if mode == "deep":
            info(
                "Technical context queries"
                + f" attempted={a2.get('technical_context_queries_attempted', 0)}"
                + f" used={a2.get('technical_context_queries_used', 0)}"
            )
        for warning in a2.get("technical_context_warnings", []) or []:
            msg = f"Agent 2: {warning}"
            pipeline_warnings.append(msg)
            info(msg)
    except Exception as e:
        error(f"Agent 2 failed: {e}")
        raise

    # ── Agent 3 ────────────────────────────────────────────────────────────
    step(3, "Fundamental Analyst  [Yahoo Finance + Tavily(optional) + Groq]")
    try:
        a3 = agent3_fundamental_analyst.run(a2, mode=mode)
        ok("Fundamental analysis complete")
        if mode == "deep":
            info(
                "Fundamental context queries"
                + f" attempted={a3.get('fundamental_context_queries_attempted', 0)}"
                + f" used={a3.get('fundamental_context_queries_used', 0)}"
            )
        for warning in a3.get("fundamental_context_warnings", []) or []:
            msg = f"Agent 3: {warning}"
            pipeline_warnings.append(msg)
            info(msg)
    except Exception as e:
        error(f"Agent 3 failed: {e}")
        raise

    # ── Agent 4 ────────────────────────────────────────────────────────────
    step(4, "Macro & Risk Specialist  [Tavily + Groq]")
    try:
        a4_macro = agent4_macro_risk_specialist.run(a3, mode=mode)
        ok("Macro & Risk analysis complete")
        if mode == "deep":
            info(
                "Macro context queries used"
                + f" = {a4_macro.get('macro_context_queries_used', 0)}"
            )
        for warning in a4_macro.get("macro_context_warnings", []) or []:
            msg = f"Agent 4: {warning}"
            pipeline_warnings.append(msg)
            info(msg)
    except Exception as e:
        error(f"Agent 4 failed: {e}")
        raise

    # ── Agent 5 ────────────────────────────────────────────────────────────
    step(5, f"Investment Advisor  [Groq model: {llm_client.MODEL}] [mode: {mode}]")
    try:
        try:
            pre_delay = float(os.environ.get("GROQ_PRE_AGENT5_DELAY_SECONDS", "0") or 0)
        except Exception:
            pre_delay = 0.0
        if pre_delay > 0:
            info(f"Waiting {pre_delay:.1f}s before Agent 5 to reduce rate-limit risk...")
            time.sleep(pre_delay)
        a5 = agent5_investment_advisor.run(a4_macro, mode=mode)
        signals = a5.get("signals", {})
        ok(f"Final report ready  |  Signals → trend={signals.get('trend')}  "
           f"tech={signals.get('signal')}  fund={signals.get('fund_view')}")
    except Exception as e:
        error(f"Agent 5 failed: {e}")
        raise

    elapsed = time.time() - start

    # ── Print final report ─────────────────────────────────────────────────
    banner(f"FINAL REPORT — {a5['ticker']} ({a5['company']})", GREEN)
    print(a5["final_report"])

    # ── Save ───────────────────────────────────────────────────────────────
    if save:
        path = save_report(a5)
        ok(f"Report saved → {path}")

    banner(f"Done in {elapsed:.1f}s", DIM)

    return {
        "output": a5,
        "elapsed": elapsed,
        "mode": mode,
        "degraded": bool(pipeline_warnings),
        "warnings": pipeline_warnings,
    }


def run_comparison_pipeline(query_a: str, query_b: str, save: bool = False, mode: str = "quick") -> dict:
    mode = (mode or "quick").strip().lower()
    if mode not in {"quick", "deep"}:
        mode = "quick"

    banner(f"Starting analysis for: \"{query_a}\"", CYAN)
    result_a = run_pipeline(user_input=query_a, save=False, mode=mode)

    banner(f"Starting analysis for: \"{query_b}\"", CYAN)
    result_b = run_pipeline(user_input=query_b, save=False, mode=mode)

    output_a = result_a["output"]
    output_b = result_b["output"]

    combined_warnings: list[str] = []
    for warning in result_a.get("warnings", []) or []:
        combined_warnings.append(f"{output_a.get('ticker', 'A')}: {warning}")
    for warning in result_b.get("warnings", []) or []:
        combined_warnings.append(f"{output_b.get('ticker', 'B')}: {warning}")

    banner(f"COMPARISON REPORT — {output_a.get('ticker')} vs {output_b.get('ticker')}", YELLOW)
    comparison_report = build_comparison_report(query_a, query_b, output_a, output_b, mode=mode)
    winner, confidence, comparison_meta = parse_comparison_outcome(comparison_report, output_a, output_b)
    comparison_report = enforce_comparison_verdict_lines(comparison_report, winner, confidence)
    print(comparison_report)
    ok(
        f"Comparison winner → {winner}  [confidence: {confidence}]"
        + (f"  [basis: {comparison_meta.get('winner_basis')}]" if comparison_meta.get("winner_basis") else "")
    )

    if save:
        path = save_comparison_report(output_a, output_b, comparison_report)
        ok(f"Comparison report saved → {path}")

    return {
        "stock_a": output_a,
        "stock_b": output_b,
        "stock_a_degraded": bool(result_a.get("degraded", False)),
        "stock_b_degraded": bool(result_b.get("degraded", False)),
        "comparison_report": comparison_report,
        "winner": winner,
        "confidence": confidence,
        "comparison_meta": comparison_meta,
        "winner_basis": comparison_meta.get("winner_basis"),
        "rubric_delta": comparison_meta.get("rubric_delta"),
        "elapsed_total": result_a.get("elapsed", 0.0) + result_b.get("elapsed", 0.0),
        "mode": mode,
        "degraded": bool(result_a.get("degraded", False) or result_b.get("degraded", False)),
        "warnings": combined_warnings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-agent stock analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py
  python run.py "apple"
    python run.py "TSLA" --save
    python run.py "asian paints" "mrf"
    python run.py "compare asian paints and mrf"
        """,
    )
    parser.add_argument(
                "query",
                nargs="*",
                help="One stock query, or two stock queries for comparison",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the full report to ./reports/<TICKER>_<timestamp>.md",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Dump complete pipeline output as JSON to stdout at the end",
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "deep"],
        default="quick",
        help="Synthesis depth: quick (single-pass) or deep (multi-pass critique/revision).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Check API keys
    if not check_env():
        sys.exit(1)

    # Get user input
    raw_queries = args.query or []
    if not raw_queries:
        banner("Stock Market Analysis Agent — Multi-Agent Pipeline")
        print("Enter one stock query, or ask to compare two stocks.")
        print("Examples: 'apple', 'TSLA', 'compare asian paints and mrf'")
        print()
        entered = input("  Your input: ").strip()
        if not entered:
            error("No input provided. Exiting.")
            sys.exit(1)
        raw_queries = [entered]

    mode, detected_queries = detect_single_vs_multi_stock(raw_queries)

    if mode == "multi":
        q1, q2 = detected_queries
        banner(f"Comparison mode detected: \"{q1}\" vs \"{q2}\"", CYAN)
        result = run_comparison_pipeline(q1, q2, save=args.save, mode=args.mode)
        if args.json:
            safe: dict[str, object] = {
                "stock_a": {k: v for k, v in result["stock_a"].items() if isinstance(v, (str, dict, list, int, float, bool, type(None)))},
                "stock_b": {k: v for k, v in result["stock_b"].items() if isinstance(v, (str, dict, list, int, float, bool, type(None)))},
                "comparison_report": result["comparison_report"],
                "winner": result["winner"],
                "confidence": result["confidence"],
                "elapsed_total": result["elapsed_total"],
            }
            print(json.dumps(safe, indent=2, ensure_ascii=False))
        return

    user_input = detected_queries[0].strip()
    banner(f"Starting analysis for: \"{user_input}\"")
    result = run_pipeline(user_input=user_input, save=args.save, mode=args.mode)

    if args.json:
        safe = {k: v for k, v in result["output"].items() if isinstance(v, (str, dict, list, int, float, bool, type(None)))}
        print(json.dumps(safe, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
