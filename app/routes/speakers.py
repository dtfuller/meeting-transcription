from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import clips, fs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _unknown_meetings_count() -> int:
    return sum(1 for m in fs.list_meetings() if m.unknown_count > 0)


@router.get("/speakers")
def speakers_index(request: Request):
    unknown_clips = fs.list_unknown_clips()
    return templates.TemplateResponse(
        request,
        "speakers.html",
        {
            "active_tab": "speakers",
            "clips": unknown_clips,
            "known_names": fs.list_known_names(),
            "speakers_count": len(unknown_clips),
            "pipeline_running": False,
            "labels_since_reset": clips.labels_since_reset(),
            "unknown_meetings_count": _unknown_meetings_count(),
        },
    )


@router.post("/speakers/label", response_class=HTMLResponse)
def label(request: Request, filename: str = Form(...), name: str = Form(...)):
    clips.label_clip(filename, name)
    remaining = fs.list_unknown_clips()
    html = templates.get_template("_queue_with_toast.html").render(
        request=request,
        clips=remaining,
        known_names=fs.list_known_names(),
        labels_since_reset=clips.labels_since_reset(),
        unknown_meetings_count=_unknown_meetings_count(),
    )
    return HTMLResponse(html)
