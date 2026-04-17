from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse


def _parse_range(header: str, size: int) -> tuple[int, int]:
    # "bytes=START-END"  — END inclusive; END may be missing
    if not header.startswith("bytes="):
        raise ValueError("bad range header")
    spec = header.removeprefix("bytes=").strip()
    start_str, _, end_str = spec.partition("-")
    start = int(start_str)
    end = int(end_str) if end_str else size - 1
    if start < 0 or end < start or end >= size:
        raise ValueError("range out of bounds")
    return start, end


def _iter_file(path: Path, start: int, length: int, chunk: int = 65536):
    with path.open("rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def serve(path: Path, range_header: str | None) -> Response:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    size = path.stat().st_size
    media_type = "video/quicktime" if path.suffix.lower() == ".mov" else "application/octet-stream"

    if range_header:
        try:
            start, end = _parse_range(range_header, size)
        except ValueError:
            raise HTTPException(status_code=416)
        length = end - start + 1
        return StreamingResponse(
            _iter_file(path, start, length),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    return StreamingResponse(
        _iter_file(path, 0, size),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
    )
