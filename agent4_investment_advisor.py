"""
Agent 4 - Investment Advisor (Synthesis Agent)
Combines previous agent outputs into the final decision report.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import json
import logging
import re
from typing import Any

from llm_client import _llm
from agent4_utils import (
    StructuredDecision,
    apply_rule_overrides,
    compute_rule_decision,
    derive_position_size,
    enforce_consistency,
    extract_first_json_object,
    parse_signals as parse_signals_robust,
    parse_structured_decision,
    remove_decision_json_block,
    summarize_for_context,
    validate_stock_data,
)

TAG = "Agent 4"

logger = logging.getLogger(TAG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

RUBRIC_CRITERIA: dict[str, str] = {
    "trend_relevance": "Trend Relevance",
    "sector_trend_fit": "Sector-Trend Fit",
    "visual_text_alignment": "Visual-Text Alignment",
    "quote_quality": "Quote Quality",
    "report_completeness": "Report Completeness",
}

QUICK_REQUIRED_SECTIONS = [
    "Executive Summary",
    "Final Recommendation",
    "12-Month Scenario",
    "Top 3 Risks",
    "Position Sizing",
    "Caveats",
]

DEEP_REQUIRED_SECTIONS = [
    "Executive Summary",
    "Signal Decomposition",
    "Data Snapshot",
    "Evidence Ledger",
    "12-Month Scenario Matrix",
    "Risk Register and Mitigants",
    "Position Sizing and Risk Controls",
    "Monitoring Checklist",
    "Final Recommendation",
]


def _extract(pattern: str, text: str, default: str = "N/A") -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else default


def parse_signals(outputs: dict) -> dict:
    parsed = parse_signals_impl(outputs)
    return {
        "trend": parsed.trend,
        "signal": parsed.technical_signal,
        "confidence": parsed.technical_confidence,
        "fund_view": parsed.fundamental_view,
        "horizon": parsed.horizon,
        "warnings": parsed.warnings,
    }


def parse_signals_impl(outputs: dict[str, Any]):
    return parse_signals_robust(outputs)


def _extract_evidence_lines(text: str, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^[-*•\s]+", "", line).strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(("trend:", "signal:", "confidence:", "fundamental view:", "horizon:")):
            continue
        if len(line) < 18:
            continue
        lines.append(line[:220])
        if len(lines) >= limit:
            break
    return lines


def _bullet_block(lines: list[str], fallback: str) -> str:
    if not lines:
        return f"- {fallback}"
    return "\n".join(f"- {line}" for line in lines)


def _clamp_score(value: Any, low: int = 1, high: int = 5) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        return low
    return max(low, min(high, n))


def _grade_from_normalized(score_100: int) -> str:
    if score_100 >= 90:
        return "A"
    if score_100 >= 80:
        return "B"
    if score_100 >= 70:
        return "C"
    if score_100 >= 60:
        return "D"
    return "E"


def _normalize_rubric_payload(raw: dict[str, Any], source: str) -> dict[str, Any]:
    container = raw.get("criteria") if isinstance(raw.get("criteria"), dict) else raw
    criteria_out: dict[str, dict[str, Any]] = {}

    for key, label in RUBRIC_CRITERIA.items():
        item = container.get(key, {}) if isinstance(container, dict) else {}
        if isinstance(item, dict):
            score = _clamp_score(item.get("score", 1))
            note = str(item.get("note", "")).strip()
        else:
            score = _clamp_score(item)
            note = ""

        criteria_out[key] = {
            "label": label,
            "score": score,
            "note": note,
        }

    total = sum(x["score"] for x in criteria_out.values())
    normalized = int(round((total / (len(RUBRIC_CRITERIA) * 5)) * 100))

    improvements_raw = raw.get("top_improvements", []) if isinstance(raw, dict) else []
    improvements: list[str] = []
    if isinstance(improvements_raw, list):
        improvements = [str(x).strip() for x in improvements_raw if str(x).strip()]

    if not improvements:
        low = sorted(criteria_out.items(), key=lambda kv: kv[1]["score"])
        for key, item in low[:2]:
            if item["score"] < 4:
                improvements.append(f"Improve {RUBRIC_CRITERIA[key]} with clearer evidence and stronger coherence.")

    return {
        "source": source,
        "criteria": criteria_out,
        "total_score": total,
        "normalized_score": normalized,
        "grade": _grade_from_normalized(normalized),
        "top_improvements": improvements,
    }


def _deterministic_rubric_scores(
    report_text: str,
    decision: StructuredDecision,
    signals: dict[str, Any],
    stock_data: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    text = (report_text or "")
    lower = text.lower()

    trend = str(signals.get("trend", "UNKNOWN") or "UNKNOWN").upper()
    trend_score = 2
    trend_note = "Trend signal availability is limited."
    if trend in {"BULLISH", "BEARISH", "NEUTRAL"}:
        trend_score = 4
        trend_note = f"Detected trend is {trend} and was incorporated in synthesis."
        if "trend" in lower:
            trend_score = 5

    sector = str(stock_data.get("sector") or "").strip()
    industry = str(stock_data.get("industry") or "").strip()
    sector_score = 2
    sector_note = "Sector/industry linkage in thesis is limited."
    if sector or industry:
        sector_score = 3
        sector_note = "Sector or industry context is present in the data inputs."
        if (sector and sector.lower() in lower) or (industry and industry.lower() in lower):
            sector_score = 4
            sector_note = "Report narrative references sector/industry context explicitly."
        if "signal decomposition" in lower or "valuation" in lower:
            sector_score = min(5, sector_score + 1)

    alignment_checks = 0
    if str(decision.verdict).upper() in lower:
        alignment_checks += 1
    if str(decision.risk).upper() in lower:
        alignment_checks += 1
    if "conviction" in lower:
        alignment_checks += 1
    if "position" in lower or str(decision.position_size_pct) in text:
        alignment_checks += 1
    visual_score = max(1, min(5, alignment_checks + 1))
    visual_note = "Narrative and structured decision fields show moderate consistency."
    if visual_score >= 4:
        visual_note = "Narrative and structured decision fields are strongly aligned."

    metric_refs = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))
    quote_score = 1
    if metric_refs >= 16:
        quote_score = 5
    elif metric_refs >= 10:
        quote_score = 4
    elif metric_refs >= 6:
        quote_score = 3
    elif metric_refs >= 3:
        quote_score = 2
    quote_note = f"Found {metric_refs} numeric references in the report."

    required = DEEP_REQUIRED_SECTIONS if mode == "deep" else QUICK_REQUIRED_SECTIONS
    present = sum(1 for s in required if s.lower() in lower)
    completeness_ratio = present / max(1, len(required))
    if completeness_ratio >= 0.95:
        completeness_score = 5
    elif completeness_ratio >= 0.75:
        completeness_score = 4
    elif completeness_ratio >= 0.55:
        completeness_score = 3
    elif completeness_ratio >= 0.35:
        completeness_score = 2
    else:
        completeness_score = 1
    completeness_note = f"Detected {present}/{len(required)} expected sections for {mode} mode."

    raw = {
        "trend_relevance": {"score": trend_score, "note": trend_note},
        "sector_trend_fit": {"score": sector_score, "note": sector_note},
        "visual_text_alignment": {"score": visual_score, "note": visual_note},
        "quote_quality": {"score": quote_score, "note": quote_note},
        "report_completeness": {"score": completeness_score, "note": completeness_note},
    }
    return _normalize_rubric_payload(raw, source="deterministic")


def _build_rubric_critique_prompt(
    report_text: str,
    decision_json: dict[str, Any],
    signals: dict[str, Any],
    stock_data: dict[str, Any],
) -> str:
    core = {
        "price": stock_data.get("price"),
        "trailing_pe": stock_data.get("trailing_pe"),
        "revenue_growth_pct": stock_data.get("revenue_growth_pct"),
        "earnings_growth_pct": stock_data.get("earnings_growth_pct"),
        "sector": stock_data.get("sector"),
        "industry": stock_data.get("industry"),
    }

    return f"""You are a strict LLM-as-Judge for equity research quality.

