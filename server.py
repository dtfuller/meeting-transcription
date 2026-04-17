import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import ingest, store, watcher

ROOT = Path(__file__).parent

load_dotenv()

_watcher: watcher.Watcher | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    store.init_schema()

    from app.routes import meetings, speakers, pipeline_routes, media
    app.include_router(meetings.router)
    app.include_router(speakers.router)
    app.include_router(pipeline_routes.router)
    app.include_router(media.router)

    @app.on_event("startup")
    def _start_watcher():
        global _watcher
        watch_dir = os.getenv("WATCH_DIR")
        if not watch_dir:
            return
        _watcher = watcher.Watcher()
        _watcher.start(Path(watch_dir), ingest.get_coordinator().on_new_file)

    @app.on_event("shutdown")
    def _stop_watcher():
        global _watcher
        if _watcher is not None:
            _watcher.stop()
            _watcher = None

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def root():
        return RedirectResponse("/meetings", status_code=302)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
