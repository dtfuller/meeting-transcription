from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/pipeline")
def pipeline_index(request: Request):
    return templates.TemplateResponse(
        request,
        "pipeline.html",
        {"active_tab": "pipeline"},
    )