Evaluate this report using a 1-5 rubric per criterion.

REPORT:
{report_text}

DECISION_JSON:
{json.dumps(decision_json, indent=2)}

SIGNALS:
{json.dumps(signals, indent=2)}

CORE METRICS:
{json.dumps(core, indent=2)}

Rubric criteria:
1) Trend Relevance: Is trend assessment timely, specific, and grounded in data?
2) Sector-Trend Fit: Does the thesis clearly connect company/sector dynamics to trend context?
3) Visual-Text Alignment: Do narrative claims align with decision fields (verdict, conviction, risk, size)?
4) Quote Quality: Are supporting claims concise, specific, and backed by concrete metrics?
5) Report Completeness: Are all required sections present and professional?

Return ONLY strict JSON after marker:
RUBRIC_JSON:
{{
  "trend_relevance": {{"score": 1, "note": ""}},
  "sector_trend_fit": {{"score": 1, "note": ""}},
  "visual_text_alignment": {{"score": 1, "note": ""}},
  "quote_quality": {{"score": 1, "note": ""}},
  "report_completeness": {{"score": 1, "note": ""}},
  "top_improvements": ["", ""]
}}"""


def _judge_rubric_scores(
    report_text: str,
    decision: StructuredDecision,
    signals: dict[str, Any],
    stock_data: dict[str, Any],
    mode: str,
    use_llm: bool,
) -> tuple[dict[str, Any], str]:
    baseline = _deterministic_rubric_scores(report_text, decision, signals, stock_data, mode)
    critique_text = ""

    if not use_llm or mode != "deep":
        return baseline, critique_text

    try:
        rubric_prompt = _build_rubric_critique_prompt(report_text, decision.to_dict(), signals, stock_data)
        critique_text = _llm(
            rubric_prompt,
            max_tokens=900,
            agent_tag=f"{TAG}-Judge",
            system="Score strictly by rubric and return clean JSON.",
        )
        raw = extract_first_json_object(critique_text, marker="RUBRIC_JSON")
        if isinstance(raw, dict) and raw:
            return _normalize_rubric_payload(raw, source="llm_judge"), critique_text
    except Exception:
        logger.warning("Rubric judge unavailable; using deterministic rubric fallback.")

    return baseline, critique_text


def _build_pass1_prompt(
    ticker: str,
    company: str,
    stock_data: dict[str, Any],
    market_report: str,
    technical_report: str,
    fundamental_report: str,
    signals: dict[str, Any],
    stock_warnings: list[str],
    signal_warnings: list[str],
    rule_messages: list[str],
    mode: str = "quick",
) -> str:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    core = {
        "price": stock_data.get("price"),
        "currency": stock_data.get("currency"),
        "market_cap": stock_data.get("market_cap"),
        "beta": stock_data.get("beta"),
        "volatility_annual_pct": stock_data.get("volatility_annual_pct"),
        "trailing_pe": stock_data.get("trailing_pe"),
        "revenue_growth_pct": stock_data.get("revenue_growth_pct"),
        "earnings_growth_pct": stock_data.get("earnings_growth_pct"),
    }

    constraints = {
        "hard_rule": "If technical signal is SELL with HIGH confidence, BUY is forbidden.",
        "signal_conflict_rule": "If signals conflict, conviction must be downgraded.",
        "alignment_rule": "If all signals align, conviction may be increased.",
    }

    sections = (
        "## Executive Summary\n"
        "## Investment Variant Perception\n"
        "## Signal Decomposition (Market vs Technical vs Fundamental)\n"
        "## Valuation and Return Driver Framework\n"
        "## 12-Month Scenario Matrix (Bull/Base/Bear with assumptions and probability)\n"
        "## Risk Register with Mitigants\n"
        "## Position Sizing and Risk Controls\n"
        "## Monitoring Checklist (30/90/180 days)\n"
        "## Caveats\n"
        "## Disclaimer"
        if deep
        else
        "## Executive Summary\n"
        "## Final Recommendation\n"
        "## 12-Month Scenario Targets (Bull/Base/Bear)\n"
        "## Top 3 Risks\n"
        "## Position Sizing\n"
        "## Catalysts to Watch\n"
        "## Caveats\n"
        "## Disclaimer"
    )

    depth_guidance = (
        "Deep mode requirements: provide detailed reasoning with explicit evidence hierarchy, include at least one concrete number per major section, and clearly state what would invalidate the thesis. Also target strong rubric performance on Trend Relevance, Sector-Trend Fit, Visual-Text Alignment, Quote Quality, and Report Completeness."
        if deep else
        "Keep the analysis practical and concise."
    )

    context_window = 3600 if deep else 2200

    return f"""You are an investment advisor writing a final stock recommendation.

