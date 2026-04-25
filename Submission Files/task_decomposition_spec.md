# Stock Market Analysis — Multi-Agent Pipeline
## Task Decomposition & Specifications

| | |
|---|---|
| **Version** | 3.0 |
| **Date** | April 23, 2026 |
| **Project** | Stock Market Analysis Multi-Agent Pipeline (Groq Edition) |

---

## 1. Purpose

Convert natural-language stock input into a structured, decision-ready investment output — single stock or two-stock comparison — with governance checks, risk controls, and reproducible fallbacks using high-speed Groq inference.

---

## 2. Scope

**In scope:**
- Single-stock analysis
- Two-stock comparison
- 5-agent sequential pipeline (Market → Technical → Fundamental → Macro → Synthesis)
- Quick and deep synthesis modes
- Deterministic safety and fallback logic
- API, CLI, and UI-facing structured outputs

**Out of scope:**
- Portfolio optimization across many assets
- Order execution or brokerage integration
- Guaranteed price prediction accuracy

---

## 3. Global Input Contract

**Required runtime inputs:**

| Input | Description |
|---|---|
| Query | Single stock query or two stock phrases |
| Mode | `quick` or `deep` (defaults to `quick`) |
| Save flag | `true` / `false` — optional report persistence |

**Required environment:**

| Variable | Status | Default |
|---|---|---|
| `GROQ_API_KEY` | Required | — |
| `GROQ_MODEL` | Optional | `llama-3.3-70b-versatile` |
| `TAVILY_API_KEY` | Optional | Context enrichment only |

---

## 4. Global Output Contract

### Single-stock output fields

| Field | Type | Description |
|---|---|---|
| `ticker`, `company` | string | Resolved stock identity |
| `market_report` | string | Agent 1 trend report |
| `technical_report` | string | Agent 2 signal report |
| `fundamental_report` | string | Agent 3 valuation report |
| `macro_report` | string | Agent 4 risk report |
| `final_report` | string | Agent 5 synthesis |
| `structured_output.verdict` | BUY / HOLD / SELL | Final decision |
| `structured_output.conviction` | 1–10 | Confidence score |
| `structured_output.risk` | LOW / MEDIUM / HIGH | Risk tier |
| `structured_output.position_size_pct` | float | Suggested portfolio % |
| `structured_output.time_horizon` | SHORT / MEDIUM / LONG | Recommended hold period |
| `signals` | object | Parsed trend, signal, confidence, view, horizon, macro rating |
| `rubric` | object | Quality scores, total, normalized score, grade |
| `warnings` | list | Guardrail override notes |

### Comparison output fields

| Field | Description |
|---|---|
| `stock_a`, `stock_b` | Full single-stock outputs for each stock |
| `comparison_report` | Side-by-side narrative |
| `winner` | Winning stock identifier |
| `confidence` | HIGH / MEDIUM / LOW |
| `comparison_meta` | Winner basis, rubric delta, conviction/risk diagnostics |

---

## 5. Task Decomposition

### T0 — Environment & Model Preflight

**Goal:** Validate Groq connectivity and rate-limit settings before running the pipeline.

| | |
|---|---|
| **Inputs** | `GROQ_API_KEY`, `GROQ_MODEL`, fallback model list |
| **Outputs** | Ready / not-ready status; selected model name |

**Decision points:**
- `GROQ_API_KEY` missing → fail fast with actionable message
- Configured model unavailable → try fallback chain (Llama 3.1 → Mixtral)

---

### T1 — Input Intake & Mode Normalization

**Goal:** Normalize user input and synthesis mode before any processing.

| | |
|---|---|
| **Inputs** | Raw query or query list; optional mode string |
| **Outputs** | Sanitized query list; normalized mode (`quick` / `deep`) |

**Decision points:**
- Invalid mode string → force `quick`

---

### T2 — Route: Single vs Comparison Workflow

**Goal:** Decide whether to run a one-stock or two-stock pipeline.

| | |
|---|---|
| **Inputs** | Normalized queries from T1 |
| **Outputs** | Route type (`single` or `comparison`); resolved query pair |

**Decision points:**
- 2+ non-empty queries → comparison route
- 1 query → run LLM intent detection for hidden comparison ("compare X and Y")
- LLM parse fails → heuristic split (vs / versus / and / comma)

---

### T3 — Agent 1: Ticker Resolution & Market Snapshot

**Goal:** Resolve natural-language query to a ticker and fetch the full stock snapshot.

