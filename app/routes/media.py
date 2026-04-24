from fastapi import APIRouter, HTTPException, Request

from app import fs, video

router = APIRouter()


@router.get("/video/meeting/{stem}")
def stream_meeting(stem: str, request: Request):
    m = fs.find_meeting_by_stem(stem)
    if m is None:
        raise HTTPException(status_code=404)
    return video.serve(m.mov_path, request.headers.get("range"))


@router.get("/video/clip/{filename}")
def stream_clip(filename: str, request: Request):
    # Reject anything that tries to escape the directory
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400)
    path = fs.KNOWN_NAMES_TO_CLASSIFY / filename
    return video.serve(path, request.headers.get("range"))
