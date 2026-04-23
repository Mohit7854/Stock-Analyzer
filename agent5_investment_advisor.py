"""
Agent 5 - Investment Advisor (Synthesis Agent)
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
from agent5_utils import (
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

TAG = "Agent 5"

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

RUBRIC_BAND_GUIDANCE = {
    5: "excellent evidence quality, coherence, and coverage",
    4: "strong but with minor gaps",
    3: "adequate with visible weaknesses",
    2: "weak and under-supported",
    1: "materially deficient",
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


def _to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out


def _market_regime_snapshot(signals: dict[str, Any], stock_data: dict[str, Any]) -> dict[str, Any]:
    trend = str(signals.get("trend", "UNKNOWN") or "UNKNOWN").upper()
    technical = str(signals.get("signal", "UNKNOWN") or "UNKNOWN").upper()
    fundamental = str(signals.get("fund_view", "UNKNOWN") or "UNKNOWN").upper()

    price = _to_float(stock_data.get("price"))
    ma50 = _to_float(stock_data.get("ma50"))
    ma200 = _to_float(stock_data.get("ma200"))
    rsi = _to_float(stock_data.get("rsi14"))

    structure = "mixed"
    if price is not None and ma50 is not None and ma200 is not None:
        if price >= ma50 >= ma200:
            structure = "bullish"
        elif price <= ma50 <= ma200:
            structure = "bearish"

    bearish_pressure = 0
    if trend == "BEARISH":
        bearish_pressure += 1
    if technical == "SELL":
        bearish_pressure += 1
    if fundamental == "SELL":
        bearish_pressure += 1
    if structure == "bearish":
        bearish_pressure += 1
    if rsi is not None and rsi <= 45:
        bearish_pressure += 1

    return {
        "trend": trend,
        "technical": technical,
        "fundamental": fundamental,
        "price": price,
        "ma50": ma50,
        "ma200": ma200,
        "rsi": rsi,
        "structure": structure,
        "bearish_pressure": bearish_pressure,
    }


def _apply_bearish_guardrails(
    decision: StructuredDecision,
    signals: dict[str, Any],
    stock_data: dict[str, Any],
) -> tuple[StructuredDecision, list[str]]:
    snap = _market_regime_snapshot(signals, stock_data)
    pressure = int(snap.get("bearish_pressure", 0) or 0)
    trend = str(snap.get("trend", "UNKNOWN") or "UNKNOWN")
    technical = str(snap.get("technical", "UNKNOWN") or "UNKNOWN")
    fundamental = str(snap.get("fundamental", "UNKNOWN") or "UNKNOWN")
    structure = str(snap.get("structure", "mixed") or "mixed")

    bullish_confirmation = 0
    if trend == "BULLISH":
        bullish_confirmation += 1
    if technical == "BUY":
        bullish_confirmation += 1
    if fundamental == "BUY":
        bullish_confirmation += 1
    if structure == "bullish":
        bullish_confirmation += 1

    verdict = decision.verdict
    conviction = int(decision.conviction)
    risk = decision.risk
    notes: list[str] = []

    # Capital-preservation first: require strong multi-signal confirmation for BUY.
    if verdict == "BUY" and bullish_confirmation < 3:
        verdict = "HOLD"
        notes.append("Verdict downgraded BUY -> HOLD due to insufficient bullish confirmation.")

    # In bearish regimes, disallow aggressive long calls.
    if pressure >= 2 and verdict == "BUY":
        verdict = "HOLD"
        notes.append("Verdict downgraded BUY -> HOLD due to bearish regime pressure.")

    # In strong bearish regimes with technical weakness, force defensive stance.
    if pressure >= 4 and technical == "SELL" and verdict != "SELL":
        verdict = "SELL"
        notes.append("Verdict downgraded to SELL under strong bearish regime plus technical SELL.")

    if pressure >= 2 and conviction > 7:
        conviction = 7
        notes.append("Conviction capped at 7 due to mild bearish regime pressure.")

    if pressure >= 3 and conviction > 6:
        conviction = 6
        notes.append("Conviction capped at 6 due to bearish regime pressure.")

    if pressure >= 4 and conviction > 4:
        conviction = 4
        notes.append("Conviction capped at 4 under strong bearish regime pressure.")

    if pressure >= 2 and risk == "LOW":
        risk = "MEDIUM"
        notes.append("Risk raised LOW -> MEDIUM under bearish regime pressure.")
    if pressure >= 4 and risk != "HIGH":
        risk = "HIGH"
        notes.append("Risk raised MEDIUM -> HIGH under strong bearish regime pressure.")

    expected_position = derive_position_size(conviction, risk)
    if verdict == "SELL":
        target_position = 0.5
    elif verdict == "HOLD":
        target_position = min(expected_position, 2.0)
    else:
        target_position = min(expected_position, 4.5)

    position_size = min(float(decision.position_size_pct), target_position)
    if abs(position_size - float(decision.position_size_pct)) > 0.25:
        notes.append(
            f"Position size reduced {decision.position_size_pct:.2f}% -> {position_size:.2f}% due to bearish regime guardrail."
        )

    updated = StructuredDecision(
        verdict=verdict,
        conviction=conviction,
        risk=risk,
        position_size_pct=position_size,
        time_horizon=decision.time_horizon,
    )
    return updated, notes


def _apply_rubric_regime_penalty(
    rubric_scores: dict[str, Any],
    decision: StructuredDecision,
    signals: dict[str, Any],
    stock_data: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(rubric_scores, dict) or not rubric_scores:
        return rubric_scores

    snap = _market_regime_snapshot(signals, stock_data)
    pressure = int(snap.get("bearish_pressure", 0) or 0)
    if pressure < 3:
        return rubric_scores

    criteria_in = rubric_scores.get("criteria", {}) if isinstance(rubric_scores.get("criteria"), dict) else {}
    raw: dict[str, Any] = {}
    for key in RUBRIC_CRITERIA:
        item = criteria_in.get(key, {}) if isinstance(criteria_in, dict) else {}
        score = _clamp_score(item.get("score", 1)) if isinstance(item, dict) else _clamp_score(item)
        note = str(item.get("note", "")).strip() if isinstance(item, dict) else ""
        raw[key] = {"score": score, "note": note}

    changed = False
    if decision.verdict == "BUY":
        if raw["trend_relevance"]["score"] > 2:
            raw["trend_relevance"]["score"] = 2
            raw["trend_relevance"]["note"] = "Penalized: BUY conflicts with bearish regime pressure."
            changed = True
        if raw["visual_text_alignment"]["score"] > 2:
            raw["visual_text_alignment"]["score"] = 2
            raw["visual_text_alignment"]["note"] = "Penalized: decision coherence is weak under bearish regime pressure."
            changed = True
        if raw["quote_quality"]["score"] > 4:
            raw["quote_quality"]["score"] = 4
            changed = True

    if decision.verdict == "HOLD" and pressure >= 3:
        if raw["trend_relevance"]["score"] > 3:
            raw["trend_relevance"]["score"] = 3
            raw["trend_relevance"]["note"] = "Capped: HOLD under bearish regime should not receive top trend score."
            changed = True
        if raw["visual_text_alignment"]["score"] > 3:
            raw["visual_text_alignment"]["score"] = 3
            raw["visual_text_alignment"]["note"] = "Capped: defensive posture expected under bearish regime."
            changed = True
        if raw["quote_quality"]["score"] > 4:
            raw["quote_quality"]["score"] = 4
            changed = True

    if pressure >= 4 and decision.verdict in {"BUY", "HOLD"}:
        if raw["trend_relevance"]["score"] > 2:
            raw["trend_relevance"]["score"] = 2
            changed = True
        if raw["visual_text_alignment"]["score"] > 2:
            raw["visual_text_alignment"]["score"] = 2
            changed = True
        if raw["sector_trend_fit"]["score"] > 4:
            raw["sector_trend_fit"]["score"] = 4
            changed = True
        if raw["quote_quality"]["score"] > 3:
            raw["quote_quality"]["score"] = 3
            changed = True
        if raw["report_completeness"]["score"] > 4:
            raw["report_completeness"]["score"] = 4
            changed = True

    if not changed:
        return rubric_scores

    improvements = rubric_scores.get("top_improvements", [])
    imp_lines = [str(x).strip() for x in improvements if str(x).strip()] if isinstance(improvements, list) else []
    imp_lines.insert(0, "Respect bearish regime guardrails before assigning high confidence bullish calls.")
    raw["top_improvements"] = imp_lines[:5]

    source = str(rubric_scores.get("source") or "deterministic")
    return _normalize_rubric_payload(raw, source=source)


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


def _rubric_prompt_block(mode: str) -> str:
    mode = (mode or "quick").strip().lower()
    criteria_lines = "\n".join(
        f"- {label}: score 1-5 where 5={RUBRIC_BAND_GUIDANCE[5]}, 3={RUBRIC_BAND_GUIDANCE[3]}, 1={RUBRIC_BAND_GUIDANCE[1]}."
        for label in RUBRIC_CRITERIA.values()
    )

    mode_note = (
        "Deep mode must explicitly show evidence weighting, disconfirming evidence, and thesis invalidation conditions."
        if mode == "deep"
        else "Quick mode should remain concise while preserving clear evidence-backed reasoning."
    )

    return (
        "Rubric targets (optimize your report for these criteria):\n"
        f"{criteria_lines}\n"
        "Do not write generic text: calibrate arguments to the stock-specific metrics and signals provided.\n"
        f"{mode_note}"
    )


def _rubric_feedback_for_revision(rubric_scores: dict[str, Any]) -> str:
    if not isinstance(rubric_scores, dict):
        return ""

    criteria = rubric_scores.get("criteria", {}) if isinstance(rubric_scores.get("criteria"), dict) else {}
    weak: list[str] = []
    for key, label in RUBRIC_CRITERIA.items():
        item = criteria.get(key, {}) if isinstance(criteria, dict) else {}
        score = _clamp_score(item.get("score", 1)) if isinstance(item, dict) else _clamp_score(item)
        note = str(item.get("note", "")).strip() if isinstance(item, dict) else ""
        if score <= 3:
            detail = f"{label}: {score}/5"
            if note:
                detail += f" ({note})"
            weak.append(detail)

    improvements = rubric_scores.get("top_improvements", [])
    imp_lines = [str(x).strip() for x in improvements if str(x).strip()] if isinstance(improvements, list) else []

    parts: list[str] = []
    if weak:
        parts.append("Weak rubric areas to fix:\n" + "\n".join(f"- {line}" for line in weak))
    if imp_lines:
        parts.append("Top improvements:\n" + "\n".join(f"- {line}" for line in imp_lines[:4]))
    if not parts:
        parts.append("Rubric shows strong quality; preserve evidence density and decision consistency.")
    return "\n\n".join(parts)


def _metric_anchor_hits(text: str, stock_data: dict[str, Any]) -> int:
    anchors = [
        stock_data.get("price"),
        stock_data.get("ma50"),
        stock_data.get("ma200"),
        stock_data.get("rsi14"),
        stock_data.get("trailing_pe"),
        stock_data.get("revenue_growth_pct"),
        stock_data.get("earnings_growth_pct"),
        stock_data.get("beta"),
        stock_data.get("volatility_annual_pct"),
        stock_data.get("debt_to_equity"),
        stock_data.get("profit_margin_pct"),
    ]

    hits = 0
    text_l = (text or "").lower()

    for value in anchors:
        try:
            num = float(value)
        except Exception:
            continue

        variants = {
            f"{num:.0f}",
            f"{num:.1f}",
            f"{num:.2f}",
        }
        if abs(num) >= 1000:
            variants.add(f"{num:,.0f}")
            variants.add(f"{num:,.1f}")

        normalized_variants = set()
        for v in variants:
            vv = v.rstrip("0").rstrip(".") if "." in v else v
            if vv:
                normalized_variants.add(vv.lower())

        if any(v in text_l for v in normalized_variants):
            hits += 1

    return hits


def _deterministic_rubric_scores(
    report_text: str,
    decision: StructuredDecision,
    signals: dict[str, Any],
    stock_data: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    text = (report_text or "")
    lower = text.lower()

    snap = _market_regime_snapshot(signals, stock_data)

    trend = str(signals.get("trend", "UNKNOWN") or "UNKNOWN").upper()
    technical_signal = str(signals.get("signal", "UNKNOWN") or "UNKNOWN").upper()
    fund_view = str(signals.get("fund_view", "UNKNOWN") or "UNKNOWN").upper()
    confidence = str(signals.get("confidence", "UNKNOWN") or "UNKNOWN").upper()

    trend_vote = {
        "BULLISH": "BUY",
        "BEARISH": "SELL",
        "NEUTRAL": "HOLD",
        "UNKNOWN": "HOLD",
    }.get(trend, "HOLD")

    structure = str(snap.get("structure", "mixed") or "mixed")

    trend_alignment = (
        (trend == "BULLISH" and structure == "bullish")
        or (trend == "BEARISH" and structure == "bearish")
        or (trend == "NEUTRAL" and structure == "mixed")
    )

    trend_checks = 0
    if trend in {"BULLISH", "BEARISH", "NEUTRAL"}:
        trend_checks += 1
    if "trend" in lower or trend.lower() in lower:
        trend_checks += 1
    if technical_signal == trend_vote:
        trend_checks += 1
    if trend_alignment:
        trend_checks += 1
    if confidence in {"HIGH", "MEDIUM", "LOW"} and confidence.lower() in lower:
        trend_checks += 1

    trend_score = max(1, min(5, trend_checks))
    trend_note = f"Trend checks={trend_checks}/5; structure={structure}; trend-alignment={'yes' if trend_alignment else 'no'}."

    sector = str(stock_data.get("sector") or "").strip()
    industry = str(stock_data.get("industry") or "").strip()
    sector_score = 1
    sector_note = "Sector/industry linkage in thesis is limited."
    if sector or industry:
        sector_score = 2
        mentions = 0
        if sector and sector.lower() in lower:
            mentions += 1
        if industry and industry.lower() in lower:
            mentions += 1
        if "sector" in lower or "industry" in lower:
            mentions += 1
        if "trend" in lower and ("demand" in lower or "cycle" in lower or "macro" in lower):
            mentions += 1
        sector_score = min(5, sector_score + mentions)
        sector_note = f"Sector/industry contextual linkage signals found: {mentions}."

    alignment_checks = 0
    if str(decision.verdict).lower() in lower:
        alignment_checks += 1
    if str(decision.risk).lower() in lower:
        alignment_checks += 1
    if "conviction" in lower:
        alignment_checks += 1
    if "position" in lower or str(decision.position_size_pct) in text:
        alignment_checks += 1
    if str(decision.time_horizon).lower() in lower:
        alignment_checks += 1

    coherence = 0
    if decision.verdict == technical_signal and technical_signal in {"BUY", "HOLD", "SELL"}:
        coherence += 1
    if decision.verdict == fund_view and fund_view in {"BUY", "HOLD", "SELL"}:
        coherence += 1
    if decision.verdict == trend_vote:
        coherence += 1

    if decision.risk == "HIGH" and decision.conviction <= 6:
        coherence += 1
    elif decision.risk == "LOW" and decision.conviction >= 5:
        coherence += 1
    elif decision.risk == "MEDIUM":
        coherence += 1

    if decision.risk == "HIGH" and decision.position_size_pct <= 4.5:
        coherence += 1
    elif decision.risk in {"LOW", "MEDIUM"} and decision.position_size_pct >= 2.5:
        coherence += 1

    visual_score = max(1, min(5, round((alignment_checks + coherence) / 2)))
    visual_note = f"Narrative checks={alignment_checks}/5; decision-coherence checks={coherence}/5."

    metric_refs = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))
    anchor_hits = _metric_anchor_hits(text, stock_data)
    density = metric_refs + (anchor_hits * 2)
    quote_score = 1
    if density >= 24:
        quote_score = 5
    elif density >= 15:
        quote_score = 4
    elif density >= 9:
        quote_score = 3
    elif density >= 4:
        quote_score = 2
    quote_note = f"Found {metric_refs} numeric refs and {anchor_hits} stock-metric anchors in report text."

    required = DEEP_REQUIRED_SECTIONS if mode == "deep" else QUICK_REQUIRED_SECTIONS
    optional = ["Caveats", "Disclaimer"] if mode == "deep" else ["Catalysts to Watch", "Disclaimer"]
    present = sum(1 for s in required if s.lower() in lower)
    optional_present = sum(1 for s in optional if s.lower() in lower)
    completeness_ratio = (present + 0.5 * optional_present) / max(1, len(required) + 0.5 * len(optional))
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
    completeness_note = (
        f"Detected {present}/{len(required)} required and {optional_present}/{len(optional)} optional sections for {mode} mode."
    )

    bearish_pressure = int(snap.get("bearish_pressure", 0) or 0)
    if bearish_pressure >= 4:
        trend_score = min(trend_score, 3)
        if decision.verdict != "SELL":
            visual_score = min(visual_score, 3)

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
Calibrate scores to report evidence only; avoid defaulting to identical scores across criteria or stocks.

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

    if not use_llm:
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
        if isinstance(raw, dict) and isinstance(raw.get("RUBRIC_JSON"), dict):
            raw = raw.get("RUBRIC_JSON")
        if not isinstance(raw, dict) or not raw:
            raw = extract_first_json_object(critique_text)
            if isinstance(raw, dict) and isinstance(raw.get("RUBRIC_JSON"), dict):
                raw = raw.get("RUBRIC_JSON")
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
    macro_report: str,
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
        "capital_preservation_rule": "Prioritize drawdown control over upside chasing; prefer HOLD/SELL unless BUY is strongly supported.",
        "bearish_structure_rule": "If trend is BEARISH and price <= MA50 <= MA200, do not issue aggressive BUY.",
    }

    sections = (
        "## Executive Summary\n"
        "## Signal Decomposition (Market vs Technical vs Fundamental)\n"
        "## Data Snapshot\n"
        "## Evidence Ledger\n"
        "## 12-Month Scenario Matrix (Bull/Base/Bear with assumptions and probability)\n"
        "## Risk Register with Mitigants\n"
        "## Position Sizing and Risk Controls\n"
        "## Monitoring Checklist (30/90/180 days)\n"
        "## Final Recommendation\n"
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
    rubric_guidance = _rubric_prompt_block(mode)

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

Macro & Risk report context:
{summarize_for_context(macro_report, max_chars=context_window)}

Write a robust report with these sections:
# Equity Research - {ticker} ({company})
{sections}

{depth_guidance}
{rubric_guidance}

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
    rubric_guidance = _rubric_prompt_block(mode)

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

{deep_requirements}
{rubric_guidance}"""


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
                      fundamental_report: str, macro_report: str, signals: dict,
                      mode: str = "quick") -> dict[str, Any]:
    parsed = parse_signals_impl(
        {
            "market_report": market_report,
            "technical_report": technical_report,
            "fundamental_report": fundamental_report,
            "macro_report": macro_report,
        }
    )
    signal_map = {
        "trend": parsed.trend,
        "signal": parsed.technical_signal,
        "confidence": parsed.technical_confidence,
        "fund_view": parsed.fundamental_view,
        "macro_rating": parsed.macro_rating,
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
            macro_report=macro_report,
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

            pass1_decision = parse_structured_decision(pass1_decision_json, pass1_report)
            pass1_rubric_scores, pass1_judge_output = _judge_rubric_scores(
                report_text=pass1_report,
                decision=pass1_decision,
                signals=signal_map,
                stock_data=stock_data,
                mode=mode,
                use_llm=True,
            )
            rubric_critique = _rubric_feedback_for_revision(pass1_rubric_scores)
            if not rubric_critique and pass1_judge_output:
                rubric_critique = pass1_judge_output

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
        decision, regime_notes = _apply_bearish_guardrails(decision, signal_map, stock_data)

        override_notes = rule_overrides + consistency_notes + regime_notes
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
            use_llm=True,
        )
        rubric_scores = _apply_rubric_regime_penalty(rubric_scores, decision, signal_map, stock_data)
        if not rubric_critique:
            rubric_critique = _rubric_feedback_for_revision(rubric_scores)
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
        decision, regime_notes = _apply_bearish_guardrails(decision, signal_map, stock_data)
        override_notes = rule_overrides + consistency_notes + regime_notes

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

