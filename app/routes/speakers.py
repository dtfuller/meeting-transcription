from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/speakers")
def speakers_index(request: Request):
    return templates.TemplateResponse(
        request,
        "speakers.html",
        {"active_tab": "speakers"},
    )