Stock: {ticker} ({company})

Key stock metrics (Yahoo):
{json.dumps(core, indent=2)}

Extracted normalized signals:
{json.dumps(signals, indent=2)}

Validation warnings:
{json.dumps(stock_warnings + signal_warnings, indent=2)}

Deterministic guardrail rules (must obey):
{json.dumps(constraints, indent=2)}
Rule notes:
{json.dumps(rule_messages, indent=2)}

Market report context:
{summarize_for_context(market_report, max_chars=context_window)}

Technical report context:
{summarize_for_context(technical_report, max_chars=context_window)}

Fundamental report context:
{summarize_for_context(fundamental_report, max_chars=context_window)}

Write a robust report with these sections:
# Equity Research - {ticker} ({company})
{sections}

{depth_guidance}

After the human-readable report, append exactly:
DECISION_JSON:
{{
  "verdict": "BUY|HOLD|SELL",
  "conviction": 1,
  "risk": "LOW|MEDIUM|HIGH",
  "position_size_pct": 1.0,
  "time_horizon": "SHORT|MEDIUM|LONG"
}}

Use realistic values. Do not skip DECISION_JSON."""


def _build_critique_prompt(pass1_report: str, mode: str = "quick") -> str:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    critique_sections = (
        "1) Contradictions\n"
        "2) Weak assumptions\n"
        "3) Missing risk considerations\n"
        "4) Evidence quality gaps\n"
        "5) Scenario design flaws\n"
        "6) Position sizing / risk-control mismatch\n"
        "7) Missing disconfirming evidence\n"
        "8) Specific revision actions"
        if deep
        else
        "1) Contradictions\n"
        "2) Weak assumptions\n"
        "3) Missing risk considerations\n"
        "4) Decision quality issues (verdict/conviction/risk/position mismatch)\n"
        "5) Specific revision actions"
    )

    return f"""Critique this investment report for flaws, contradictions, and weak assumptions.

