from __future__ import annotations

from dataclasses import dataclass

from app import fs, store


@dataclass(frozen=True)
class SearchHit:
    stem: str
    subdir: str
    kind: str   # "transcript" | "knowledge" | "commitments"
    snippet: str
    rank: float


_KINDS = ("transcript", "knowledge", "commitments")


def _load_kind(m: fs.Meeting, kind: str) -> str:
    if kind == "transcript":
        return fs.load_transcript(m)
    if kind == "knowledge":
        return fs.load_knowledge(m)
    if kind == "commitments":
        return fs.load_commitments(m)
    return ""


def reindex_meeting(stem: str) -> None:
    """Rebuild FTS rows for a single meeting (all kinds). Safe if rows don't exist."""
    # Find the meeting across subdirs (include _inbox so in-flight ones are searchable).
    meeting = next(
        (m for m in fs.list_meetings(include_inbox=True) if m.stem == stem),
        None,
    )
    with store.connect() as c:
        c.execute("DELETE FROM meetings_fts WHERE stem = ?", (stem,))
        if meeting is None:
            return
        for kind in _KINDS:
            body = _load_kind(meeting, kind)
            if not body:
                continue
            c.execute(
                "INSERT INTO meetings_fts (stem, subdir, kind, body) VALUES (?, ?, ?, ?)",
                (stem, meeting.subdir, kind, body),
            )


def delete_meeting_from_index(stem: str) -> None:
    with store.connect() as c:
        c.execute("DELETE FROM meetings_fts WHERE stem = ?", (stem,))


def reindex_all() -> int:
    """Rebuild the full FTS table from the filesystem. Returns row count inserted."""
    with store.connect() as c:
        c.execute("DELETE FROM meetings_fts")
        count = 0
        for m in fs.list_meetings(include_inbox=True):
            for kind in _KINDS:
                body = _load_kind(m, kind)
                if not body:
                    continue
                c.execute(
                    "INSERT INTO meetings_fts (stem, subdir, kind, body) VALUES (?, ?, ?, ?)",
                    (m.stem, m.subdir, kind, body),
                )
                count += 1
    return count


def row_count() -> int:
    with store.connect() as c:
        return c.execute("SELECT COUNT(*) AS n FROM meetings_fts").fetchone()["n"]
