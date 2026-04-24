"""Shared helpers for rendering the <aside class='tree'> HTMX partial.

Both app/routes/folders.py (CRUD + move) and app/routes/meetings.py
(single-meeting move + tree-partial GET) return this fragment on success
and on error (with a red banner).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import fs
from app.routes._context import nav_counts

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def render_tree_partial(request: Request, *, error: str | None = None) -> HTMLResponse:
    """Render the <aside class='tree'> outerHTML. Optional red banner at the top."""
    tree = fs.build_tree()
    html = templates.get_template("_meeting_tree_partial.html").render(
        request=request,
        tree=tree,
        tree_error=error,
        **nav_counts(),
    )
    return HTMLResponse(html)


def error(request: Request, msg: str) -> HTMLResponse:
    return render_tree_partial(request, error=msg)
