import logging
import sys
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import categorize
from app import folders as folders_module
from app import fs
from app import markdown as md_render
from app import pipeline
from app import search
from app import store
from app.routes._tree import render_tree_partial, error as tree_error
from app.routes._context import nav_counts

_log = logging.getLogger(__name__)


def _split_row_tags(tags: list[store.Tag]) -> dict:
    persons = [t for t in tags if t.type == "person"]
    others = [t for t in tags if t.type in ("topic", "project")]
    visible = persons[:2] + others[:1]
    visible_set = {(t.type, t.name) for t in visible}
    hidden = [t for t in tags if (t.type, t.name) not in visible_set]
    return {"visible": visible, "hidden": hidden}


def _reindex_on_success(stem: str):
    def cb(argv: list[str], rc: int) -> None:
        if rc == 0:
            try:
                search.reindex_meeting(stem)
            except Exception:
                pass
    return cb


def _filter_tree(node: fs.TreeNode, allowed_stems: set[str]) -> fs.TreeNode:
    """Return a pruned copy of ``node`` keeping only meetings whose stems are in
    ``allowed_stems``. Subfolders with no matching meetings anywhere beneath
    them are removed."""
    filtered_subs = []
    for sub in node.subfolders:
        pruned = _filter_tree(sub, allowed_stems)
        if pruned.meetings or pruned.subfolders:
            filtered_subs.append(pruned)
    filtered_meetings = [m for m in node.meetings if m.stem in allowed_stems]
    return fs.TreeNode(
        path=node.path,
        name=node.name,
        subfolders=filtered_subs,
        meetings=filtered_meetings,
    )


ROOT = Path(__file__).parent.parent.parent
EXTRACT_PY = ROOT / "extract.py"
PROCESS_PY = ROOT / "process.py"


def build_reextract_argv(m: fs.Meeting) -> list[str]:
    data_root = fs.DATA_DIR.parent
    return [sys.executable, str(EXTRACT_PY), str(m.transcript_path.relative_to(data_root)), "--force"]


def build_reclassify_argv(m: fs.Meeting) -> list[str]:
    data_root = fs.DATA_DIR.parent
    return [sys.executable, str(PROCESS_PY), str(m.mov_path.relative_to(data_root)), "--reclassify"]

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))



@router.get("/meetings")
def meetings_index(request: Request, tag: str | None = None, tag_type: str | None = None):
    meetings = fs.list_meetings()
    tag_filter_active = bool(tag and tag_type in ("person", "topic", "project"))
    if tag_filter_active:
        allowed_stems = set(store.list_stems_with_tag(tag, tag_type))
        meetings = [m for m in meetings if m.stem in allowed_stems]
    tags_by_stem = {m.stem: store.list_meeting_tags(m.stem) for m in meetings}
    tag_split_by_stem = {stem: _split_row_tags(t) for stem, t in tags_by_stem.items()}
    tree = fs.build_tree()
    if tag_filter_active:
        tree = _filter_tree(tree, {m.stem for m in meetings})
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "tree": tree,
            "active_stem": None,
            "meeting": None,
            "selected": None,
            "tags_by_stem": tags_by_stem,
            "tag_split_by_stem": tag_split_by_stem,
            "current_tag_filter": (tag, tag_type) if tag else None,
            **nav_counts(),
        },
    )


# NOTE: this route MUST be declared before `/meetings/{stem}` below, or
# FastAPI will match the catch-all stem param ("tree-partial") first and
# respond with 404. Keep it here when refactoring.
@router.get("/meetings/tree-partial", response_class=HTMLResponse)
def tree_partial(request: Request):
    return render_tree_partial(request)


