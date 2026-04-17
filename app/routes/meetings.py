import html as html_escape
import re
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import fs
from app import markdown as md_render
from app import pipeline
from app import store
from app.routes._context import nav_counts

ROOT = Path(__file__).parent.parent.parent
EXTRACT_PY = ROOT / "extract.py"
PROCESS_PY = ROOT / "process.py"


def build_reextract_argv(m: fs.Meeting) -> list[str]:
    data_root = fs.DATA_DIR.parent
    return [sys.executable, str(EXTRACT_PY), str(m.transcript_path.relative_to(data_root)), "--force"]


def build_reclassify_argv(m: fs.Meeting) -> list[str]:
    data_root = fs.DATA_DIR.parent
    return [sys.executable, str(PROCESS_PY), str(m.mov_path.relative_to(data_root)), "--reclassify"]

_UNK_RE = re.compile(r"(Unknown Speaker \d+)")


def _render_transcript(text: str) -> str:
    escaped = html_escape.escape(text)
    return _UNK_RE.sub(r'<span class="unk">\1</span>', escaped)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))



@router.get("/meetings")
def meetings_index(request: Request, tag: str | None = None, tag_type: str | None = None):
    meetings = fs.list_meetings()
    if tag and tag_type in ("person", "topic", "project"):
        allowed_stems = set(store.list_stems_with_tag(tag, tag_type))
        meetings = [m for m in meetings if m.stem in allowed_stems]
    tags_by_stem = {m.stem: store.list_meeting_tags(m.stem) for m in meetings}
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "meeting": None,
            "selected": None,
            "tags_by_stem": tags_by_stem,
            "current_tag_filter": (tag, tag_type) if tag else None,
            **nav_counts(),
        },
    )


@router.get("/meetings/{subdir}/{stem}")
def meeting_detail(subdir: str, stem: str, request: Request, view: str = "transcript"):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(status_code=404)
    if view not in ("transcript", "knowledge", "commitments"):
        view = "transcript"
    meetings = fs.list_meetings()
    tags_by_stem = {mm.stem: store.list_meeting_tags(mm.stem) for mm in meetings}
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "meeting": m,
            "selected": m,
            "view": view,
            "transcript_html": _render_transcript(fs.load_transcript(m)),
            "knowledge_html": md_render.render(fs.load_knowledge(m)),
            "commitments_html": md_render.render(fs.load_commitments(m)),
            "tags_by_stem": tags_by_stem,
            "meeting_tags": store.list_meeting_tags(stem),
            "current_tag_filter": None,
            **nav_counts(),
        },
    )


@router.post("/meetings/{subdir}/{stem}/reextract")
def reextract(subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(build_reextract_argv(m), cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.post("/meetings/{subdir}/{stem}/reclassify")
def reclassify_one(subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(build_reclassify_argv(m), cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)
