import sys
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import clips, fs, pagination, pipeline, reidentify, store
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
    parsed = fs.parse_clip_filename(filename)
    clips.label_clip(filename, name)
    if parsed is not None:
        reidentify.apply_label_to_transcript(
            parsed.source_stem, parsed.raw_label, parsed.timestamp_text, name,
        )
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


@router.post("/speakers/label-inline", response_class=HTMLResponse)
def label_inline(request: Request,
                 filename: str = Form(...),
                 name: str = Form(...),
                 stem: str = Form(...)):
    """Label a clip and return ONLY the updated per-meeting speaker list.

    Used by the inline editor on /inbox cards and the /meetings detail
    page, where we want a scoped HTMX swap rather than re-rendering the
    entire global Speakers queue.
    """
    parsed = fs.parse_clip_filename(filename)
    clips.label_clip(filename, name)
    if parsed is not None:
        reidentify.apply_label_to_transcript(
            parsed.source_stem, parsed.raw_label, parsed.timestamp_text, name,
        )
    stem_clips = [c for c in fs.list_unknown_clips() if c.source_stem == stem]
    html = templates.get_template("_unknown_speakers_inline.html").render(
        request=request,
        stem=stem,
        clips=stem_clips,
    )
    return HTMLResponse(html)


@router.post("/speakers/discard", response_class=HTMLResponse)
def discard(request: Request,
            filename: str = Form(...),
            source_stem: str = Form(...),
            timestamp_text: str = Form(...),
            page: int = Form(1)):
    clip_path = fs.KNOWN_NAMES_TO_CLASSIFY / filename
    if clip_path.exists():
        clip_path.unlink()
    store.add_dismissed_clip(source_stem, timestamp_text)
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


@router.post("/speakers/rematch-queue", response_class=HTMLResponse)
def rematch_queue(request: Request, page: int = Form(1)):
    """Embed each queued clip and match it against the current
    known-names/to-use/ voiceprints. No video re-processing — just in-place
    transcript patches plus clip file moves for any matches."""
    result = reidentify.rematch_unknown_clips()
    remaining = fs.list_unknown_clips()
    pg = pagination.paginate(remaining, page)
    toast = {
        "matched": len(result.matched),
        "still_unknown": len(result.unmatched),
        "names": sorted({n for _, n in result.matched}),
    }
    html = templates.get_template("_queue_with_toast.html").render(
        request=request,
        clips=pg.items,
        page_info=pg,
        page_base_url="/speakers",
        known_names=fs.list_known_names(),
        labels_since_reset=clips.labels_since_reset(),
        unknown_meetings_count=_unknown_meetings_count(),
        rematch_toast=toast,
    )
    return HTMLResponse(html)


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
