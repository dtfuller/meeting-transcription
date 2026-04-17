from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import fs, ingest, store, watcher as watcher_mod
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent

# Shared watcher instance used by the lifecycle endpoints. server.py's startup
# hook also installs one; when that is present, /watcher/start is a no-op.
_shared_watcher: watcher_mod.Watcher | None = None


def _existing_subdirs() -> list[str]:
    return sorted({m.subdir for m in fs.list_meetings()
                   if m.subdir and m.subdir != store.INBOX_SUBDIR})


@router.get("/inbox")
def inbox_index(request: Request):
    proposals = store.list_pending_proposals()
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "active_tab": "inbox",
            "proposals": proposals,
            "existing_subdirs": _existing_subdirs(),
            "watcher_enabled": bool(os.getenv("WATCH_DIR")),
            **nav_counts(),
        },
    )


@router.post("/inbox/{stem}/apply")
def inbox_apply(
    stem: str,
    target_subdir: Annotated[str, Form()],
    tag_name: Annotated[list[str], Form()] = [],
    tag_type: Annotated[list[str], Form()] = [],
):
    proposal = store.get_proposal(stem)
    if proposal is None:
        raise HTTPException(status_code=404)

    target_subdir = target_subdir.strip()
    if not target_subdir:
        raise HTTPException(status_code=400, detail="target_subdir is required")

    moves = [
        (fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov",
         fs.DATA_DIR / target_subdir / f"{stem}.mov"),
        (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt",
         fs.TRANSCRIPTS_DIR / target_subdir / f"{stem}.txt"),
        (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md",
         fs.INFORMATION_DIR / target_subdir / f"{stem}-knowledge.md"),
        (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-commitments.md",
         fs.INFORMATION_DIR / target_subdir / f"{stem}-commitments.md"),
    ]
    for src, dst in moves:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    tags = []
    for n, t in zip(tag_name, tag_type):
        n = (n or "").strip()
        t = (t or "").strip()
        if n and t in ("person", "topic", "project"):
            tags.append(store.Tag(name=n, type=t))
    store.set_meeting_tags(stem, tags, source="auto" if proposal.proposed_subdir else "manual")

    store.delete_proposal(stem)
    return RedirectResponse(f"/meetings/{target_subdir}/{stem}", status_code=303)


@router.post("/inbox/{stem}/dismiss")
def inbox_dismiss(stem: str):
    if store.get_proposal(stem) is None:
        raise HTTPException(status_code=404)
    store.delete_proposal(stem)
    return RedirectResponse("/inbox", status_code=303)


@router.post("/watcher/start")
def watcher_start():
    global _shared_watcher
    watch_dir = os.getenv("WATCH_DIR")
    if not watch_dir:
        raise HTTPException(status_code=400, detail="WATCH_DIR not set in environment")
    if _shared_watcher is None:
        _shared_watcher = watcher_mod.Watcher()
    if not _shared_watcher.is_running():
        _shared_watcher.start(Path(watch_dir), ingest.get_coordinator().on_new_file)
    return JSONResponse(_shared_watcher.status())


@router.post("/watcher/stop")
def watcher_stop():
    global _shared_watcher
    if _shared_watcher is not None and _shared_watcher.is_running():
        _shared_watcher.stop()
    return JSONResponse({"is_running": False, "watch_dir": None})


@router.get("/watcher/status")
def watcher_status():
    global _shared_watcher
    if _shared_watcher is None:
        return JSONResponse({"is_running": False, "watch_dir": None})
    return JSONResponse(_shared_watcher.status())