REPORT:
{pass1_report}

Output a strict critique with sections:
{critique_sections}

{"Be specific, hard-nosed, and evidence-oriented." if deep else "Be specific and concise."}"""


def _build_revision_prompt(
    ticker: str,
    company: str,
    pass1_report: str,
    critique: str,
    rubric_critique: str,
    signals: dict[str, Any],
    rule_messages: list[str],
    mode: str = "quick",
) -> str:
    mode = (mode or "quick").strip().lower()
    deep = mode == "deep"

    deep_requirements = (
        "Revision requirements for deep mode:\n"
        "- Strengthen evidence traceability: each major claim should tie to a metric or extracted signal.\n"
        "- Explicitly include disconfirming evidence and what would invalidate the recommendation.\n"
        "- Expand scenario analysis with assumptions and relative likelihood.\n"
        "- Ensure risk controls and position sizing are internally consistent with conviction and risk tier.\n"
        "- Address rubric weaknesses: Trend Relevance, Sector-Trend Fit, Visual-Text Alignment, Quote Quality, and Report Completeness."
        if deep else
        ""
    )

    rubric_block = ""
    if deep and rubric_critique:
        rubric_block = f"\nRUBRIC CRITIQUE:\n{rubric_critique}\n"

    return f"""Revise the report using the critique below while obeying deterministic rules.