| | |
|---|---|
| **Inputs** | User stock query |
| **Outputs** | `ticker`, `company`, `exchange`, `confidence`, `reasoning`, `stock_data` |

**Decision points:**
- LLM-derived ticker hints available → use as primary candidates
- LLM fails → heuristic candidate list

**Handling:**
- Try Yahoo Finance resolver candidate-by-candidate until a valid symbol is found
- All candidates fail → raise resolution error with list of tried symbols

---

### T4 — Agent 1: Market Context & Trend Report

**Goal:** Build the market context block and classify the overall market trend.

| | |
|---|---|
| **Inputs** | `ticker`, `company`, `stock_data`, mode, optional Tavily key |
| **Outputs** | `market_context`, `market_report`, `TREND` line |

**Decision points:**
- Tavily enabled for Agent 1 → enrich with live news/sentiment
- Tavily fails or unavailable → continue with Yahoo data only

**Handling:**
- Deterministic trend fallback based on `price` vs `MA50` / `MA200`

---

### T5 — Agent 2: Technical Analysis

**Goal:** Produce a technical report with SIGNAL and CONFIDENCE markers.

| | |
|---|---|
| **Inputs** | Agent 1 payload, `stock_data`, mode |
| **Outputs** | `technical_context`, `technical_report`, `SIGNAL` line |

**Decision points:**
- LLM generation success → use LLM report
- LLM generation fails → deterministic fallback

**Handling:**
- Deterministic fallback: MA crossovers, RSI thresholds, MACD direction
- Yahoo Finance is primary data source; Tavily off by default for Agent 2

---

### T6 — Agent 3: Fundamental Analysis

**Goal:** Produce a fundamental report with FUNDAMENTAL VIEW and HORIZON markers.

| | |
|---|---|
| **Inputs** | Agent 2 payload, `stock_data`, mode |
| **Outputs** | `fundamental_context`, `fundamental_report`, `FUNDAMENTAL VIEW` line |

**Decision points:**
- Tavily enabled for Agent 3 → enrich with earnings catalysts, guidance, risks
- Tavily fails → continue with Yahoo fundamentals only

**Handling:**
- Deterministic fallback: growth rate, margins, and debt ratio scoring

---

### T7 — Agent 4: Macro & Risk Specialist

**Goal:** Evaluate broader economic shifts, regulatory risks, and sector headwinds.

| | |
|---|---|
| **Inputs** | Agent 3 payload, `stock_data`, mode |
| **Outputs** | `macro_context`, `macro_report`, `MACRO RATING` line |

**Decision points:**
- Tavily enabled for Agent 4 → fetch interest rate, inflation, regulatory context
- Tavily fails → LLM-only macro assessment

**Handling:**
- Deterministic macro rating fallback: STABLE / CAUTION / CRITICAL based on beta and volatility

---

### T8 — Agent 5: Signal Parsing & Data Validation

**Goal:** Extract normalized signals from all four specialist agents and validate stock data.

| | |
|---|---|
| **Inputs** | Agent 1–4 reports, `stock_data` |
| **Outputs** | Parsed `signals` object, `warnings` list |

**Decision points:**
- Expected parse markers present → extract and normalize
- Markers missing → set to `UNKNOWN` + add to warnings list

**Handling:**
- Regex-based parsing with synonym normalization (e.g., STRONG BUY → BUY)
- `price` is the only hard-error field; all others produce warnings if missing

---

### T9 — Rule Engine & Governance Overrides

**Goal:** Apply deterministic risk and consistency rules to produce the governed final decision.

| | |
|---|---|
| **Inputs** | Parsed signals, `stock_data` |
| **Outputs** | Governed `StructuredDecision`, override notes |

**Decision points:**

| Rule | Trigger | Action |
|---|---|---|
| Hard no-buy | Technical SELL + HIGH confidence | Block BUY → downgrade to HOLD |
| Alignment boost | All 3 votes agree | +1 conviction |
| Conflict penalty | BUY and SELL both present | −2 conviction, cap at 7 |
| Risk floor | Beta ≥ 1.4 or vol ≥ 40% | Raise risk to HIGH |
| Risk floor | Beta ≥ 1.0 or vol ≥ 25% | Raise risk to MEDIUM |

**Position sizing (derived from conviction + risk):**

| Conviction | Base size |
|---|---|
| 1–3 | 1.0% |
| 4–5 | 2.5% |
| 6–7 | 4.5% |
| 8 | 6.0% |
| 9–10 | 8.0% |

Then capped by risk tier: LOW → 10%, MEDIUM → 7%, HIGH → 4.5%.
Final position = `min(base, risk_cap)`.

