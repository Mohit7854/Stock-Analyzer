# Stock market analysis lab

A compact **multi-agent workflow** that simulates an equity research desk for single-stock and two-stock analysis. Each stage is handled by a dedicated Groq-powered role: market research, technical analysis, fundamental analysis, and final investment synthesis.

The app includes a **FastAPI** backend with a built-in browser UI. Orchestration and prompts run in Python using **Groq**, **Yahoo Finance**, and optional **Tavily** context enrichment.

## What the pipeline does

| Stage | Role | What happens |
|------|------|------|
| 1 | **Market research** | Resolves ticker from natural language, fetches Yahoo market data, and optionally enriches with Tavily sentiment/news context. |
| 2 | **Technical analyst** | Interprets moving averages, RSI, MACD, bands, and support/resistance from Yahoo data (Tavily optional and off by default). |
| 3 | **Fundamental analyst** | Reviews valuation, growth, profitability, leverage; optionally pulls Tavily catalysts/risks context. |
| 4 | **Macro & Risk specialist** | Evaluates broader economic shifts, regulatory risks, and industry-wide headwinds; optionally enriches with Tavily context. |
| 5 | **Investment advisor** | Synthesizes all signals into the final recommendation with risk, conviction, position sizing, and governance checks. |

This project is designed as a teaching/demo system. A full deep-mode run can trigger multiple billed LLM calls and external data queries.

## Tech stack

- **Python 3.10+**
- **FastAPI** + **Uvicorn** for API serving
- **Groq API** (text synthesis and structured reasoning)
- **Yahoo Finance** via `yfinance` for market, technical, and fundamental data
- **Tavily** (optional enhancer) for additional real-time news/catalyst context
- **python-dotenv** for local environment configuration

## Quick start

1. **Clone the repository**

	 ```bash
	 git clone <your-repo-url>
	 cd "EndSEM project"
	 ```

2. **Create a virtual environment and install dependencies**

	 ```bash
	 python -m venv .venv
	 .venv\Scripts\activate    # Windows PowerShell
	 pip install -r requirements.txt
	 ```