Stock: {ticker} ({company})

Signals:
{json.dumps(signals, indent=2)}

Deterministic rule notes:
{json.dumps(rule_messages, indent=2)}

INITIAL REPORT:
{pass1_report}

CRITIQUE:
{critique}

{rubric_block}

Produce an improved final report with the same sections and append:
DECISION_JSON:
{{
  "verdict": "BUY|HOLD|SELL",
  "conviction": 1,
  "risk": "LOW|MEDIUM|HIGH",
  "position_size_pct": 1.0,
  "time_horizon": "SHORT|MEDIUM|LONG"
}}

Ensure DECISION_JSON matches the report narrative.

{deep_requirements}"""


def _clean_report_and_decision(revised_report: str) -> tuple[str, dict[str, Any]]:
    decision_json = extract_first_json_object(revised_report, marker="DECISION_JSON")
    human_report = remove_decision_json_block(revised_report, marker="DECISION_JSON")
    return human_report.strip(), decision_json


def _ensure_final_verdict_line(report_text: str, decision: StructuredDecision) -> str:
    cleaned = re.sub(r"FINAL\s+VERDICT\s*:\s*.*$", "", report_text, flags=re.IGNORECASE | re.MULTILINE).rstrip()
    final_line = (
        f"FINAL VERDICT: {decision.verdict} | "
        f"CONVICTION: {decision.conviction}/10 | "
        f"RISK: {decision.risk}"
    )
    return (cleaned + "\n\n" + final_line).strip()


def synthesize_report(ticker: str, company: str, stock_data: dict,
                      market_report: str, technical_report: str,
                      fundamental_report: str, signals: dict,
                      mode: str = "quick") -> dict[str, Any]:
    parsed = parse_signals_impl(
        {
            "market_report": market_report,
            "technical_report": technical_report,
            "fundamental_report": fundamental_report,
        }
    )
    signal_map = {
        "trend": parsed.trend,
        "signal": parsed.technical_signal,
        "confidence": parsed.technical_confidence,
        "fund_view": parsed.fundamental_view,
        "horizon": parsed.horizon,
    }

    stock_errors, stock_warnings = validate_stock_data(stock_data)
    if stock_errors:
        raise ValueError("; ".join(stock_errors))

    rules = compute_rule_decision(parsed, stock_data)

    logger.info("Extracted signals: %s", signal_map)
    if parsed.warnings:
        logger.warning("Signal warnings: %s", parsed.warnings)
    if stock_warnings:
        logger.warning("Stock data warnings: %s", stock_warnings)
    logger.info("Rule decisions: %s", rules.to_dict())

    mode = (mode or "quick").strip().lower()
    if mode not in {"quick", "deep"}:
        mode = "quick"

    rubric_critique = ""

    try:
        pass1_prompt = _build_pass1_prompt(
            ticker=ticker,
            company=company,
            stock_data=stock_data,
            market_report=market_report,
            technical_report=technical_report,
            fundamental_report=fundamental_report,
            signals=signal_map,
            stock_warnings=stock_warnings,
            signal_warnings=parsed.warnings,
            rule_messages=rules.messages,
            mode=mode,
        )

        if mode == "quick":
            critique = "Quick mode: single-pass synthesis used."
            revised_report = _llm(pass1_prompt, max_tokens=850, agent_tag=TAG, system="Be concise, clear, and practical.")
        else:
            pass1_report = _llm(
                pass1_prompt,
                max_tokens=1900,
                agent_tag=TAG,
                system="You are a rigorous buy-side strategist. Prioritize depth, evidence weighting, and internally consistent risk logic.",
            )
            _, pass1_decision_json = _clean_report_and_decision(pass1_report)

            critique_prompt = _build_critique_prompt(pass1_report, mode=mode)
            critique = _llm(
                critique_prompt,
                max_tokens=1000,
                agent_tag=TAG,
                system="You are an unforgiving investment committee reviewer.",
            )

            rubric_prompt = _build_rubric_critique_prompt(pass1_report, pass1_decision_json, signal_map, stock_data)
            rubric_critique = _llm(
                rubric_prompt,
                max_tokens=900,
                agent_tag=f"{TAG}-Judge",
                system="Audit by rubric and return concise JSON.",
            )

            revision_prompt = _build_revision_prompt(
                ticker=ticker,
                company=company,
                pass1_report=pass1_report,
                critique=critique,
                rubric_critique=rubric_critique,
                signals=signal_map,
                rule_messages=rules.messages,
                mode=mode,
            )
            revised_report = _llm(
                revision_prompt,
                max_tokens=2100,
                agent_tag=TAG,
                system="Revise for institutional-quality depth, consistency, and decision robustness.",
            )

        human_report, decision_json = _clean_report_and_decision(revised_report)
        decision = parse_structured_decision(decision_json, human_report)

        decision, rule_overrides = apply_rule_overrides(decision, rules)
        decision, consistency_notes = enforce_consistency(decision, stock_data)

        override_notes = rule_overrides + consistency_notes
        if override_notes:
            logger.warning("Governance overrides: %s", override_notes)
            human_report = (
                human_report.strip()
                + "\n\n## Governance Checks Applied\n"
                + "\n".join(f"- {note}" for note in override_notes)
            )

        final_report = _ensure_final_verdict_line(human_report, decision)
        rubric_scores, rubric_judge_output = _judge_rubric_scores(
            report_text=final_report,
            decision=decision,
            signals=signal_map,
            stock_data=stock_data,
            mode=mode,
            use_llm=(mode == "deep"),
        )
        if not rubric_critique and rubric_judge_output:
            rubric_critique = rubric_judge_output

        payload: dict[str, Any] = {
            "report": final_report,
            "structured_output": decision.to_dict(),
            "critique": critique,
            "rubric_critique": rubric_critique,
            "rubric": rubric_scores,
            "mode": mode,
            "signal_warnings": parsed.warnings,
            "stock_warnings": stock_warnings,
            "rule_messages": rules.messages,
            "override_notes": override_notes,
            "signals": signal_map,
        }
        return payload
    except Exception:
        logger.warning("LLM synthesis unavailable; using deterministic fallback.")

        market_vote = {
            "BULLISH": "BUY",
            "BEARISH": "SELL",
            "NEUTRAL": "HOLD",
            "UNKNOWN": "HOLD",
        }.get(parsed.trend, "HOLD")
        votes = [market_vote, parsed.technical_signal, parsed.fundamental_view]
        valid_votes = [v for v in votes if v in {"BUY", "HOLD", "SELL"}]

        if not valid_votes:
            base_verdict = "HOLD"
        else:
            counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
            for v in valid_votes:
                counts[v] += 1
            ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            base_verdict = ranked[0][0] if ranked[0][1] > ranked[1][1] else "HOLD"

        conviction = 6
        conviction += 1 if parsed.technical_confidence == "HIGH" else 0
        conviction -= 1 if parsed.technical_confidence == "LOW" else 0
        conviction += 1 if rules.all_aligned else 0
        conviction -= 2 if rules.conflict_detected else 0
        conviction = max(1, min(10, conviction))

        base_decision = StructuredDecision(
            verdict=base_verdict,
            conviction=conviction,
            risk=rules.risk_floor,
            position_size_pct=derive_position_size(conviction, rules.risk_floor),
            time_horizon=parsed.horizon,
        )

        decision, rule_overrides = apply_rule_overrides(base_decision, rules)
        decision, consistency_notes = enforce_consistency(decision, stock_data)
        override_notes = rule_overrides + consistency_notes

        market_evidence = _bullet_block(
            _extract_evidence_lines(market_report, limit=5 if mode == "deep" else 3),
            "Market context was limited; trend uses price/MA/RSI structure.",
        )
        technical_evidence = _bullet_block(
            _extract_evidence_lines(technical_report, limit=5 if mode == "deep" else 3),
            "Technical context was limited; signal relies on MA/RSI/MACD confluence.",
        )
        fundamental_evidence = _bullet_block(
            _extract_evidence_lines(fundamental_report, limit=5 if mode == "deep" else 3),
            "Fundamental context was limited; view relies on valuation-growth-balance-sheet blend.",
        )

        if mode == "deep":
            final_report = f"""# Equity Research - {ticker} ({company})