---

### T10 — Agent 5: Report Synthesis

**Goal:** Produce the final human-readable report and `DECISION_JSON` block.

| | |
|---|---|
| **Inputs** | Agent 1–4 reports, parsed signals, stock metrics, mode, rule notes |
| **Outputs** | `final_report`, `structured_output` |

**Decision points:**

| Mode | Behavior |
|---|---|
| Quick | Single-pass LLM synthesis |
| Deep | Multi-pass: initial report → critique → rubric grade → revision |

**Handling:**
- LLM must produce `DECISION_JSON` block with verdict, conviction, risk, position size, horizon
- If JSON parse fails → deterministic structured decision from signal parsing

---

### T11 — Rubric Scoring & Quality Evaluation

**Goal:** Score the final report quality across 5 criteria.

| | |
|---|---|
| **Inputs** | `final_report`, `structured_output`, `stock_data` |
| **Outputs** | Rubric payload: criteria scores, total, normalized score (0–100), grade |

**Rubric criteria:**

| Criterion | What it measures |
|---|---|
| Trend Relevance | Does analysis reflect the actual market trend? |
| Sector-Trend Fit | Is the recommendation aligned with industry dynamics? |
| Visual-Text Alignment | Do the numbers support the narrative? |
| Quote Quality | Evidence quality and expert perspective |
| Report Completeness | All required sections present? |

**Grading:** A (90–100) · B (80–89) · C (70–79) · D (60–69) · E (<60)

**Source:** `llm_judge` in deep mode; `deterministic` fallback in quick mode.

---

### T12 — Two-Stock Comparison Decision

**Goal:** Produce a winner, confidence level, and comparison report with rubric-delta safety checks.

| | |
|---|---|
| **Inputs** | `stock_a` full output, `stock_b` full output |
| **Outputs** | `comparison_report`, `winner`, `confidence`, `comparison_meta` |

**Winner logic:**

| Rubric delta | Outcome |
|---|---|
| ≥ 3 | Winner follows rubric lead |
| < 3 | Fallback to conviction, then lower risk tier |

**Confidence from rubric delta:** HIGH (≥ 14) · MEDIUM (≥ 7) · LOW (< 7)

If LLM comparison conflicts with deterministic choice and `abs(delta) ≥ 18`, the deterministic winner overrides.

---

### T13 — Delivery & Persistence

**Goal:** Return the final payload and optionally save markdown reports to disk.

| | |
|---|---|
| **Inputs** | Final payload, save flag |
| **Outputs** | JSON payload; optional `.md` file in `reports/` |

**File naming:**
- Single: `{TICKER}_{DATE}.md`
- Comparison: `{STOCK_A}_vs_{STOCK_B}_{DATE}.md`

---

## 6. Failure & Fallback Matrix

| Failure | Behaviour |
|---|---|
| Groq unavailable | Stop immediately with explicit preflight message |
| Tavily unavailable | Continue without enrichment context (fail-open) |
| LLM generation failure | Use deterministic local fallback for that agent |
| Agent 5 synthesis failure | Deterministic final recommendation and report |
| Signal parse failure | Set affected signals to UNKNOWN; add to warnings |
| Ticker resolution failure | Raise error with list of all tried candidates |

---

## 7. Non-Functional Requirements

- Deterministic safety behavior must always be available, independent of LLM availability.
- Rate-limit handling (pacing and cooldown) designed for Groq free tier constraints.
- All agents must log warnings for missing or unparseable data.
- No agent should silently swallow errors that affect the final decision.

**Mode behavior summary:**

| Mode | Latency | LLM passes | Tavily queries per agent |
|---|---|---|---|
| Quick | ~10–15s | 1 | 1 (default) |
| Deep | ~30–45s | 4 (critique + revision) | 2 (default) |

---

## 8. Acceptance Checklist

- [ ] All 5 agents execute in sequence (1 → 2 → 3 → 4 → 5)
- [ ] Every final report includes all structured decision fields
- [ ] Governance override notes appear whenever a guardrail fires
- [ ] Comparison always returns exactly one winner
- [ ] Pipeline handles rate limits and service unavailability gracefully
- [ ] Deterministic fallbacks activate without crashing the pipeline
- [ ] All UNKNOWN signals produce a warning entry in the output
- [ ] Position size is always within 0.5%–20.0% bounds
- [ ] Report files are saved only when `save=true`
- [ ] Health endpoint returns actionable status before any analysis runs

---

*Stock Market Analysis Multi-Agent Pipeline · Version 3.0 · April 2026*
