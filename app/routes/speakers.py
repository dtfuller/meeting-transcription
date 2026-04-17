from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import fs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _unknown_meetings_count() -> int:
    return sum(1 for m in fs.list_meetings() if m.unknown_count > 0)


@router.get("/speakers")
def speakers_index(request: Request):
    clips = fs.list_unknown_clips()
    return templates.TemplateResponse(
        request,
        "speakers.html",
        {
            "active_tab": "speakers",
            "clips": clips,
            "known_names": fs.list_known_names(),
            "speakers_count": len(clips),
            "pipeline_running": False,
            "labels_since_reset": 0,  # wired up in Task 9
            "unknown_meetings_count": _unknown_meetings_count(),
        },
    )
