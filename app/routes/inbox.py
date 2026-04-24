from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config_store, fs, ingest, markdown as md_render, pagination, search, store, watcher as watcher_mod
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class InboxItem:
    proposal: store.Proposal
    transcript_html: str
    knowledge_html: str
    commitments_html: str
    has_video: bool
    unknown_clips: list  # list[fs.Clip] for this meeting's unknown speakers


def _existing_subdirs() -> list[str]:
    return sorted({m.subdir for m in fs.list_meetings()
                   if m.subdir and m.subdir != store.INBOX_SUBDIR})


def _inbox_items() -> list[InboxItem]:
    # Group clips by source_stem once so each proposal lookup is O(1).
    clips_by_stem: dict[str, list] = {}
    for c in fs.list_unknown_clips():
        clips_by_stem.setdefault(c.source_stem, []).append(c)

    items: list[InboxItem] = []
    for p in store.list_pending_proposals():
        m = fs.find_meeting(store.INBOX_SUBDIR, p.stem)
        if m is None:
            items.append(InboxItem(p, "", "", "", False, clips_by_stem.get(p.stem, [])))
            continue
        items.append(InboxItem(
            proposal=p,
            transcript_html=md_render.render_transcript(fs.load_transcript(m)),
            knowledge_html=md_render.render(fs.load_knowledge(m)),
            commitments_html=md_render.render(fs.load_commitments(m)),
            has_video=m.mov_path.exists(),
            unknown_clips=clips_by_stem.get(p.stem, []),
        ))
    return items


def _is_finished(item: InboxItem) -> bool:
    """A proposal's pipeline is "finished" only when all three content
    files exist. Status == 'ready' alone isn't enough — a safety-net
    promotion can leave a 'ready' row with no on-disk content."""
    return bool(item.transcript_html and item.knowledge_html and item.commitments_html)


def _is_finished_ok(item: InboxItem) -> bool:
    return _is_finished(item) and item.proposal.status != "error"


def _is_error(item: InboxItem) -> bool:
    return item.proposal.status == "error"


@router.get("/inbox")
def inbox_index(request: Request, page: int = 1,
                inbox_filter: str = Query("", alias="filter"),
                applied_subdir: str | None = None,
                applied_stem: str | None = None):
    all_items = _inbox_items()
    ok_count = sum(1 for i in all_items if _is_finished_ok(i))
    error_count = sum(1 for i in all_items if _is_error(i))
    if inbox_filter == "ok":
        filtered = [i for i in all_items if _is_finished_ok(i)]
    elif inbox_filter == "error":
        filtered = [i for i in all_items if _is_error(i)]
    else:
        filtered = all_items
    pg = pagination.paginate(filtered, page)
    applied_meeting = None
    if applied_subdir and applied_stem:
        from urllib.parse import quote
        applied_meeting = {
            "subdir": applied_subdir,
            "stem": applied_stem,
            "url": f"/meetings/{quote(applied_stem)}",
        }
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "active_tab": "inbox",
            "items": pg.items,
            "page_info": pg,
            "page_base_url": "/inbox",
            "page_params": {"filter": inbox_filter} if inbox_filter else {},
            "inbox_filter": inbox_filter,
            "total_count": len(all_items),
            "ok_count": ok_count,
            "error_count": error_count,
            "existing_subdirs": _existing_subdirs(),
            "watcher_enabled": bool(config_store.watch_dir()),
            "applied_meeting": applied_meeting,
            **nav_counts(),
        },
    )


@router.post("/inbox/{stem}/apply")
def inbox_apply(
    stem: str,
    target_subdir: Annotated[str, Form()],
    tag_name: Annotated[list[str], Form()] = [],
    tag_type: Annotated[list[str], Form()] = [],
    return_filter: Annotated[str, Form()] = "",
    return_page: Annotated[int, Form()] = 1,
):
    proposal = store.get_proposal(stem)
    if proposal is None:
        raise HTTPException(status_code=404)

    target_subdir = target_subdir.strip()
    if not target_subdir:
        raise HTTPException(status_code=400, detail="target_subdir is required")
    if "/" in target_subdir or "\\" in target_subdir or ".." in target_subdir:
        raise HTTPException(status_code=400, detail="invalid target_subdir")

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
    try:
        search.reindex_meeting(stem)
    except Exception:
        pass  # best-effort; files have already moved
    from urllib.parse import urlencode
    params = {"applied_subdir": target_subdir, "applied_stem": stem}
    if return_filter:
        params["filter"] = return_filter
    if return_page and return_page > 1:
        params["page"] = return_page
    return RedirectResponse(f"/inbox?{urlencode(params)}", status_code=303)


@router.post("/inbox/{stem}/dismiss")
def inbox_dismiss(
    stem: str,
    return_filter: Annotated[str, Form()] = "",
    return_page: Annotated[int, Form()] = 1,
):
    if store.get_proposal(stem) is None:
        raise HTTPException(status_code=404)
    store.delete_proposal(stem)
    return _filtered_inbox_redirect(return_filter, return_page)


@router.post("/inbox/{stem}/discard")
def inbox_discard(
    stem: str,
    return_filter: Annotated[str, Form()] = "",
    return_page: Annotated[int, Form()] = 1,
):
    if store.get_proposal(stem) is None:
        raise HTTPException(status_code=404)
    paths = [
        fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov",
        fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt",
        fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md",
        fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-commitments.md",
    ]
    for p in paths:
        if p.exists():
            p.unlink()
    store.add_dismissed_inbox_stem(stem)
    store.delete_proposal(stem)
    return _filtered_inbox_redirect(return_filter, return_page)


@router.post("/inbox/{stem}/retry")
def inbox_retry(
    stem: str,
    return_filter: Annotated[str, Form()] = "",
    return_page: Annotated[int, Form()] = 1,
):
    p = store.get_proposal(stem)
    if p is None:
        raise HTTPException(status_code=404)
    if p.status != "error":
        raise HTTPException(status_code=409, detail="proposal not in error state")
    inbox_mov = fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov"
    if not inbox_mov.exists():
        raise HTTPException(status_code=409, detail="source file missing")
    store.update_proposal_status(stem, "transcribing", None)
    ingest.get_coordinator().enqueue_existing(inbox_mov, stem)
    return _filtered_inbox_redirect(return_filter, return_page)


def _filtered_inbox_redirect(return_filter: str, return_page: int) -> RedirectResponse:
    from urllib.parse import urlencode
    params: dict = {}
    if return_filter:
        params["filter"] = return_filter
    if return_page and return_page > 1:
        params["page"] = return_page
    target = "/inbox" if not params else f"/inbox?{urlencode(params)}"
    return RedirectResponse(target, status_code=303)


@router.post("/watcher/start")
def watcher_start():
    watch_dir = os.getenv("WATCH_DIR")
    if not watch_dir:
        raise HTTPException(status_code=400, detail="WATCH_DIR not set in environment")
    w = watcher_mod.get_shared()
    if not w.is_running():
        w.start(Path(watch_dir), ingest.get_coordinator().on_new_file)
    return JSONResponse(w.status())


@router.post("/watcher/stop")
def watcher_stop():
    w = watcher_mod.get_shared()
    if w.is_running():
        w.stop()
    return JSONResponse({"is_running": False, "watch_dir": None})


@router.get("/watcher/status")
def watcher_status():
    return JSONResponse(watcher_mod.get_shared().status())
