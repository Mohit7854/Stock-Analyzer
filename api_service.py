"""
api_service.py - HTTP wrapper around the CLI orchestration pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import run as orchestrator
from llm_client import check_gemini

app = FastAPI(title="Stock Analysis API", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"
UI_ASSETS_DIR = UI_DIR / "assets"
INDEX_HTML = UI_DIR / "index.html"

if UI_ASSETS_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=str(UI_ASSETS_DIR)), name="ui-assets")


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Single stock query")
    save: bool = False
    mode: str = "quick"


class CompareRequest(BaseModel):
    stock_a: str = Field(..., min_length=1)
    stock_b: str = Field(..., min_length=1)
    save: bool = False
    mode: str = "quick"


class AutoRunRequest(BaseModel):
    query: str | None = None
    queries: List[str] = Field(default_factory=list)
    save: bool = False
    mode: str = "quick"


def _normalized_mode(value: str | None) -> str:
    mode = (value or "quick").strip().lower()
    return mode if mode in {"quick", "deep"} else "quick"


def _single_summary(output: dict) -> dict:
    decision = (output.get("structured_output") or {}) if isinstance(output, dict) else {}
    rubric = (output.get("rubric") or {}) if isinstance(output, dict) else {}
    return {
        "ticker": output.get("ticker") if isinstance(output, dict) else None,
        "company": output.get("company") if isinstance(output, dict) else None,
        "verdict": decision.get("verdict"),
        "conviction": decision.get("conviction"),
        "risk": decision.get("risk"),
        "position_size_pct": decision.get("position_size_pct"),
        "time_horizon": decision.get("time_horizon"),
        "rubric": rubric if isinstance(rubric, dict) and rubric else None,
        "rubric_grade": rubric.get("grade") if isinstance(rubric, dict) else None,
        "rubric_score": rubric.get("normalized_score") if isinstance(rubric, dict) else None,
    }


def _raise_500(exc: Exception) -> None:
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
def root_ui():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return {
        "ui_available": False,
        "service": "stock-analysis-api",
        "endpoints": ["/api", "/health", "/analyze", "/compare", "/run"],
    }


@app.get("/api")
def root_api() -> dict:
    return {
        "service": "stock-analysis-api",
        "ui": "/",
        "endpoints": ["/health", "/analyze", "/compare", "/run"],
        "modes": ["quick", "deep"],
    }


@app.get("/health")
def health() -> JSONResponse:
    gemini_ok, gemini_message = check_gemini()
    tavily_configured = bool((os.environ.get("TAVILY_API_KEY") or "").strip())

    ok = gemini_ok
    code = 200 if ok else 503
    payload = {
        "ok": ok,
        "message": gemini_message,
        "checks": {
            "gemini": gemini_ok,
            "tavily_api_key_configured": tavily_configured,
        },
    }
    return JSONResponse(status_code=code, content=payload)


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    mode = _normalized_mode(req.mode)
    try:
        result = orchestrator.run_pipeline(user_input=req.query.strip(), save=req.save, mode=mode)
    except Exception as exc:
        _raise_500(exc)

    output = result.get("output", {})
    return {
        "mode": "single",
        "synthesis_mode": mode,
        "elapsed": result.get("elapsed", 0.0),
        "summary": _single_summary(output),
        "output": output,
    }


@app.post("/compare")
def compare(req: CompareRequest) -> dict:
    mode = _normalized_mode(req.mode)
    try:
        result = orchestrator.run_comparison_pipeline(
            query_a=req.stock_a.strip(),
            query_b=req.stock_b.strip(),
            save=req.save,
            mode=mode,
        )
    except Exception as exc:
        _raise_500(exc)

    return {
        "mode": "multi",
        "synthesis_mode": mode,
        "stock_a_summary": _single_summary(result.get("stock_a", {})),
        "stock_b_summary": _single_summary(result.get("stock_b", {})),
        **result,
    }


@app.post("/run")
def run_auto(req: AutoRunRequest) -> dict:
    analysis_mode = _normalized_mode(req.mode)
    raw_queries = [q.strip() for q in req.queries if q and q.strip()]
    if req.query and req.query.strip():
        raw_queries.append(req.query.strip())

    if not raw_queries:
        raise HTTPException(status_code=400, detail="Provide 'query' or non-empty 'queries'.")

    route_mode, detected = orchestrator.detect_single_vs_multi_stock(raw_queries)

    if route_mode == "multi":
        try:
            result = orchestrator.run_comparison_pipeline(
                query_a=detected[0],
                query_b=detected[1],
                save=req.save,
                mode=analysis_mode,
            )
        except Exception as exc:
            _raise_500(exc)
        return {
            "mode": "multi",
            "synthesis_mode": analysis_mode,
            "stock_a_summary": _single_summary(result.get("stock_a", {})),
            "stock_b_summary": _single_summary(result.get("stock_b", {})),
            **result,
        }

    try:
        result = orchestrator.run_pipeline(user_input=detected[0], save=req.save, mode=analysis_mode)
    except Exception as exc:
        _raise_500(exc)

    output = result.get("output", {})
    return {
        "mode": "single",
        "synthesis_mode": analysis_mode,
        "elapsed": result.get("elapsed", 0.0),
        "summary": _single_summary(output),
        "output": output,
    }