## Executive Summary
This deep-mode report uses deterministic multi-signal synthesis across market trend, technical structure, and fundamental quality with governance constraints applied to verdict, conviction, and position sizing.

## Signal Decomposition
- Market trend: {parsed.trend}
- Technical signal: {parsed.technical_signal} ({parsed.technical_confidence})
- Fundamental view: {parsed.fundamental_view}
- Horizon bias: {parsed.horizon}
- Rule conflict detected: {'Yes' if rules.conflict_detected else 'No'}
- Cross-signal alignment: {'Yes' if rules.all_aligned else 'No'}

## Data Snapshot
- Price: {stock_data.get('price')} {stock_data.get('currency')}
- MA50 / MA200: {stock_data.get('ma50')} / {stock_data.get('ma200')}
- RSI14: {stock_data.get('rsi14')}
- Trailing PE: {stock_data.get('trailing_pe')}
- Revenue growth %: {stock_data.get('revenue_growth_pct')}
- Earnings growth %: {stock_data.get('earnings_growth_pct')}
- Debt/Equity: {stock_data.get('debt_to_equity')}
- Profit margin %: {stock_data.get('profit_margin_pct')}

## Evidence Ledger
### Market Evidence
{market_evidence}

### Technical Evidence
{technical_evidence}

### Fundamental Evidence
{fundamental_evidence}

