from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import search
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/search/partial")
def search_partial(request: Request, q: str = ""):
    query = (q or "").strip()
    if not query:
        # HTMX swaps innerHTML — empty string clears the dropdown.
        return HTMLResponse("")
    hits = search.search(query, limit=8)
    return templates.TemplateResponse(
        request,
        "_search_partial.html",
        {"hits": hits, "query": query},
    )


@router.get("/search")
def search_index(request: Request, q: str = ""):
    query = (q or "").strip()
    hits = search.search(query) if query else []
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "active_tab": None,
            "query": query,
            "hits": hits,
            **nav_counts(),
        },
    )