@router.get("/meetings/{stem}")
def meeting_detail(stem: str, request: Request, view: str = "knowledge"):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(status_code=404)
    if view not in ("transcript", "knowledge", "commitments"):
        view = "knowledge"
    meetings = fs.list_meetings()
    tags_by_stem = {mm.stem: store.list_meeting_tags(mm.stem) for mm in meetings}
    tag_split_by_stem = {stem: _split_row_tags(t) for stem, t in tags_by_stem.items()}
    idx = next(
        (i for i, mm in enumerate(meetings)
         if mm.subdir == m.subdir and mm.stem == m.stem),
        None,
    )
    prev_meeting = meetings[idx - 1] if idx is not None and idx > 0 else None
    next_meeting = meetings[idx + 1] if idx is not None and idx < len(meetings) - 1 else None
    tree = fs.build_tree()
    unknown_clips = [c for c in fs.list_unknown_clips() if c.source_stem == stem]
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "tree": tree,
            "active_stem": stem,
            "meeting": m,
            "selected": m,
            "view": view,
            "prev_meeting": prev_meeting,
            "next_meeting": next_meeting,
            "transcript_html": md_render.render_transcript(fs.load_transcript(m)),
            "knowledge_html": md_render.render(fs.load_knowledge(m)),
            "commitments_html": md_render.render(fs.load_commitments(m)),
            "tags_by_stem": tags_by_stem,
            "tag_split_by_stem": tag_split_by_stem,
            "meeting_tags": store.list_meeting_tags(stem),
            "unknown_clips": unknown_clips,
            "current_tag_filter": None,
            **nav_counts(),
        },
    )


@router.post("/meetings/{stem}/reextract")
def reextract(stem: str):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(
            build_reextract_argv(m), cwd=str(ROOT),
            on_complete=_reindex_on_success(stem),
        )
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.post("/meetings/{stem}/reclassify")
def reclassify_one(stem: str):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(
            build_reclassify_argv(m), cwd=str(ROOT),
            on_complete=_reindex_on_success(stem),
        )
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.post("/meetings/{stem}/tags")
def set_tags(
    stem: str,
    tag_name: Annotated[list[str], Form()] = [],
    tag_type: Annotated[list[str], Form()] = [],
):
    if fs.find_meeting_by_stem(stem) is None:
        raise HTTPException(status_code=404)
    tags = []
    for n, t in zip(tag_name, tag_type):
        n = (n or "").strip()
        if n and t in ("person", "topic", "project"):
            tags.append(store.Tag(name=n, type=t))
    store.set_meeting_tags(stem, tags, source="manual")
    return RedirectResponse(f"/meetings/{stem}", status_code=303)


@router.post("/meetings/{stem}/suggest-tags")
def suggest_tags(stem: str):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(status_code=404)
    existing_subdirs = sorted(
        {mm.subdir for mm in fs.list_meetings() if mm.subdir and mm.subdir != store.INBOX_SUBDIR}
    )
    try:
        proposal = categorize.propose(
            transcript=fs.load_transcript(m),
            knowledge=fs.load_knowledge(m),
            commitments=fs.load_commitments(m),
            existing_subdirs=existing_subdirs,
            known_names=fs.list_known_names(),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"categorize failed: {e}")
    return {"tags": [{"name": t.name, "type": t.type} for t in proposal.tags]}


@router.post("/meetings/{stem}/move", response_class=HTMLResponse)
def meeting_move(request: Request, stem: str, new_subdir: str = Form("")):
    try:
        target = folders_module.validate_folder_path(new_subdir)
    except ValueError as e:
        return tree_error(request, str(e))
    if target == "_inbox" or target.startswith("_inbox/"):
        return tree_error(request, "'_inbox' is managed by the app.")
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        return tree_error(request, f"Meeting '{stem}' not found.")
    if m.subdir == target:
        return render_tree_partial(request)
    # Collision: another meeting with the same stem already at the destination.
    dst_mov = fs.DATA_DIR / target / f"{stem}.mov"
    if dst_mov.exists():
        return tree_error(request, f"A meeting named '{stem}' already exists at '{target}'.")
    try:
        fs.move_meeting_artifacts(stem, m.subdir, target)
    except (FileExistsError, FileNotFoundError) as e:
        return tree_error(request, str(e))
    try:
        search.reindex_meeting(stem)
    except Exception:
        _log.exception("reindex failed for %s", stem)
    return render_tree_partial(request)
