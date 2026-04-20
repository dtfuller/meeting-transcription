from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config_store, folder_picker, ingest, watcher as watcher_mod
from app.routes._context import nav_counts

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/config")
def config_index(request: Request):
    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "active_tab": None,
            "watch_dir": config_store.watch_dir() or "",
            **nav_counts(),
        },
    )


@router.post("/config")
def config_save(watch_dir: str = Form("")):
    watch_dir = (watch_dir or "").strip()
    if not watch_dir:
        raise HTTPException(status_code=400, detail="watch_dir is required")
    path = Path(watch_dir).expanduser()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {watch_dir}")

    settings = config_store.load()
    settings["watch_dir"] = str(path)
    config_store.save(settings)

    w = watcher_mod.get_shared()
    if w.is_running():
        w.reconfigure(path)
    else:
        w.start(path, ingest.get_coordinator().on_new_file)

    return RedirectResponse("/config", status_code=303)


@router.post("/config/browse")
def config_browse():
    initial = config_store.get("watch_dir") or None
    picked = folder_picker.pick_folder(initial)
    return JSONResponse({"path": picked})
