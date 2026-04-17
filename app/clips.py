from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app import fs


@dataclass
class LabelResult:
    new_path: Path


_lock = threading.Lock()
_counter = 0


def label_clip(clip_filename: str, name: str) -> LabelResult:
    if "/" in clip_filename or "\\" in clip_filename or ".." in clip_filename:
        raise ValueError("invalid clip filename")
    src = fs.KNOWN_NAMES_TO_CLASSIFY / clip_filename
    if not src.exists():
        raise FileNotFoundError(clip_filename)

    # Build destination name: "<name> - <rest of original filename after first ' - '>"
    rest = clip_filename.split(" - ", 1)[1] if " - " in clip_filename else clip_filename
    fs.KNOWN_NAMES_TO_USE.mkdir(parents=True, exist_ok=True)
    candidate = fs.KNOWN_NAMES_TO_USE / f"{name.strip()} - {rest}"
    if candidate.exists():
        stem = candidate.stem
        suffix = candidate.suffix
        n = 2
        while True:
            candidate = fs.KNOWN_NAMES_TO_USE / f"{stem} ({n}){suffix}"
            if not candidate.exists():
                break
            n += 1

    src.rename(candidate)

    global _counter
    with _lock:
        _counter += 1

    return LabelResult(new_path=candidate)


def labels_since_reset() -> int:
    return _counter


def reset_counter() -> None:
    global _counter
    with _lock:
        _counter = 0
