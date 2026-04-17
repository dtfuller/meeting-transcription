import sys
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import fs, pipeline, clips

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent
PROCESS_PY = ROOT / "process.py"


def resolve_argv(scope: str, mode: str) -> list[str]:
    """Convert form fields -> argv for process.py."""
    argv: list[str] = [sys.executable, str(PROCESS_PY)]
    if scope and scope != "all":
        argv.append(scope)
    if mode == "reclassify":
        argv.append("--reclassify")
    return argv


def _meetings_as_scopes() -> list[str]:
    """All selectable scopes: 'all', each subdir, each individual .mov."""
    out = ["all"]
    meetings = fs.list_meetings()
    subdirs = sorted({m.subdir for m in meetings if m.subdir})
    out += [f"data/{s}" for s in subdirs]
    data_root = fs.DATA_DIR.parent
    out += [str(m.mov_path.relative_to(data_root)) for m in meetings]
    return out


@router.get("/pipeline")
def pipeline_index(request: Request):
    r = pipeline.get_runner()
    return templates.TemplateResponse(
        request,
        "pipeline.html",
        {
            "active_tab": "pipeline",
            "scopes": _meetings_as_scopes(),
            "is_running": r.is_running(),
            "history": r.history(),
            "speakers_count": len(fs.list_unknown_clips()),
            "pipeline_running": r.is_running(),
        },
    )


@router.post("/pipeline/run")
def pipeline_run(scope: str = Form("all"), mode: str = Form("new")):
    r = pipeline.get_runner()
    argv = resolve_argv(scope, mode)

    def on_complete(argv_: list[str], rc: int) -> None:
        if rc == 0 and "--reclassify" in argv_:
            clips.reset_counter()

    r.set_on_complete(on_complete)

    try:
        r.start(argv, cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(status_code=409, detail="Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.get("/pipeline/stream")
async def pipeline_stream():
    r = pipeline.get_runner()

    async def event_source():
        async for line in r.subscribe():
            yield f"data: {line}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
