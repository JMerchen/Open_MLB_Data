"""FastAPI app that serves the mispriced-Topps-cards page.

Read-only: it never calls eBay itself. All data comes from whatever the
collector (app/collector.py, run on a schedule) has already written to
SQLite. Run with: uvicorn app.web:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import comps, config, db

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Topps eBay Mispricing Finder")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def _ensure_db() -> None:
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    view: str = Query("underpriced", pattern="^(underpriced|overpriced)$"),
    limit: int = Query(50, ge=1, le=200),
):
    listings = (
        comps.most_underpriced(limit=limit)
        if view == "underpriced"
        else comps.most_overpriced(limit=limit)
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "listings": listings,
            "view": view,
            "limit": limit,
            "comp_lookback_days": config.COMP_LOOKBACK_DAYS,
            "min_comps": config.MIN_COMPS_FOR_SCORE,
        },
    )


@app.get("/api/mispriced")
def api_mispriced(
    view: str = Query("underpriced", pattern="^(underpriced|overpriced)$"),
    limit: int = Query(50, ge=1, le=200),
):
    listings = (
        comps.most_underpriced(limit=limit)
        if view == "underpriced"
        else comps.most_overpriced(limit=limit)
    )
    return [comps.to_dict(listing) for listing in listings]
