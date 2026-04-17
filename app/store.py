from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "ui.db"
INBOX_SUBDIR = "_inbox"


@dataclass(frozen=True)
class Tag:
    name: str
    type: str  # "person" | "topic" | "project"


@dataclass(frozen=True)
class Proposal:
    stem: str
    proposed_subdir: str
    proposed_tags: list[Tag]
    status: str  # "transcribing" | "analyzing" | "ready" | "error"
    error_message: str | None
    created_at: str


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meeting_tags (
          stem      TEXT NOT NULL,
          tag_name  TEXT NOT NULL,
          tag_type  TEXT NOT NULL CHECK(tag_type IN ('person', 'topic', 'project')),
          source    TEXT NOT NULL CHECK(source IN ('auto', 'manual')),
          PRIMARY KEY (stem, tag_name, tag_type)
        );

        CREATE TABLE IF NOT EXISTS inbox_proposals (
          stem               TEXT PRIMARY KEY,
          proposed_subdir    TEXT NOT NULL,
          proposed_tags_json TEXT NOT NULL,
          status             TEXT NOT NULL CHECK(status IN ('transcribing', 'analyzing', 'ready', 'error')),
          error_message      TEXT,
          created_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS meeting_tags_by_tag ON meeting_tags(tag_name, tag_type);
        """)


def _tags_to_json(tags: list[Tag]) -> str:
    return json.dumps([{"name": t.name, "type": t.type} for t in tags])


def _tags_from_json(s: str) -> list[Tag]:
    return [Tag(name=t["name"], type=t["type"]) for t in json.loads(s)]


def save_proposal(
    stem: str,
    proposed_subdir: str,
    proposed_tags: list[Tag],
    status: str,
    error_message: str | None,
) -> None:
    with connect() as c:
        c.execute(
            """
            INSERT INTO inbox_proposals (stem, proposed_subdir, proposed_tags_json, status, error_message)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(stem) DO UPDATE SET
              proposed_subdir    = excluded.proposed_subdir,
              proposed_tags_json = excluded.proposed_tags_json,
              status             = excluded.status,
              error_message      = excluded.error_message
            """,
            (stem, proposed_subdir, _tags_to_json(proposed_tags), status, error_message),
        )


def update_proposal_status(stem: str, status: str, error_message: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE inbox_proposals SET status = ?, error_message = ? WHERE stem = ?",
            (status, error_message, stem),
        )


def get_proposal(stem: str) -> Proposal | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM inbox_proposals WHERE stem = ?", (stem,)
        ).fetchone()
    if row is None:
        return None
    return Proposal(
        stem=row["stem"],
        proposed_subdir=row["proposed_subdir"],
        proposed_tags=_tags_from_json(row["proposed_tags_json"]),
        status=row["status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def list_pending_proposals() -> list[Proposal]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM inbox_proposals ORDER BY created_at ASC"
        ).fetchall()
    return [
        Proposal(
            stem=r["stem"],
            proposed_subdir=r["proposed_subdir"],
            proposed_tags=_tags_from_json(r["proposed_tags_json"]),
            status=r["status"],
            error_message=r["error_message"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def delete_proposal(stem: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM inbox_proposals WHERE stem = ?", (stem,))


def set_meeting_tags(stem: str, tags: list[Tag], source: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM meeting_tags WHERE stem = ?", (stem,))
        c.executemany(
            "INSERT INTO meeting_tags (stem, tag_name, tag_type, source) VALUES (?, ?, ?, ?)",
            [(stem, t.name, t.type, source) for t in tags],
        )


def list_meeting_tags(stem: str) -> list[Tag]:
    with connect() as c:
        rows = c.execute(
            "SELECT tag_name, tag_type FROM meeting_tags WHERE stem = ? ORDER BY tag_type, tag_name",
            (stem,),
        ).fetchall()
    return [Tag(name=r["tag_name"], type=r["tag_type"]) for r in rows]


def list_stems_with_tag(tag_name: str, tag_type: str) -> list[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT stem FROM meeting_tags WHERE tag_name = ? AND tag_type = ?",
            (tag_name, tag_type),
        ).fetchall()
    return [r["stem"] for r in rows]
