from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app import fs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _counts() -> dict:
    return {
        "speakers_count": len(fs.list_unknown_clips()),
        "pipeline_running": False,  # wired up in pipeline task
    }


@router.get("/meetings")
def meetings_index(request: Request):
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": fs.list_meetings(),
            "meeting": None,
            "selected": None,
            **_counts(),
        },
    )


@router.get("/meetings/{subdir}/{stem}")
def meeting_detail(subdir: str, stem: str, request: Request, view: str = "transcript"):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(status_code=404)
    if view not in ("transcript", "knowledge", "commitments"):
        view = "transcript"
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": fs.list_meetings(),
            "meeting": m,
            "selected": m,
            "view": view,
            "transcript_text": fs.load_transcript(m),
            "knowledge_html": fs.load_knowledge(m),
            "commitments_html": fs.load_commitments(m),
            **_counts(),
        },
    )
