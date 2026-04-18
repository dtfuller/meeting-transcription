from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import search
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


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