## Data Snapshot
- Price: {stock_data.get('price')} {stock_data.get('currency')}
- RSI14: {stock_data.get('rsi14')}
- MA50 / MA200: {stock_data.get('ma50')} / {stock_data.get('ma200')}
- Trailing PE: {stock_data.get('trailing_pe')}
- Revenue growth %: {stock_data.get('revenue_growth_pct')}
- Earnings growth %: {stock_data.get('earnings_growth_pct')}
- Sector / Industry: {stock_data.get('sector')} / {stock_data.get('industry')}

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
        rubric_scores = _apply_rubric_regime_penalty(rubric_scores, decision, signal_map, stock_data)

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


def run(agent5_output: dict, mode: str = "quick") -> dict:
    ticker = agent5_output["ticker"]
    company = agent5_output["company"]
    stock_data = agent5_output.get("stock_data", {})

    market_report = agent5_output.get("market_report", "")
    technical_report = agent5_output.get("technical_report", "")
    fundamental_report = agent5_output.get("fundamental_report", "")
    macro_report = agent5_output.get("macro_report", "")

    parsed = parse_signals_impl(
        {
            "market_report": market_report,
            "technical_report": technical_report,
            "fundamental_report": fundamental_report,
            "macro_report": macro_report,
        }
    )
    signals = {
        "trend": parsed.trend,
        "signal": parsed.technical_signal,
        "confidence": parsed.technical_confidence,
        "fund_view": parsed.fundamental_view,
        "macro_rating": parsed.macro_rating,
        "horizon": parsed.horizon,
        "warnings": parsed.warnings,
    }

    print(f"\n[Agent 5] Building final investment report for {ticker}...")
    payload = synthesize_report(
        ticker=ticker,
        company=company,
        stock_data=stock_data,
        market_report=market_report,
        technical_report=technical_report,
        fundamental_report=fundamental_report,
        macro_report=macro_report,
        signals=signals,
        mode=mode,
    )

    parsed_payload = payload if isinstance(payload, dict) else extract_first_json_object(str(payload))
    final_report = parsed_payload.get("report", "")
    structured_output = parsed_payload.get("structured_output", {})

    return {
        **agent5_output,
        "mode": parsed_payload.get("mode", mode),
        "signals": signals,
        "agent5_critique": parsed_payload.get("critique", ""),
        "agent5_rubric_critique": parsed_payload.get("rubric_critique", ""),
        "rubric": parsed_payload.get("rubric", {}),
        "agent5_warnings": {
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
