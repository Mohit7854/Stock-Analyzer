"""
market_data.py - Shared Yahoo Finance data helpers.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd
import yfinance as yf


_QUERY_STOPWORDS = {
    "i", "want", "need", "show", "me", "the", "a", "an", "for", "to", "of", "and",
    "stock", "shares", "company", "price", "analysis", "please", "buy", "said",
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _r(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _ticker_info(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    try:
        return t.info or {}
    except Exception:
        return {}


def _symbol_has_data(symbol: str) -> bool:
    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True)
        return not hist.empty
    except Exception:
        return False


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _query_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [t for t in tokens if len(t) > 1 and t not in _QUERY_STOPWORDS]


def resolve_ticker(user_input: str) -> dict:
    """
    Resolve a natural-language stock query to a Yahoo Finance symbol.
    """
    query = user_input.strip()
    if not query:
        raise ValueError("Empty stock query.")

    compact = re.sub(r"\s+", "", query).upper()
    if re.fullmatch(r"[A-Z0-9.\-]{1,12}", compact):
        if "." in compact:
            direct_candidates = [compact]
        else:
            # Try Indian exchange suffixes first to avoid noisy failed probes.
            direct_candidates = [f"{compact}.NS", f"{compact}.BO", compact]
        for symbol in direct_candidates:
            if _symbol_has_data(symbol):
                info = _ticker_info(symbol)
                return {
                    "ticker": symbol,
                    "company": info.get("longName") or info.get("shortName") or symbol,
                    "exchange": info.get("exchange") or info.get("fullExchangeName") or "",
                    "confidence": "HIGH",
                    "reasoning": "Resolved directly as a valid Yahoo Finance symbol.",
                }

    try:
        search = yf.Search(query, max_results=8, news_count=0)
        quotes = getattr(search, "quotes", []) or []
    except Exception as exc:
        raise RuntimeError(f"Ticker search failed for query '{query}': {exc}") from exc

    if not quotes:
        raise RuntimeError(f"No ticker match found for '{query}' on Yahoo Finance.")

    equity_quotes = [q for q in quotes if isinstance(q, dict) and (q.get("quoteType") or "").upper() in ("", "EQUITY")]
    ranked_quotes = equity_quotes if equity_quotes else [q for q in quotes if isinstance(q, dict)]

    tokens = _query_tokens(query)
    query_norm = _norm_text(" ".join(tokens) if tokens else query)

    def _quote_score(quote: dict) -> int:
        symbol = str(quote.get("symbol") or "")
        longname = str(quote.get("longname") or quote.get("shortname") or "")
        sym_norm = _norm_text(symbol)
        name_norm = _norm_text(longname)

        score = 0
        qtype = (quote.get("quoteType") or "").upper()
        score += 10 if qtype in ("", "EQUITY") else -100

        if query_norm and query_norm == sym_norm:
            score += 130
        if query_norm and query_norm in name_norm:
            score += 90
        if query_norm and sym_norm and sym_norm in query_norm:
            score += 20

        if tokens:
            matched = sum(1 for t in tokens if t in name_norm or t in sym_norm)
            score += matched * 30
            if matched == len(tokens):
                score += 45
            elif len(tokens) > 1 and matched >= 2:
                score += 20

        exch = str(quote.get("exchange") or "").upper()
        if exch in {"NSE", "BSE", "NSI", "BOM"}:
            score += 5
        return score

    best = max(ranked_quotes, key=_quote_score) if ranked_quotes else quotes[0]

    symbol = best.get("symbol")
    if not symbol:
        raise RuntimeError(f"Yahoo Finance returned no symbol for '{query}'.")

    info = _ticker_info(symbol)
    company = (
        info.get("longName")
        or info.get("shortName")
        or best.get("longname")
        or best.get("shortname")
        or symbol
    )

    normalized_query = query.lower().replace(" ", "")
    normalized_symbol = symbol.lower().replace(" ", "")
    confidence = "HIGH" if normalized_query == normalized_symbol else "MEDIUM"

    return {
        "ticker": symbol,
        "company": company,
        "exchange": info.get("exchange") or info.get("fullExchangeName") or best.get("exchange") or "",
        "confidence": confidence,
        "reasoning": "Resolved using Yahoo Finance search results.",
    }


def _rsi14(close: pd.Series) -> float | None:
    if len(close) < 20:
        return None
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.rolling(window=14).mean()
    avg_loss = losses.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return _to_float(rsi.iloc[-1])


def get_stock_snapshot(symbol: str) -> dict:
    """
    Fetch market + technical + basic fundamental data from Yahoo Finance.
    """
    t = yf.Ticker(symbol)
    hist = t.history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty:
        raise RuntimeError(f"No historical market data available for {symbol}.")

    hist = hist.dropna(subset=["Close"])
    close = hist["Close"]
    high = hist["High"] if "High" in hist else close
    low = hist["Low"] if "Low" in hist else close
    volume = hist["Volume"] if "Volume" in hist else pd.Series([0] * len(close), index=close.index)

    latest = _to_float(close.iloc[-1])
    prev = _to_float(close.iloc[-2] if len(close) > 1 else close.iloc[-1])

    def pct_change(days: int) -> float | None:
        if len(close) <= days:
            return None
        base = _to_float(close.iloc[-(days + 1)])
        if not base:
            return None
        return ((latest - base) / base) * 100 if latest is not None else None

    ma20 = _to_float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
    ma50 = _to_float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    ma200 = _to_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + (2 * bb_std)
    bb_lower = bb_mid - (2 * bb_std)

    returns = close.pct_change().dropna()
    vol_annual = _to_float(returns.tail(30).std() * math.sqrt(252) * 100) if len(returns) >= 10 else None

    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    support_20d = _to_float(low.tail(20).min()) if len(low) >= 20 else _to_float(low.min())
    resistance_20d = _to_float(high.tail(20).max()) if len(high) >= 20 else _to_float(high.max())
    low_52w = _to_float(low.tail(252).min()) if len(low) >= 252 else _to_float(low.min())
    high_52w = _to_float(high.tail(252).max()) if len(high) >= 252 else _to_float(high.max())

    avg_vol_20 = _to_int(volume.tail(20).mean()) if len(volume) >= 20 else _to_int(volume.mean())
    latest_vol = _to_int(volume.iloc[-1]) if len(volume) else None

    snapshot = {
        "ticker": symbol,
        "company": info.get("longName") or info.get("shortName") or symbol,
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": _to_int(info.get("marketCap")),
        "beta": _r(_to_float(info.get("beta")), 3),
        "price": _r(latest),
        "prev_close": _r(prev),
        "day_change_pct": _r(((latest - prev) / prev) * 100 if latest and prev else None),
        "month_change_pct": _r(pct_change(21)),
        "quarter_change_pct": _r(pct_change(63)),
        "ma20": _r(ma20),
        "ma50": _r(ma50),
        "ma200": _r(ma200),
        "rsi14": _r(_rsi14(close)),
        "macd": _r(_to_float(macd_line.iloc[-1])),
        "macd_signal": _r(_to_float(signal_line.iloc[-1])),
        "macd_hist": _r(_to_float(macd_hist.iloc[-1])),
        "bb_upper": _r(_to_float(bb_upper.iloc[-1])),
        "bb_mid": _r(_to_float(bb_mid.iloc[-1])),
        "bb_lower": _r(_to_float(bb_lower.iloc[-1])),
        "support_20d": _r(support_20d),
        "resistance_20d": _r(resistance_20d),
        "low_52w": _r(low_52w),
        "high_52w": _r(high_52w),
        "avg_volume_20d": avg_vol_20,
        "latest_volume": latest_vol,
        "volatility_annual_pct": _r(vol_annual),
        "trailing_pe": _r(_to_float(info.get("trailingPE"))),
        "forward_pe": _r(_to_float(info.get("forwardPE"))),
        "price_to_book": _r(_to_float(info.get("priceToBook"))),
        "ev_to_ebitda": _r(_to_float(info.get("enterpriseToEbitda"))),
        "profit_margin_pct": _r(_to_float(info.get("profitMargins")) * 100 if info.get("profitMargins") is not None else None),
        "revenue_growth_pct": _r(_to_float(info.get("revenueGrowth")) * 100 if info.get("revenueGrowth") is not None else None),
        "earnings_growth_pct": _r(_to_float(info.get("earningsGrowth")) * 100 if info.get("earningsGrowth") is not None else None),
        "debt_to_equity": _r(_to_float(info.get("debtToEquity"))),
        "free_cash_flow": _to_int(info.get("freeCashflow")),
        "return_on_equity_pct": _r(_to_float(info.get("returnOnEquity")) * 100 if info.get("returnOnEquity") is not None else None),
        "dividend_yield_pct": _r(_to_float(info.get("dividendYield")) * 100 if info.get("dividendYield") is not None else None),
    }
    return snapshot
