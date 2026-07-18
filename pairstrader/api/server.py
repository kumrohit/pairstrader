"""Performance tracker API.

Run:  uvicorn pairstrader.api.server:app --reload
Then open http://127.0.0.1:8000

Serves the latest results.json produced by a backtest run (or, later,
by the live paper-trading loop writing the same schema).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results.json"
DASHBOARD = Path(__file__).with_name("dashboard.html")

app = FastAPI(title="Pairs Trading Performance Tracker")


@app.get("/api/results")
def results() -> JSONResponse:
    if not RESULTS.exists():
        return JSONResponse({"error": "No results yet. Run scripts/run_demo.py first."},
                            status_code=404)
    return JSONResponse(json.loads(RESULTS.read_text()))


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD.read_text()
