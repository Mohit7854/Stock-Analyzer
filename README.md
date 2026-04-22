# Stock market analysis lab

A compact **multi-agent workflow** that simulates an equity research desk for single-stock and two-stock analysis. Each stage is handled by a dedicated Gemini-powered role: market research, technical analysis, fundamental analysis, and final investment synthesis.

The app includes a **FastAPI** backend with a built-in browser UI. Orchestration and prompts run in Python using **Gemini**, **Yahoo Finance**, and **Tavily** for real-time market research and context enrichment.

## What the pipeline does

| Stage | Role | What happens |
|------|------|------|
| 1 | **Market research** | Resolves ticker from natural language, fetches Yahoo market data, **enriches context with Tavily** (market sentiment, recent news), and writes a trend report. |
| 2 | **Technical analyst** | Interprets moving averages, RSI, MACD, bands, and support/resistance; **integrates Tavily analyst commentary** to produce signal and confidence. |
| 3 | **Fundamental analyst** | Reviews valuation, growth, profitability, leverage; **pulls Tavily catalysts, earnings outlook, risks** to produce a horizon-oriented view. |
| 4 | **Investment advisor** | Synthesizes all signals into a final recommendation with risk, conviction, position sizing, and governance checks; **uses Tavily sentiment in conviction scoring**. |

This project is designed as a teaching/demo system. A full deep-mode run can trigger multiple billed LLM calls and external data queries.

## Tech stack

- **Python 3.10+**
- **FastAPI** + **Uvicorn** for API serving
- **Gemini API** (text synthesis and structured reasoning)
- **Yahoo Finance** via `yfinance` for market, technical, and fundamental data
- **Tavily** (required) for real-time market research, sentiment analysis, and catalyst discovery
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
	 GEMINI_API_KEY=your_gemini_api_key
	 GEMINI_MODEL=gemini-2.0-flash
	 GEMINI_TIMEOUT=180
	 TAVILY_API_KEY=tvly-...
	 ```

	 **Both `GEMINI_API_KEY` and `TAVILY_API_KEY` are required.** The system will not start without them.
	 - Get your Gemini API key from [Google AI Studio](https://aistudio.google.com)
	 - Get your Tavily API key from [Tavily](https://tavily.com)

4. **Run the API + UI**

	 ```bash
	 uvicorn api_service:app --host 0.0.0.0 --port 8000
	 ```

	 Open `http://127.0.0.1:8000/` in your browser.

## Tavily Integration

**Tavily is mandatory** for all analysis operations. The system uses Tavily to enrich real-time context across all four research stages:

### How Tavily is Used

- **Agent 1 (Market Research)**: Fetches latest stock news, market sentiment, and recent developments
- **Agent 2 (Technical Analyst)**: Pulls analyst commentary, implied volatility, positioning data
- **Agent 3 (Fundamental Analyst)**: Discovers earnings catalysts, guidance, and risk developments
- **Agent 4 (Investment Advisor)**: Incorporates latest sentiment into conviction and risk calculations

### Resilience & Retry Logic

Each agent has automatic retry logic for Tavily queries:
- **3 retries** on API failure with exponential backoff (1s → 2s → 4s)
- Failures after retry exhaustion will **block the entire analysis** with clear error message
- This ensures all reports have current, high-quality market context or fail completely

### Health Check

The `/health` endpoint will return **503 Service Unavailable** if either Gemini or Tavily is misconfigured:

```bash
# Check if system is ready
curl http://127.0.0.1:8000/health
```

Expected response when ready:
```json
{
  "ok": true,
  "message": "Gemini is available.",
  "checks": {
    "gemini": true,
    "tavily_api_key_configured": true
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

- **Mandatory Tavily Integration**: Tavily is now required (not optional) for all analyses
  - All agents use real-time market context from Tavily
  - Automatic retry logic: 3 attempts with exponential backoff (1s → 2s → 4s)
  - Health check enforces both Gemini and Tavily availability
  - Startup will fail with clear error if `TAVILY_API_KEY` is missing

- **Enriched Agent Context**:
  - **Market Research**: Real-time news, sentiment data, market developments
  - **Technical Analyst**: Analyst commentary, options flow, volatility positioning
  - **Fundamental Analyst**: Earnings catalysts, guidance, risk factors from current sources
  - **Investment Advisor**: Sentiment-based conviction scoring, current market regime analysis

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

	 - `GEMINI_API_KEY` (required)
	 - `GEMINI_MODEL` (optional, defaults to gemini-2.0-flash)
	 - `GEMINI_TIMEOUT` (optional, defaults to 180)
	 - `TAVILY_API_KEY` (required)

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
├── llm_client.py               # Gemini API wrapper
├── market_data.py              # Yahoo Finance + Tavily integration
├── agent1_market_research.py   # Market data and trend research
├── agent2_technical_analyst.py # Technical indicators and signals
├── agent3_fundamental_analyst.py # Valuation and growth analysis
├── agent4_investment_advisor.py  # Final synthesis and risk governance
├── agent4_utils.py             # Guardrail rules and position sizing
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

**Error**: `ValueError: TAVILY_API_KEY environment variable is required.`

**Solution**: 
- Verify `TAVILY_API_KEY` is set in your `.env` file
- Ensure the key is not empty or whitespace-only
- Restart the API after updating `.env`

### Health Check Returns 503

**Error**: `"ok": false` from `/health` endpoint

**Solution**:
- Check both `gemini` and `tavily_api_key_configured` flags in the response
- Verify `GEMINI_API_KEY` is valid
- Verify `TAVILY_API_KEY` is valid
- Run `uvicorn api_service:app --reload` to see startup logs

### Tavily Search Fails After Retries

**Error**: `RuntimeError: Tavily search failed after 3 attempts: ...`

**Causes & Solutions**:
- **Rate limit hit**: Check your Tavily plan limits. Retry later or upgrade.
- **Invalid API key**: Verify the key in `.env` is correct
- **Network issue**: Check internet connection
- **Tavily service down**: Check [Tavily status page](https://tavily.com)

### Analysis Hangs or Times Out

**Cause**: Tavily API is slow or unresponsive

**Solution**:
- Quick mode (default) is faster; try `--mode quick`
- Check internet connection speed
- Verify Tavily API key has sufficient rate limit quota
- Use `/health` to verify service is ready before analysis

### CLI Exits Without Output

**Error**: Script exits with no error message

**Solution**:
- Check that `.env` exists in the same directory as `run.py`
- Run with verbose logging: Add print statements to trace execution
- Verify `GEMINI_API_KEY` and `TAVILY_API_KEY` are both set
- Try running from project root: `cd "EndSEM project" && python run.py`
