from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "ui.json"


def load() -> dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save(settings: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, sort_keys=True)
    os.replace(tmp, CONFIG_PATH)


def get(key: str, default=None):
    return load().get(key, default)


def watch_dir() -> str | None:
    """Single source of truth: ui.json wins, then WATCH_DIR env, else None."""
    import os
    from_config = get("watch_dir")
    if from_config:
        return from_config
    from_env = os.getenv("WATCH_DIR")
    return from_env or None
