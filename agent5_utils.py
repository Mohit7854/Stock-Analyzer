"""
agent5_utils.py - Reliability and decision-quality helpers for Agent 5.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

VERDICTS = {"BUY", "HOLD", "SELL"}
RISKS = {"LOW", "MEDIUM", "HIGH"}
HORIZONS = {"SHORT", "MEDIUM", "LONG"}
CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
SIGNAL_VALUES = {"BUY", "HOLD", "SELL", "UNKNOWN"}
TREND_VALUES = {"BULLISH", "NEUTRAL", "BEARISH", "UNKNOWN"}
MACRO_VALUES = {"STABLE", "CAUTION", "CRITICAL", "UNKNOWN"}


@dataclass
class ParsedSignals:
    trend: str
    technical_signal: str
    technical_confidence: str
    fundamental_view: str
    macro_rating: str
    horizon: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleDecision:
    force_no_buy: bool
    conflict_detected: bool
    all_aligned: bool
    conviction_adjustment: int
    risk_floor: str
    messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructuredDecision:
    verdict: str
    conviction: int
    risk: str
    position_size_pct: float
    time_horizon: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "conviction": int(self.conviction),
            "risk": self.risk,
            "position_size_pct": float(round(self.position_size_pct, 2)),
            "time_horizon": self.time_horizon,
        }


def _normalize_word(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"[^A-Z0-9_\- ]+", "", text)
    return text.strip()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _extract_value(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return _normalize_word(m.group(1))
    return ""


def _normalize_choice(value: str, allowed: set[str], default: str) -> str:
    norm = _normalize_word(value)
    if norm in allowed:
        return norm
    if norm == "STRONG BUY":
        return "BUY"
    if norm == "STRONG SELL":
        return "SELL"
    return default


def parse_signals(outputs: dict[str, Any]) -> ParsedSignals:
    warnings: list[str] = []

    market_text = str(outputs.get("market_report", ""))
    technical_text = str(outputs.get("technical_report", ""))
    fundamental_text = str(outputs.get("fundamental_report", ""))
    macro_text = str(outputs.get("macro_report", ""))

    trend_raw = _extract_value(
        market_text,
        [
            r"TREND\s*[:=\-]\s*([A-Za-z]+)",
            r"MARKET\s+TREND\s*[:=\-]\s*([A-Za-z]+)",
        ],
    )
    technical_raw = _extract_value(
        technical_text,
        [
            r"SIGNAL\s*[:=\-]\s*([A-Za-z]+)",
            r"TRADE\s+SIGNAL\s*[:=\-]\s*([A-Za-z]+)",
        ],
    )
    confidence_raw = _extract_value(
        technical_text,
        [r"CONFIDENCE\s*[:=\-]\s*([A-Za-z]+)"],
    )
    fund_raw = _extract_value(
        fundamental_text,
        [
            r"FUNDAMENTAL\s+VIEW\s*[:=\-]\s*([A-Za-z]+)",
            r"FUNDAMENTAL\s+VERDICT\s*[:=\-]\s*([A-Za-z]+)",
        ],
    )
    macro_raw = _extract_value(
        macro_text,
        [
            r"MACRO\s+RATING\s*[:=\-]\s*([A-Za-z]+)",
            r"MACRO\s+VIEW\s*[:=\-]\s*([A-Za-z]+)",
        ],
    )
    horizon_raw = _extract_value(
        fundamental_text,
        [r"HORIZON\s*[:=\-]\s*([A-Za-z]+)"],
    )

    trend = _normalize_choice(trend_raw, TREND_VALUES, "UNKNOWN")
    technical_signal = _normalize_choice(technical_raw, SIGNAL_VALUES, "UNKNOWN")
    technical_confidence = _normalize_choice(confidence_raw, CONFIDENCE_LEVELS, "UNKNOWN")
    fundamental_view = _normalize_choice(fund_raw, SIGNAL_VALUES, "UNKNOWN")
    macro_rating = _normalize_choice(macro_raw, MACRO_VALUES, "UNKNOWN")
    horizon = _normalize_choice(horizon_raw, HORIZONS, "MEDIUM")

    if trend == "UNKNOWN":
        warnings.append("Missing or unparseable market trend.")
    if technical_signal == "UNKNOWN":
        warnings.append("Missing or unparseable technical signal.")
    if technical_confidence == "UNKNOWN":
        warnings.append("Missing or unparseable technical confidence.")
    if fundamental_view == "UNKNOWN":
        warnings.append("Missing or unparseable fundamental view.")
    if macro_rating == "UNKNOWN":
        warnings.append("Missing or unparseable macro rating.")

    return ParsedSignals(
        trend=trend,
        technical_signal=technical_signal,
        technical_confidence=technical_confidence,
        fundamental_view=fundamental_view,
        macro_rating=macro_rating,
        horizon=horizon,
        warnings=warnings,
    )


def validate_stock_data(stock_data: dict[str, Any]) -> tuple[list[str], list[str]]:
    if not isinstance(stock_data, dict):
        return ["stock_data is missing or not a dictionary."], []

    critical_fields = ["price"]
    technical_fields = ["ma50", "ma200", "rsi14"]
    important_fields = ["beta", "volatility_annual_pct", "trailing_pe", "market_cap"]

    errors: list[str] = []
    warnings: list[str] = []

    for field in critical_fields:
        if stock_data.get(field) is None:
            errors.append(f"Critical stock_data field missing: {field}")

    for field in technical_fields:
        if stock_data.get(field) is None:
            warnings.append(f"Technical indicator unavailable: {field}")

    for field in important_fields:
        if stock_data.get(field) is None:
            warnings.append(f"Important stock_data field missing: {field}")

    return errors, warnings


def summarize_for_context(text: str, max_chars: int = 2200) -> str:
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text

    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text[:max_chars]

    top = "\n".join(lines[: min(24, len(lines))])
    bottom = "\n".join(lines[max(0, len(lines) - 24):])
    headings = [ln for ln in lines if ln.lstrip().startswith("#") or ln.strip().endswith(":")]
    headings_text = "\n".join(headings[:12])

    merged = "\n\n".join(
        part for part in [top, "...", headings_text, "...", bottom] if part
    )
    return merged[:max_chars]


def infer_risk_from_market_data(stock_data: dict[str, Any]) -> str:
    beta = _safe_float(stock_data.get("beta"))
    vol = _safe_float(stock_data.get("volatility_annual_pct"))

    if (beta is not None and beta >= 1.4) or (vol is not None and vol >= 40):
        return "HIGH"
    if (beta is not None and beta >= 1.0) or (vol is not None and vol >= 25):
        return "MEDIUM"
    return "LOW"


def derive_position_size(conviction: int, risk: str) -> float:
    c = max(1, min(10, int(conviction)))
    r = _normalize_choice(risk, RISKS, "MEDIUM")

    if c <= 3:
        base = 1.0
    elif c <= 5:
        base = 2.5
    elif c <= 7:
        base = 4.5
    elif c <= 8:
        base = 6.0
    else:
        base = 8.0

    cap = {"LOW": 10.0, "MEDIUM": 7.0, "HIGH": 4.5}[r]
    return round(min(base, cap), 2)


def compute_rule_decision(signals: ParsedSignals, stock_data: dict[str, Any]) -> RuleDecision:
    messages: list[str] = []

    force_no_buy = signals.technical_signal == "SELL" and signals.technical_confidence == "HIGH"
    if force_no_buy:
        messages.append("Hard rule active: technical SELL with HIGH confidence blocks BUY verdict.")

    market_vote = {
        "BULLISH": "BUY",
        "BEARISH": "SELL",
        "NEUTRAL": "HOLD",
        "UNKNOWN": "UNKNOWN",
    }.get(signals.trend, "UNKNOWN")

    votes = [market_vote, signals.technical_signal, signals.fundamental_view]
    known_votes = [v for v in votes if v in {"BUY", "HOLD", "SELL"}]

    all_aligned = len(known_votes) == 3 and len(set(known_votes)) == 1
    conflict_detected = "BUY" in known_votes and "SELL" in known_votes

    conviction_adjustment = 0
    if all_aligned:
        conviction_adjustment += 1
        messages.append("All agent signals align; conviction boost applied.")
    if conflict_detected:
        conviction_adjustment -= 2
        messages.append("Mixed signals detected; conviction adjusted for risk control.")

    risk_floor = infer_risk_from_market_data(stock_data)

    return RuleDecision(
        force_no_buy=force_no_buy,
        conflict_detected=conflict_detected,
        all_aligned=all_aligned,
        conviction_adjustment=conviction_adjustment,
        risk_floor=risk_floor,
        messages=messages,
    )


def extract_first_json_object(text: str, marker: str | None = None) -> dict[str, Any]:
    if not text:
        return {}

    source = text
    if marker:
        idx = source.upper().find(marker.upper())
        if idx != -1:
            source = source[idx:]

    start = source.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(source[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = source[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                    except Exception:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = source.find("{", start + 1)

    return {}


def parse_structured_decision(candidate: dict[str, Any], report_text: str) -> StructuredDecision:
    report_text = report_text or ""

    verdict = _normalize_choice(
        candidate.get("verdict", ""),
        VERDICTS,
        _normalize_choice(_extract_value(report_text, [r"FINAL\s+VERDICT\s*[:=\-]\s*([A-Za-z]+)"]), VERDICTS, "HOLD"),
    )

    conviction = _safe_int(candidate.get("conviction"))
    if conviction is None:
        c_txt = _extract_value(report_text, [r"CONVICTION\s*[:=\-]\s*(\d+)"])
        conviction = _safe_int(c_txt)
    if conviction is None:
        conviction = 6
    conviction = max(1, min(10, conviction))

    risk = _normalize_choice(
        candidate.get("risk", ""),
        RISKS,
        _normalize_choice(_extract_value(report_text, [r"RISK\s*[:=\-]\s*([A-Za-z]+)"]), RISKS, "MEDIUM"),
    )

    horizon = _normalize_choice(
        candidate.get("time_horizon", ""),
        HORIZONS,
        _normalize_choice(
            _extract_value(report_text, [r"TIME\s+HORIZON\s*[:=\-]\s*([A-Za-z]+)", r"HORIZON\s*[:=\-]\s*([A-Za-z]+)"]),
            HORIZONS,
            "MEDIUM",
        ),
    )

    position = _safe_float(candidate.get("position_size_pct"))
    if position is None:
        position = derive_position_size(conviction, risk)

    return StructuredDecision(
        verdict=verdict,
        conviction=conviction,
        risk=risk,
        position_size_pct=max(0.5, min(20.0, float(position))),
        time_horizon=horizon,
    )


def apply_rule_overrides(decision: StructuredDecision, rules: RuleDecision) -> tuple[StructuredDecision, list[str]]:
    overrides: list[str] = []

    verdict = decision.verdict
    conviction = decision.conviction
    risk = decision.risk

    if rules.force_no_buy and verdict == "BUY":
        verdict = "HOLD"
        overrides.append("Verdict downgraded from BUY to HOLD due to hard technical SELL/HIGH rule.")

    conviction = max(1, min(10, conviction + rules.conviction_adjustment))

    if rules.conflict_detected and conviction > 7:
        conviction = 7
        overrides.append("Conviction capped at 7 due to signal conflict.")

    if rules.all_aligned and conviction < 7:
        conviction = 7
        overrides.append("Conviction raised to minimum 7 because all signals align.")

    rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    if rank.get(risk, 2) < rank.get(rules.risk_floor, 2):
        risk = rules.risk_floor
        overrides.append(f"Risk raised to {risk} using beta/volatility floor.")

    updated = StructuredDecision(
        verdict=verdict,
        conviction=conviction,
        risk=risk,
        position_size_pct=decision.position_size_pct,
        time_horizon=decision.time_horizon,
    )
    return updated, overrides


def enforce_consistency(decision: StructuredDecision, stock_data: dict[str, Any]) -> tuple[StructuredDecision, list[str]]:
    notes: list[str] = []

    risk = decision.risk
    beta = _safe_float(stock_data.get("beta"))
    vol = _safe_float(stock_data.get("volatility_annual_pct"))

    if risk == "LOW" and ((beta is not None and beta >= 1.0) or (vol is not None and vol >= 25)):
        risk = "MEDIUM"
        notes.append("Risk raised LOW -> MEDIUM for elevated beta/volatility.")

    if risk == "MEDIUM" and ((beta is not None and beta >= 1.4) or (vol is not None and vol >= 40)):
        risk = "HIGH"
        notes.append("Risk raised MEDIUM -> HIGH for elevated beta/volatility.")

    expected_position = derive_position_size(decision.conviction, risk)
    if abs(expected_position - decision.position_size_pct) > 1.0:
        notes.append(
            f"Position size adjusted {decision.position_size_pct:.2f}% -> {expected_position:.2f}% for conviction/risk consistency."
        )

    updated = StructuredDecision(
        verdict=decision.verdict,
        conviction=decision.conviction,
        risk=risk,
        position_size_pct=expected_position,
        time_horizon=decision.time_horizon,
    )

    return updated, notes


def remove_decision_json_block(text: str, marker: str = "DECISION_JSON") -> str:
    if not text:
        return ""

    src = str(text)
    idx = src.upper().find(marker.upper())
    if idx == -1:
        return src

    before = src[:idx].rstrip()
    # Drop first JSON object after marker if present; keep trailing text if any.
    tail = src[idx:]
    brace = tail.find("{")
    if brace == -1:
        return before

    depth = 0
    in_string = False
    escape = False
    end_idx = -1
    for i, ch in enumerate(tail[brace:], start=brace):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break

    if end_idx == -1:
        return before

    after = tail[end_idx:].strip()
    if after:
        return (before + "\n\n" + after).strip()
    return before
