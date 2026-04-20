from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config_store, ingest, store, watcher

ROOT = Path(__file__).parent

load_dotenv()


def resolve_watch_dir() -> str | None:
    """ui.json takes precedence; fall back to the WATCH_DIR env var."""
    return config_store.watch_dir()


def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    store.init_schema()

    from app.routes import meetings, speakers, pipeline_routes, media, inbox, config_routes, search_routes
    app.include_router(meetings.router)
    app.include_router(speakers.router)
    app.include_router(pipeline_routes.router)
    app.include_router(media.router)
    app.include_router(inbox.router)
    app.include_router(config_routes.router)
    app.include_router(search_routes.router)

    from app import search as search_mod
    if search_mod.row_count() == 0:
        try:
            search_mod.reindex_all()
        except Exception:
            pass  # non-fatal; search page still works, just empty until next mutation

    @app.on_event("startup")
    def _start_watcher():
        watch_dir = resolve_watch_dir()
        if not watch_dir:
            return
        w = watcher.get_shared()
        w.start(Path(watch_dir), ingest.get_coordinator().on_new_file)

    @app.on_event("shutdown")
    def _stop_watcher():
        w = watcher.get_shared()
        if w.is_running():
            w.stop()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def root():
        return RedirectResponse("/meetings", status_code=302)

    return app


if __name__ == "__main__":
    uvicorn.run("server:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)