3. **Create `.env` in the project root**

	 ```env
	 GROQ_API_KEY=your_groq_api_key
	 GROQ_MODEL=llama-3.3-70b-versatile
	 GROQ_TIMEOUT=60
	 GROQ_MIN_CALL_INTERVAL_SECONDS=1.0
	 GROQ_FAIL_FAST_ON_429=true
	 GROQ_RATE_LIMIT_COOLDOWN_SECONDS=60
	 TAVILY_API_KEY=tvly-...
	 TAVILY_ENABLED_AGENTS=1,3
	 TAVILY_FAIL_OPEN=true
	 TAVILY_MAX_RETRIES=1
	 TAVILY_MIN_DELAY_SECONDS=1.5
	 TAVILY_SEARCH_DEPTH=basic
	 ```

	 `GROQ_API_KEY` is required.
	 `TAVILY_API_KEY` is optional when `TAVILY_FAIL_OPEN=true` (default).
	 If you set `TAVILY_FAIL_OPEN=false`, Tavily becomes required.
	 - Get your Groq API key from [Groq Cloud Console](https://console.groq.com)
	 - Get your Tavily API key from [Tavily](https://tavily.com)

4. **Run the API + UI**

	 ```bash
	 uvicorn api_service:app --host 0.0.0.0 --port 8000
	 ```

	 Open `http://127.0.0.1:8000/` in your browser.

## Tavily Integration

Tavily is an context layer. Yahoo Finance remains the primary market/technical/fundamental source.

### Default Usage Policy

- `TAVILY_ENABLED_AGENTS=1,3,4` by default (Market + Fundamental + Macro)
- Agent 2 technical analysis is Yahoo-first by default
- Queries are capped and throttled to reduce usage spikes
- If Tavily fails and `TAVILY_FAIL_OPEN=true`, the pipeline continues with Yahoo + LLM
- When quota/auth failures occur, Tavily is temporarily disabled for the current process to avoid repeated errors

### Resilience & Retry Logic

The Tavily helper applies quota-safe behavior:
- low default retries (`TAVILY_MAX_RETRIES=1`)
- per-query pacing (`TAVILY_MIN_DELAY_SECONDS=1.5`)
- per-agent query caps (quick/deep) via environment variables
- quota/auth failures can short-circuit remaining Tavily queries to avoid waste

### Health Check

The `/health` endpoint always requires Groq. Tavily is required only when `TAVILY_FAIL_OPEN=false` for enabled agents.

```bash
# Check if system is ready
curl http://127.0.0.1:8000/health
```

Expected response when ready:
```json
{
  "ok": true,
  "message": "Groq is available.",
  "checks": {
    "groq": true,
		"tavily_api_key_configured": true,
		"tavily_required": false,
		"tavily_fail_open": true,
		"tavily_enabled_agents": ["agent1", "agent3", "agent4"],
		"tavily_status": "configured"
  }
}
```

## CLI usage

```bash
python run.py
python run.py "mrf"
python run.py "AAPL" --save
python run.py "mrf" --mode quick
python run.py "mrf" --mode deep

# Compare mode (two explicit inputs)
python run.py "asian paints" "mrf"

# Compare mode (natural language)
python run.py "compare asian paints and mrf"
```

## Recent Updates

### v3.0 Features (Current)

- **Hybrid Tavily Policy**: Yahoo-first pipeline with optional Tavily enhancement
	- Default enabled agents: 1 and 3 (`TAVILY_ENABLED_AGENTS=1,3`)
	- Lower Tavily usage via query caps + pacing controls
	- Fail-open mode supported (`TAVILY_FAIL_OPEN=true`) to keep pipeline running
	- Health check reports Tavily status/requirement explicitly

- **Enriched Agent Context**:
  - **Market Research**: Real-time news, sentiment data, market developments
  - **Technical Analyst**: Analyst commentary, options flow, volatility positioning
  - **Fundamental Analyst**: Earnings catalysts, guidance, risk factors from current sources
  - **Macro & Risk Specialist**: Interest rate trends, regulatory shifts, sector headwinds
  - **Investment Advisor**: Sentiment-based conviction scoring, current market regime analysis, risk-adjusted sizing

- **Improved Resilience**: Automatic retry logic prevents transient API failures from blocking analysis

### v2.0 Features

- **Report Export**: Download analyses as markdown files directly from the web UI
  - Analyze tab: Download after running an analysis
  - History tab: Download any previously saved report
  - Formats: `{TICKER}_{DATE}.md` or `{STOCK_A}_vs_{STOCK_B}_{DATE}.md`

- **Enhanced Documentation (NEW)**: Comprehensive `info.txt` with detailed explanations
  - Step-by-step guardrail rule walkthroughs
  - Real-world examples for pressure calculation
  - Position sizing formulas and examples
  - Complete rubric scoring methodology
  - Signal alignment scenarios

## API reference

Endpoints:

- `GET /` - Web UI
- `GET /api` - API metadata
- `GET /health` - Service status and key checks
- `POST /analyze` - Single stock analysis
- `POST /compare` - Two-stock comparison
- `POST /run` - Auto route to single vs comparison

All POST routes accept mode:

- `"mode": "quick"` (default, lower latency)
- `"mode": "deep"` (more context and deeper synthesis)

### Rubric logic (quick, deep, compare)

The final synthesis stage now produces a quality rubric for each stock report.

Rubric criteria:

- Trend Relevance
- Sector-Trend Fit
- Visual-Text Alignment
- Quote Quality
- Report Completeness

Scoring model:

- Each criterion gets a `score` from 1 to 5 and an optional `note`.
- `total_score` is the sum across 5 criteria (min 5, max 25).
- `normalized_score` is calculated as:
	`round((total_score / 25) * 100)`
- `grade` mapping:
	- `A`: 90-100
	- `B`: 80-89
	- `C`: 70-79
	- `D`: 60-69
	- `E`: below 60
- `top_improvements` comes from judge output when available; otherwise it is auto-generated from the weakest criteria.

Quick mode rubric behavior:

- Uses the LLM judge pass when available, with deterministic fallback.
- Keeps latency lower than deep mode by using single-pass synthesis and concise rubric prompting.

Deep mode rubric behavior:

- Uses a multi-pass flow: initial report -> critique -> rubric critique -> revision.
- Final rubric is produced by an LLM judge (`RUBRIC_JSON` contract) with deterministic fallback if judge output is unavailable or malformed.
- The final rubric payload includes `source` to indicate `llm_judge` or `deterministic`.

Where rubric data appears:

- `output.rubric` (full object with criteria, total, normalized score, grade, improvements, source)
- `summary.rubric_grade`
- `summary.rubric_score`

Comparison winner logic with rubric:

- Deterministic chooser uses rubric delta first when both rubric scores exist.
- If `abs(rubric_delta) >= 3`, winner follows rubric score lead.
- If rubric is tied/close (`abs(delta) < 3`) or missing, fallback is conviction then lower risk tier.
- Confidence from rubric delta is scaled:
	- `HIGH` when `abs(delta) >= 14`
	- `MEDIUM` when `abs(delta) >= 7`
	- `LOW` otherwise
- If LLM compare output conflicts with deterministic choice and a strong rubric gap exists (`abs(delta) >= 18` with rubric basis), deterministic winner overrides.

Comparison metadata fields:

- `comparison_meta.winner_basis`
- `comparison_meta.rubric_score_a`
- `comparison_meta.rubric_score_b`
- `comparison_meta.rubric_delta`

Example requests:

```bash
curl -X POST http://127.0.0.1:8000/analyze \
	-H "Content-Type: application/json" \
	-d '{"query":"mrf", "mode":"quick"}'

curl -X POST http://127.0.0.1:8000/compare \
	-H "Content-Type: application/json" \
	-d '{"stock_a":"asian paints","stock_b":"mrf","mode":"deep"}'
```

## Web UI

The UI is served directly by FastAPI at `GET /`.

### Tabs

- **Analyze**: Real-time stock analysis. Run a single analysis or comparison, view results, and download the report as markdown.
- **History**: View all saved reports (stored in browser localStorage). Each report can be re-downloaded at any time.

### Features

- **Single stock analysis**: Ticker or company name lookup with full multi-stage synthesis
- **Two-stock comparison**: Side-by-side analysis with winner determination and detailed rubric comparison
- **Quick/deep synthesis mode**: Toggle execution profile (quick ~10-15s, deep ~30-45s)
- **Health badge**: Real-time service status and key validation indicators
- **Structured summary cards**: Market trend, technical signal, fundamental view, and investment recommendation
- **Rubric grade badge**: Quality assessment with criterion-by-criterion breakdown (when available)
- **In-browser report history**: Persistent storage of up to 100+ reports using localStorage
- **Report download** (NEW): Export reports as markdown files directly from Analyze tab (after analysis) or History tab (for saved reports)
  - Single analysis: `{TICKER}_{DATE}.md`
  - Comparison: `{STOCK_A}_vs_{STOCK_B}_{DATE}.md`

### Downloading Reports

After running an analysis in the **Analyze** tab, click the "Download Report" button to save the analysis as a markdown file. You can also download any previously saved report from the **History** tab by clicking its download button.

## Deploy to Vercel

1. Push the repository to GitHub.
2. Import the repository in Vercel.
3. Add a `vercel.json` file in project root:

	 ```json
	 {
		 "version": 2,
		 "builds": [
			 { "src": "api_service.py", "use": "@vercel/python" }
		 ],
		 "routes": [
			 { "src": "/(.*)", "dest": "api_service.py" }
		 ],
		 "functions": {
			 "api_service.py": { "maxDuration": 300 }
		 }
	 }
	 ```

4. Set environment variables in Vercel project settings:

	 - `GROQ_API_KEY` (required)
	 - `GROQ_MODEL` (optional, defaults to llama-3.3-70b-versatile)
	 - `GROQ_TIMEOUT` (optional, defaults to 60)
	 - `TAVILY_API_KEY` (optional when `TAVILY_FAIL_OPEN=true`)
	 - `TAVILY_ENABLED_AGENTS` (optional, default `1,3`)
	 - `TAVILY_FAIL_OPEN` (optional, default `true`)
	 - `TAVILY_MAX_RETRIES` (optional, default `1`)
	 - `TAVILY_MIN_DELAY_SECONDS` (optional, default `1.5`)

5. Deploy and test `/health` and `/analyze`.

Note: deep mode may approach serverless timeout limits depending on your Vercel plan.

## Deploy to Railway (container)

This repository includes:

- `api_service.py`
- `Dockerfile`
- `start.sh`
- `.dockerignore`
- `ui/`

Steps:

1. Push to GitHub.
2. Create a Railway project from the repo.
3. Build using the included `Dockerfile`.
4. Set health check path to `/health`.
5. Configure the same environment variables as above.
6. Deploy.

## Project layout

```text
.
├── api_service.py              # FastAPI app with all endpoints
├── run.py                       # CLI orchestrator
├── llm_client.py               # Groq API wrapper
├── market_data.py              # Yahoo Finance data and indicators
├── tavily_service.py           # Tavily policy, throttling, and fallback helpers
├── agent1_market_research.py   # Market data and trend research
├── agent2_technical_analyst.py # Technical indicators and signals
├── agent3_fundamental_analyst.py # Valuation and growth analysis
├── agent4_macro_risk_specialist.py # Macro, regulatory, and systemic risk
├── agent5_investment_advisor.py  # Final synthesis and risk governance
├── agent5_utils.py             # Guardrail rules and position sizing
├── ui/                         # Web UI (HTML, CSS, JS)
├── requirements.txt            # Python dependencies
├── info.txt                    # Comprehensive project documentation
├── Dockerfile                  # Container build specification
├── start.sh                    # Container startup script
└── README.md                   # This file
```

## Documentation

For comprehensive understanding of the system internals, including detailed explanations of:

- **Bearish Pressure Calculation**: 5-component pressure model with real-world examples
- **Guardrail Rules**: Capital preservation logic with 4 major rules and sub-conditions
- **Conviction Scale**: 1-10 scale with probability mapping and capping rationale
- **Position Sizing**: Base calculation with verdict capping and portfolio examples
- **Rubric Scoring**: 5-criterion quality assessment methodology
- **Signal Alignment**: Multi-signal requirements and real-world scenarios

See `info.txt` in the project root.

## Security notes

- Do not commit `.env` or API keys.
- Use dedicated API keys with usage limits.
- Rotate keys if they are ever exposed.

## Troubleshooting

### Tavily API Key Missing

**Error**: Tavily key missing warning or strict-mode startup failure.

**Solution**: 
- Verify `TAVILY_API_KEY` is set in your `.env` file
- Ensure the key is not empty or whitespace-only
- If you want strict mode, set `TAVILY_FAIL_OPEN=false`
- Restart the API after updating `.env`

### Health Check Returns 503

**Error**: `"ok": false` from `/health` endpoint

**Solution**:
- Check `groq`, `tavily_required`, and `tavily_status` flags in the response
- Verify `GROQ_API_KEY` is valid
- If `tavily_required=true`, verify `TAVILY_API_KEY` is valid
- Run `uvicorn api_service:app --reload` to see startup logs

### Tavily Search Fails or Quota Is Hit

**Error**: Tavily warning appears and context is degraded.

**Causes & Solutions**:
- **Rate limit hit**: reduce query volume (`TAVILY_ENABLED_AGENTS=1,3`, quick mode, lower query caps) and retry later.
- **Invalid API key**: Verify the key in `.env` is correct
- **Network issue**: Check internet connection
- **Tavily service down**: Check [Tavily status page](https://tavily.com)

By default (`TAVILY_FAIL_OPEN=true`) analysis continues with Yahoo + LLM and returns warnings/degraded metadata.

### Analysis Hangs or Times Out

**Cause**: Tavily API is slow or unresponsive

**Solution**:
- Quick mode (default) is faster; try `--mode quick`
- Check internet connection speed
- Reduce Tavily pressure with `TAVILY_MAX_RETRIES=1` and higher `TAVILY_MIN_DELAY_SECONDS`
- Use `/health` to verify service is ready before analysis

### CLI Exits Without Output

**Error**: Script exits with no error message

**Solution**:
- Check that `.env` exists in the same directory as `run.py`
- Run with verbose logging: Add print statements to trace execution
- Verify `GROQ_API_KEY` is set
- If running strict mode (`TAVILY_FAIL_OPEN=false`), verify `GROQ_API_KEY` is set
- Try running from project root: `cd "EndSEM project" && python run.py`
