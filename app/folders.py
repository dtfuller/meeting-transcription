"""Pure validation helpers for folder names and paths.

No I/O. Every ValueError message is user-facing (displayed in the tree
banner), so keep it short and concrete.
"""
from __future__ import annotations

_INVALID_NAME_CHARS = frozenset("/\\")
_RESERVED_NAMES = frozenset({".", "..", "_inbox"})
MAX_NAME_LEN = 80


def validate_folder_name(name: str) -> str:
    """Normalize + validate a single folder name segment.

    Returns the cleaned name. Raises ValueError with a user-facing message.
    """
    n = (name or "").strip()
    if not n:
        raise ValueError("Name can't be empty.")
    if n in _RESERVED_NAMES:
        raise ValueError(f"'{n}' is a reserved name.")
    if any(c in _INVALID_NAME_CHARS for c in n):
        raise ValueError("Name can't contain '/' or '\\'.")
    if len(n) > MAX_NAME_LEN:
        raise ValueError(f"Name too long (max {MAX_NAME_LEN} characters).")
    return n


def validate_folder_path(path: str) -> str:
    """Validate a full folder path.

    Empty/whitespace → "" (root, valid as a destination). Otherwise every
    segment runs through validate_folder_name.
    """
    p = (path or "").strip()
    if not p:
        return ""
    if p.startswith("/") or p.endswith("/"):
        raise ValueError("Path can't start or end with '/'.")
    segments = [validate_folder_name(seg) for seg in p.split("/")]
    return "/".join(segments)
