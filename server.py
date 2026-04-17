from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

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
