import sys
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import clips, fs, pagination, pipeline
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent
PROCESS_PY = ROOT / "process.py"


def build_reclassify_all_argv() -> list[str]:
    return [sys.executable, str(PROCESS_PY), "--reclassify"]


def _unknown_meetings_count() -> int:
    return sum(1 for m in fs.list_meetings() if m.unknown_count > 0)


@router.get("/speakers")
def speakers_index(request: Request, page: int = 1):
    unknown_clips = fs.list_unknown_clips()
    pg = pagination.paginate(unknown_clips, page)
    return templates.TemplateResponse(
        request,
        "speakers.html",
        {
            "active_tab": "speakers",
            "clips": pg.items,
            "page_info": pg,
            "page_base_url": "/speakers",
            "known_names": fs.list_known_names(),
            "labels_since_reset": clips.labels_since_reset(),
            "unknown_meetings_count": _unknown_meetings_count(),
            **nav_counts(),
        },
    )


@router.post("/speakers/label", response_class=HTMLResponse)
def label(request: Request, filename: str = Form(...), name: str = Form(...),
          page: int = Form(1)):
    clips.label_clip(filename, name)
    remaining = fs.list_unknown_clips()
    pg = pagination.paginate(remaining, page)
    html = templates.get_template("_queue_with_toast.html").render(
        request=request,
        clips=pg.items,
        page_info=pg,
        page_base_url="/speakers",
        known_names=fs.list_known_names(),
        labels_since_reset=clips.labels_since_reset(),
        unknown_meetings_count=_unknown_meetings_count(),
    )
    return HTMLResponse(html)


def _reset_counter_on_reclassify_success(argv_: list[str], rc: int) -> None:
    if rc == 0 and "--reclassify" in argv_:
        clips.reset_counter()


@router.post("/speakers/reclassify")
def reclassify_all():
    r = pipeline.get_runner()
    try:
        r.start(
            build_reclassify_all_argv(),
            cwd=str(ROOT),
            on_complete=_reset_counter_on_reclassify_success,
        )
    except pipeline.AlreadyRunning:
        raise HTTPException(status_code=409, detail="Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)
