from __future__ import annotations

import html as html_escape
from dataclasses import dataclass

from app import fs, store

# Ascii SOH/STX markers passed to FTS5 snippet() and replaced with real
# <mark> tags AFTER html-escaping the body — keeps user-sourced snippet
# content XSS-safe while still rendering the highlight as HTML.
_HL_START = "\x01"
_HL_END = "\x02"


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


def _render_snippet(raw: str) -> str:
    """HTML-escape the body, then replace control markers with real <mark> tags."""
    escaped = html_escape.escape(raw)
    return (
        escaped
        .replace(_HL_START, "<mark>")
        .replace(_HL_END, "</mark>")
    )


def search(query: str, limit: int = 50) -> list[SearchHit]:
    q = (query or "").strip()
    if not q:
        return []
    # FTS5 snippet: column_index 3 = body; left/right markers; ellipsis; max tokens.
    # We pass ASCII control chars as markers so we can html-escape the body first
    # and then substitute real <mark> tags — keeps the snippet XSS-safe for |safe
    # rendering in the template.
    sql = (
        "SELECT stem, subdir, kind, "
        "snippet(meetings_fts, 3, ?, ?, '…', 12) AS snippet, "
        "rank "
        "FROM meetings_fts WHERE meetings_fts MATCH ? "
        "ORDER BY rank LIMIT ?"
    )
    import sqlite3
    try:
        with store.connect() as c:
            rows = c.execute(sql, (_HL_START, _HL_END, q, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        SearchHit(
            stem=r["stem"],
            subdir=r["subdir"],
            kind=r["kind"],
            snippet=_render_snippet(r["snippet"] or ""),
            rank=r["rank"],
        )
        for r in rows
    ]