## 12-Month Scenario Matrix
- Bull case: trend strengthens with earnings delivery and risk-premium compression; upside concentration is higher but requires confirmation from participation and guidance quality.
- Base case: mixed macro and company execution keep valuation near current band; returns are moderate and depend on earnings consistency.
- Bear case: growth disappointment or macro risk-off reprices valuation; downside expands when technical structure weakens alongside negative revisions.

## Risk Register and Mitigants
- Macro and liquidity shocks: size position conservatively and avoid over-concentration in correlated risk factors.
- Earnings miss / guidance cut: reduce exposure on failed post-result price response and declining participation.
- Valuation rerating: require margin of safety when growth momentum decelerates versus expectations.

## Position Sizing and Risk Controls
Suggested allocation: {decision.position_size_pct}%
Risk tier: {decision.risk}
Execution controls: staged entry, pre-defined invalidation levels, and re-evaluation on material news.

## Monitoring Checklist (30/90/180 Days)
- 30 days: confirm trend persistence, participation quality, and estimate revisions.
- 90 days: evaluate earnings delivery versus guidance and margin trajectory.
- 180 days: reassess thesis durability, valuation regime, and capital allocation efficiency.

## Final Recommendation
Verdict: {decision.verdict}
Conviction: {decision.conviction}/10
Risk: {decision.risk}
Time Horizon: {decision.time_horizon}

## Caveats
- This deep-mode deterministic synthesis is data-driven but not a substitute for primary filings and management commentary.
- Reassess promptly on major macro, policy, or company-specific events.

## Disclaimer
This is not financial advice.
"""
        else:
            final_report = f"""# Equity Research - {ticker} ({company})
## Executive Summary
This report uses deterministic signal aggregation across market, technical, and fundamental signals.

