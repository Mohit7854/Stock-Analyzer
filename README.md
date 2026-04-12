# Stock market analysis lab

A compact **multi-agent workflow** that simulates an equity research desk for single-stock and two-stock analysis. Each stage is handled by a dedicated Gemini-powered role: market research, technical analysis, fundamental analysis, and final investment synthesis.

The app includes a **FastAPI** backend with a built-in browser UI. Orchestration and prompts run in Python using **Gemini**, **Yahoo Finance**, and optional **Tavily** web context.

## What the pipeline does

| Stage | Role | What happens |
|------|------|------|
| 1 | **Market research** | Resolves ticker from natural language, fetches Yahoo market data, enriches context with Tavily, and writes a trend report. |
| 2 | **Technical analyst** | Interprets moving averages, RSI, MACD, bands, and support/resistance to produce signal and confidence. |
| 3 | **Fundamental analyst** | Reviews valuation, growth, profitability, leverage, and catalysts/risks to produce a horizon-oriented view. |
| 4 | **Investment advisor** | Synthesizes all signals into a final recommendation with risk, conviction, position sizing, and governance checks. |

This project is designed as a teaching/demo system. A full deep-mode run can trigger multiple billed LLM calls and external data queries.

## Tech stack

- **Python 3.10+**
- **FastAPI** + **Uvicorn** for API serving
- **Gemini API** (text synthesis and structured reasoning)
- **Yahoo Finance** via `yfinance` for market, technical, and fundamental data
- **Tavily** (optional) for additional web research context
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

	 `TAVILY_API_KEY` is optional but recommended for richer research context.

4. **Run the API + UI**

	 ```bash
	 uvicorn api_service:app --host 0.0.0.0 --port 8000
	 ```

	 Open `http://127.0.0.1:8000/` in your browser.

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

- Uses deterministic scoring only.
- Checks signal/report alignment, section completeness, metric density, and decision-text consistency.

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

Features:

- Single stock analysis
- Two-stock comparison
- Quick/deep synthesis mode
- Health badge
- Structured summary cards
- Rubric grade badge and criterion breakdown (when available)
- In-browser report history

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
	 - `GEMINI_MODEL`
	 - `GEMINI_TIMEOUT`
	 - `TAVILY_API_KEY` (optional)

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
├── api_service.py
├── run.py
├── llm_client.py
├── market_data.py
├── agent1_market_research.py
├── agent2_technical_analyst.py
├── agent3_fundamental_analyst.py
├── agent4_investment_advisor.py
├── agent4_utils.py
├── ui/
├── requirements.txt
├── Dockerfile
├── start.sh
└── README.md
```

## Security notes

- Do not commit `.env` or API keys.
- Use dedicated API keys with usage limits.
- Rotate keys if they are ever exposed.