## Final Recommendation
Verdict: {decision.verdict}
Conviction: {decision.conviction}/10
Risk: {decision.risk}
Time Horizon: {decision.time_horizon}

## 12-Month Scenario Targets (Bull/Base/Bear)
Bull: +20% | Base: +8% | Bear: -12%

## Top 3 Risks
- Macro and sector volatility
- Earnings disappointment risk
- Valuation rerating risk

## Position Sizing
Suggested allocation: {decision.position_size_pct}%

## Catalysts to Watch
- Quarterly earnings and guidance
- Sector demand trends
- Margin and cash-flow trends

## Caveats
- Confidence is calibrated conservatively when signals disagree.
- Reassess after material news or earnings updates.

## Disclaimer
This is not financial advice.
"""

        if override_notes:
            final_report = (
                final_report.strip()
                + "\n\n## Governance Checks Applied\n"
                + "\n".join(f"- {note}" for note in override_notes)
            )

        final_report = _ensure_final_verdict_line(final_report, decision)
        rubric_scores = _deterministic_rubric_scores(
            report_text=final_report,
            decision=decision,
            signals=signal_map,
            stock_data=stock_data,
            mode=mode,
        )

        return {
            "report": final_report,
            "structured_output": decision.to_dict(),
            "critique": "Deterministic synthesis applied.",
            "rubric_critique": "Deterministic rubric applied.",
            "rubric": rubric_scores,
            "mode": mode,
            "signal_warnings": parsed.warnings,
            "stock_warnings": stock_warnings,
            "rule_messages": rules.messages,
            "override_notes": override_notes,
            "signals": signal_map,
        }


def run(agent3_output: dict, mode: str = "quick") -> dict:
    ticker = agent3_output["ticker"]
    company = agent3_output["company"]
    stock_data = agent3_output.get("stock_data", {})

    market_report = agent3_output.get("market_report", "")
    technical_report = agent3_output.get("technical_report", "")
    fundamental_report = agent3_output.get("fundamental_report", "")

    parsed = parse_signals_impl(agent3_output)
    signals = {
        "trend": parsed.trend,
        "signal": parsed.technical_signal,
        "confidence": parsed.technical_confidence,
        "fund_view": parsed.fundamental_view,
        "horizon": parsed.horizon,
        "warnings": parsed.warnings,
    }
    print(f"\n[Agent 4] Building final investment report for {ticker}...")

    payload = synthesize_report(
        ticker=ticker,
        company=company,
        stock_data=stock_data,
        market_report=market_report,
        technical_report=technical_report,
        fundamental_report=fundamental_report,
        signals=signals,
        mode=mode,
    )

    parsed_payload = payload if isinstance(payload, dict) else extract_first_json_object(str(payload))
    final_report = parsed_payload.get("report", "")
    structured_output = parsed_payload.get("structured_output", {})

    return {
        **agent3_output,
        "mode": parsed_payload.get("mode", mode),
        "signals": signals,
        "agent4_critique": parsed_payload.get("critique", ""),
        "agent4_rubric_critique": parsed_payload.get("rubric_critique", ""),
        "rubric": parsed_payload.get("rubric", {}),
        "agent4_warnings": {
            "signal_warnings": parsed_payload.get("signal_warnings", []),
            "stock_warnings": parsed_payload.get("stock_warnings", []),
            "rule_messages": parsed_payload.get("rule_messages", []),
            "override_notes": parsed_payload.get("override_notes", []),
        },
        "structured_output": structured_output,
        "final_report": final_report,
    }


if __name__ == "__main__":
    stub = {
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "stock_data": {"price": 180, "trailing_pe": 30},
        "market_report": "TREND: BULLISH",
        "technical_report": "SIGNAL: HOLD\nCONFIDENCE: MEDIUM",
        "fundamental_report": "FUNDAMENTAL VIEW: BUY\nHORIZON: LONG",
    }
    out = run(stub)
    print("\n" + "=" * 60)
    print(out["final_report"])
