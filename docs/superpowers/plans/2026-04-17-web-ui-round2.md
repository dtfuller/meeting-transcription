# Web UI Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a directory watcher that auto-ingests new recordings into `data/_inbox/`, runs the pipeline, and proposes a routing subdir + tags via Claude; the user approves in a new Inbox tab, and tags persist in SQLite for display/filter in the Meetings tab. Per `docs/superpowers/specs/2026-04-17-web-ui-round2-design.md`.

**Architecture:** All new code lives in `app/` alongside the Round 1 modules. State that doesn't come from the filesystem (tags, pending proposals) goes into a single SQLite DB at `<repo>/ui.db`. The watcher (`watchdog.PollingObserver`) runs as a background thread inside the FastAPI process, kicks `app/ingest.py`, which reuses the existing `PipelineRunner`. Templates and routes follow the Round 1 patterns (HTMX + Starlette 1.0 `TemplateResponse(request, "name.html", {...})` signature).

**Tech Stack:** Python 3.11 · FastAPI · Jinja2 · HTMX · sqlite3 (stdlib) · watchdog · anthropic SDK · pytest + httpx.

---

## File structure

**New files:**

```
app/
  store.py                # sqlite wrapper (connect, init_schema, tag + proposal CRUD)
  watcher.py              # PollingObserver wrapper with stability heuristic
  ingest.py               # IngestCoordinator: copy → pipeline → categorize → proposal
  categorize.py           # Claude-powered (subdir, tags) proposer
  routes/
    inbox.py              # GET /inbox, POST apply/dismiss/watcher-toggle
templates/
  inbox.html              # tab page
  _inbox_card.html        # one card per proposal
tests/
  test_store.py
  test_watcher.py
  test_ingest.py
  test_categorize.py
  test_routes_inbox.py
  helpers/
    fake_anthropic.py     # drop-in stub Anthropic client
```

**Modified:**

- `app/fs.py` — add `include_inbox` param to `list_meetings`, add `is_inbox` property on `Meeting`.
- `app/routes/meetings.py` — pass `include_inbox=False`; render tag chips; add `POST /meetings/{subdir}/{stem}/tags`; support `?tag=` filter on the tree.
- `app/routes/speakers.py`, `app/routes/pipeline_routes.py` — add `inbox_count` to every context dict.
- `templates/base.html` — fourth tab.
- `templates/_meeting_tree.html` — tag chips next to each row.
- `templates/_meeting_detail.html` — Tags section below subtabs.
- `server.py` — `store.init_schema()` on startup; optional watcher startup if `WATCH_DIR` is set; watcher shutdown on server stop.
- `static/app.css` — chip, spinner, status pill, inbox card styles.
- `requirements.txt` — add `watchdog>=4.0`.
- `.gitignore` — add `ui.db`, `ui.db-journal`.
- `.env.example` — add `WATCH_DIR=` placeholder.
- `CLAUDE.md` — append Round 2 subsection under the existing "Web UI (Round 1)" section.

**Unchanged:** `transcribe.py`, `extract.py`, `process.py`, `app/pipeline.py`, `app/clips.py`, `app/video.py`, `app/markdown.py`, all Round 1 tests.

---

## Critical conventions

- **DB path:** `app/store.py` exposes `DB_PATH = Path(__file__).parent.parent / "ui.db"`. Tests monkeypatch this to `tmp_path / "ui.db"`.
- **Meeting identity:** stem only (filename minus `.mov`). Tags and proposals key off stem. `(subdir, stem)` pairs only appear in URLs.
- **Starlette 1.0 TemplateResponse signature:** all new routes use `TemplateResponse(request, "name.html", {...})` — `request` as first positional, never in the context dict. Consistent with Round 1 code.
- **`fs.DATA_DIR.parent` pattern for the repo-root subprocess cwd:** reused for `process.py` invocation so tests that monkeypatch `fs.DATA_DIR` work. Same pattern as `app/routes/meetings.py` and `pipeline_routes.py`.
- **Inbox subdir literal:** `INBOX_SUBDIR = "_inbox"` constant in `app/store.py` (imported where needed). Filesystem paths are computed with this constant, never typed inline.
- **Tag dataclass:** `@dataclass(frozen=True) class Tag: name: str; type: str` in `app/store.py`. `type` ∈ `{"person", "topic", "project"}`.
- **Proposal dataclass:** `@dataclass(frozen=True) class Proposal: stem: str; proposed_subdir: str; proposed_tags: list[Tag]; status: str; error_message: str | None; created_at: str`.

---

## Task 1: SQLite store (`app/store.py`) + schema + tag/proposal CRUD

**Files:**
- Create: `app/store.py`, `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_store.py`:

```python
import json
from pathlib import Path

import pytest

from app import store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    yield


def test_init_schema_is_idempotent():
    # Second call should not raise
    store.init_schema()
    store.init_schema()


def test_save_and_get_proposal():
    tags = [store.Tag(name="Darwin Henao", type="person"),
            store.Tag(name="multiturbo", type="topic")]
    store.save_proposal(
        stem="2026-04-16 17-01-16",
        proposed_subdir="multiturbo",
        proposed_tags=tags,
        status="ready",
        error_message=None,
    )
    p = store.get_proposal("2026-04-16 17-01-16")
    assert p is not None
    assert p.stem == "2026-04-16 17-01-16"
    assert p.proposed_subdir == "multiturbo"
    assert p.proposed_tags == tags
    assert p.status == "ready"
    assert p.error_message is None


def test_save_proposal_upsert():
    store.save_proposal(stem="s", proposed_subdir="a", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.save_proposal(stem="s", proposed_subdir="b", proposed_tags=[],
                        status="ready", error_message=None)
    p = store.get_proposal("s")
    assert p.proposed_subdir == "b"
    assert p.status == "ready"


def test_update_proposal_status():
    store.save_proposal(stem="s", proposed_subdir="", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.update_proposal_status("s", "error", "transcribe failed")
    p = store.get_proposal("s")
    assert p.status == "error"
    assert p.error_message == "transcribe failed"


def test_list_pending_proposals_ordered_by_created_at():
    store.save_proposal(stem="a", proposed_subdir="", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.save_proposal(stem="b", proposed_subdir="", proposed_tags=[],
                        status="ready", error_message=None)
    ps = store.list_pending_proposals()
    stems = [p.stem for p in ps]
    assert set(stems) == {"a", "b"}


def test_delete_proposal():
    store.save_proposal(stem="s", proposed_subdir="", proposed_tags=[],
                        status="ready", error_message=None)
    assert store.get_proposal("s") is not None
    store.delete_proposal("s")
    assert store.get_proposal("s") is None


def test_set_and_list_meeting_tags():
    tags = [store.Tag(name="Darwin Henao", type="person"),
            store.Tag(name="multiturbo", type="topic")]
    store.set_meeting_tags("stem-1", tags, source="manual")
    out = store.list_meeting_tags("stem-1")
    assert set(out) == set(tags)


def test_set_meeting_tags_replaces():
    store.set_meeting_tags("stem-1",
                           [store.Tag(name="A", type="topic")],
                           source="auto")
    store.set_meeting_tags("stem-1",
                           [store.Tag(name="B", type="topic")],
                           source="manual")
    out = store.list_meeting_tags("stem-1")
    assert out == [store.Tag(name="B", type="topic")]


def test_list_stems_with_tag():
    store.set_meeting_tags("m1", [store.Tag(name="Darwin Henao", type="person")],
                           source="manual")
    store.set_meeting_tags("m2", [store.Tag(name="Darwin Henao", type="person")],
                           source="manual")
    store.set_meeting_tags("m3", [store.Tag(name="Alice", type="person")],
                           source="manual")
    stems = store.list_stems_with_tag("Darwin Henao", "person")
    assert set(stems) == {"m1", "m2"}


def test_inbox_subdir_constant():
    assert store.INBOX_SUBDIR == "_inbox"
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/test_store.py -v`
Expected: ModuleNotFoundError / collection error.

- [ ] **Step 3: Implement `app/store.py`**

Create `app/store.py`:

```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_store.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat(ui): sqlite store for tags + inbox proposals"
```

---

## Task 2: `app/fs.py` — `include_inbox` parameter + `is_inbox`

**Files:**
- Modify: `app/fs.py`, `tests/test_fs.py`

- [ ] **Step 1: Write failing tests (append to `tests/test_fs.py`)**

Add at the end of `tests/test_fs.py`:

```python
def test_list_meetings_excludes_inbox_by_default(tree):
    (tree / "data" / "_inbox").mkdir()
    (tree / "data" / "_inbox" / "2026-04-17 22-00-00.mov").write_bytes(b"\x00")
    meetings = fs.list_meetings()
    keys = [(m.subdir, m.stem) for m in meetings]
    assert ("_inbox", "2026-04-17 22-00-00") not in keys


def test_list_meetings_includes_inbox_when_asked(tree):
    (tree / "data" / "_inbox").mkdir()
    (tree / "data" / "_inbox" / "2026-04-17 22-00-00.mov").write_bytes(b"\x00")
    meetings = fs.list_meetings(include_inbox=True)
    keys = [(m.subdir, m.stem) for m in meetings]
    assert ("_inbox", "2026-04-17 22-00-00") in keys


def test_meeting_is_inbox_property(tree):
    (tree / "data" / "_inbox").mkdir()
    (tree / "data" / "_inbox" / "stem-x.mov").write_bytes(b"\x00")
    m = fs.find_meeting("_inbox", "stem-x")
    assert m is not None
    assert m.is_inbox

    m2 = fs.find_meeting("multiturbo", "2026-04-14 17-00-43")
    assert not m2.is_inbox
```

- [ ] **Step 2: Run — expect 3 failures**

Run: `pytest tests/test_fs.py -v`
Expected: the three new tests fail.

- [ ] **Step 3: Update `app/fs.py`**

Add the `is_inbox` property inside the `Meeting` dataclass (place it near the other `@property` methods):

```python
    @property
    def is_inbox(self) -> bool:
        return self.subdir == "_inbox"
```

Change the `list_meetings` signature and body. Replace the existing function with:

```python
def list_meetings(include_inbox: bool = False) -> list[Meeting]:
    if not DATA_DIR.exists():
        return []
    meetings = (_meeting_from_mov(p) for p in DATA_DIR.rglob("*.mov"))
    if not include_inbox:
        meetings = (m for m in meetings if m.subdir != "_inbox")
    return sorted(meetings, key=lambda m: (m.subdir, m.stem))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fs.py -v`
Expected: 9 passed (6 original + 3 new).

Full suite: `pytest -v`
Expected: 46 passed (43 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add app/fs.py tests/test_fs.py
git commit -m "feat(ui): fs.list_meetings(include_inbox=) + Meeting.is_inbox"
```

---

## Task 3: Categorize (`app/categorize.py`) + fake Anthropic helper

**Files:**
- Create: `app/categorize.py`, `tests/helpers/fake_anthropic.py`, `tests/test_categorize.py`

- [ ] **Step 1: Fake Anthropic helper**

Create `tests/helpers/fake_anthropic.py`:

```python
"""Minimal drop-in stub for the anthropic.Anthropic client used by app/categorize.py.

Returns a canned text response. Tests inject one of these via dependency.
"""
from dataclasses import dataclass


@dataclass
class _Block:
    text: str


@dataclass
class _Message:
    content: list

    def __post_init__(self):
        if not isinstance(self.content, list):
            self.content = [self.content]


class FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Message(content=[_Block(text=self._text)])


class FakeAnthropic:
    def __init__(self, text: str):
        self.messages = FakeMessages(text)
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_categorize.py`:

```python
import json

import pytest

from app import categorize, store
from tests.helpers.fake_anthropic import FakeAnthropic


def test_propose_returns_subdir_and_tags():
    fake_json = json.dumps({
        "subdir": "multiturbo",
        "tags": [
            {"name": "Darwin Henao", "type": "person"},
            {"name": "multiturbo", "type": "topic"},
            {"name": "2026 Q2 roadmap", "type": "project"},
        ],
    })
    client = FakeAnthropic(text=fake_json)

    proposal = categorize.propose(
        transcript="[00:00:15 Darwin Henao] hola",
        knowledge="# Knowledge\nmultiturbo status...",
        commitments="# Commitments\nDarwin owns X",
        existing_subdirs=["multiturbo", "check-in"],
        known_names=["Darwin Henao", "David Fuller"],
        client=client,
    )
    assert proposal.subdir == "multiturbo"
    assert len(proposal.tags) == 3
    assert store.Tag(name="Darwin Henao", type="person") in proposal.tags


def test_propose_wraps_response_in_xml_when_no_json():
    fake_json = '<response>' + json.dumps({"subdir": "foo", "tags": []}) + '</response>'
    client = FakeAnthropic(text=fake_json)
    proposal = categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=[], known_names=[],
        client=client,
    )
    assert proposal.subdir == "foo"
    assert proposal.tags == []


def test_propose_strips_unknown_tag_types():
    fake_json = json.dumps({
        "subdir": "x",
        "tags": [
            {"name": "keep", "type": "person"},
            {"name": "drop", "type": "weird"},
        ],
    })
    client = FakeAnthropic(text=fake_json)
    proposal = categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=[], known_names=[],
        client=client,
    )
    names = [t.name for t in proposal.tags]
    assert "keep" in names
    assert "drop" not in names


def test_propose_sends_existing_subdirs_in_prompt():
    client = FakeAnthropic(text=json.dumps({"subdir": "x", "tags": []}))
    categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=["multiturbo", "check-in"],
        known_names=["Darwin Henao"],
        client=client,
    )
    kwargs = client.messages.last_kwargs
    user_msg = kwargs["messages"][0]["content"]
    assert "multiturbo" in user_msg
    assert "check-in" in user_msg
    assert "Darwin Henao" in user_msg
```

- [ ] **Step 3: Run — expect ImportError / failures**

Run: `pytest tests/test_categorize.py -v`

- [ ] **Step 4: Implement `app/categorize.py`**

Create `app/categorize.py`:

```python
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from app.store import Tag

_VALID_TAG_TYPES = {"person", "topic", "project"}
CATEGORIZE_MODEL = "claude-opus-4-6"
SYSTEM_PROMPT = (
    "You classify a meeting transcript. Return ONLY a JSON object with keys:\n"
    '  "subdir": string — pick one from the given list, or invent a short '
    "slug-case name if none fit.\n"
    '  "tags": array of {"name": string, "type": "person"|"topic"|"project"}.\n'
    "Include every person clearly named in the transcript (prefer full names). "
    "Include topic tags for the main subject(s). Include project tags only when a "
    "project name is explicitly referenced. Return no prose outside the JSON."
)


@dataclass(frozen=True)
class CategorizeProposal:
    subdir: str
    tags: list[Tag]


def _build_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def propose(
    transcript: str,
    knowledge: str,
    commitments: str,
    existing_subdirs: list[str],
    known_names: list[str],
    client=None,
) -> CategorizeProposal:
    if client is None:
        client = _build_client()

    subdirs_list = ", ".join(existing_subdirs) if existing_subdirs else "(none)"
    known_list = ", ".join(known_names) if known_names else "(none)"

    user_msg = (
        f"Existing subdirs: {subdirs_list}\n"
        f"Known speakers already in the voiceprint library: {known_list}\n\n"
        f"## Transcript\n{transcript[:8000]}\n\n"
        f"## Knowledge\n{knowledge}\n\n"
        f"## Commitments\n{commitments}\n"
    )

    response = client.messages.create(
        model=CATEGORIZE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    data = _extract_json(text)
    subdir = str(data.get("subdir", "")).strip()
    raw_tags = data.get("tags", []) or []
    tags: list[Tag] = []
    for t in raw_tags:
        try:
            name = str(t["name"]).strip()
            ttype = str(t["type"]).strip()
        except (KeyError, TypeError):
            continue
        if not name or ttype not in _VALID_TAG_TYPES:
            continue
        tags.append(Tag(name=name, type=ttype))
    return CategorizeProposal(subdir=subdir, tags=tags)


def _extract_json(text: str) -> dict:
    # Strip optional <response>...</response> wrapper
    match = re.search(r"<response>(.*?)</response>", text, re.DOTALL)
    if match:
        text = match.group(1)
    # Find the outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_categorize.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/categorize.py tests/helpers/fake_anthropic.py tests/test_categorize.py
git commit -m "feat(ui): Claude-powered subdir + tag proposer (app/categorize.py)"
```

---

## Task 4: Ingest coordinator (`app/ingest.py`)

**Files:**
- Create: `app/ingest.py`, `tests/test_ingest.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_ingest.py`:

```python
import sys
import time
from pathlib import Path

import pytest

from app import fs, ingest, pipeline, store
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()
    monkeypatch.setattr(
        ingest,
        "_PIPELINE_ARGV_BUILDER",
        lambda inbox_path: [sys.executable, str(HELPER)],
    )
    monkeypatch.setattr(
        ingest,
        "_run_categorize",
        lambda stem: None,  # skip LLM during ingest tests
    )
    yield
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()


def _write_mov(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 32)


def test_on_new_file_copies_to_inbox_and_saves_pending_proposal(tmp_path):
    src = tmp_path / "external" / "new-meeting.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)

    inbox_path = fs.DATA_DIR / "_inbox" / "new-meeting.mov"
    assert inbox_path.exists()
    assert store.get_proposal("new-meeting") is not None


def test_pipeline_kicks_off_and_proposal_reaches_ready(tmp_path):
    src = tmp_path / "external" / "m.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    p = store.get_proposal("m")
    assert p is not None
    assert p.status == "ready"
    assert p.error_message is None


def test_skips_duplicate_file(tmp_path):
    src = tmp_path / "external" / "dup.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    # Second call should no-op since data/_inbox/dup.mov now exists
    ingest.get_coordinator().on_new_file(src)
    # Pipeline should NOT re-run
    assert not pipeline.get_runner().is_running()


def test_concurrent_ingest_queues_second_file(tmp_path, monkeypatch):
    # First pipeline is long; second should queue and run after
    monkeypatch.setattr(
        ingest,
        "_PIPELINE_ARGV_BUILDER",
        lambda inbox_path: [sys.executable, "-c", "import time; time.sleep(0.3)"],
    )
    a = tmp_path / "external" / "a.mov"
    b = tmp_path / "external" / "b.mov"
    _write_mov(a); _write_mov(b)

    ingest.get_coordinator().on_new_file(a)
    ingest.get_coordinator().on_new_file(b)

    # Wait for both to finish
    for _ in range(400):
        if (not pipeline.get_runner().is_running()
                and store.get_proposal("a")
                and store.get_proposal("b")
                and store.get_proposal("a").status == "ready"
                and store.get_proposal("b").status == "ready"):
            break
        time.sleep(0.05)

    assert store.get_proposal("a").status == "ready"
    assert store.get_proposal("b").status == "ready"
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/test_ingest.py -v`

- [ ] **Step 3: Implement `app/ingest.py`**

Create `app/ingest.py`:

```python
from __future__ import annotations

import shutil
import sys
import threading
from collections import deque
from pathlib import Path

from app import categorize, fs, pipeline, store

ROOT = Path(__file__).parent.parent
PROCESS_PY = ROOT / "process.py"


def _default_argv_builder(inbox_path: Path) -> list[str]:
    # process.py receives a path relative to repo root
    data_root = fs.DATA_DIR.parent
    rel = inbox_path.relative_to(data_root)
    return [sys.executable, str(PROCESS_PY), str(rel)]


# Module-level indirection lets tests monkeypatch without breaking production
_PIPELINE_ARGV_BUILDER = _default_argv_builder


def _run_categorize(stem: str) -> None:
    """Overridable so tests can skip network. Default: run Claude."""
    m = fs.find_meeting(store.INBOX_SUBDIR, stem)
    if m is None:
        store.update_proposal_status(stem, "error", "meeting file disappeared")
        return
    try:
        existing_subdirs = sorted(
            {mm.subdir for mm in fs.list_meetings() if mm.subdir and mm.subdir != store.INBOX_SUBDIR}
        )
        result = categorize.propose(
            transcript=fs.load_transcript(m),
            knowledge=fs.load_knowledge(m),
            commitments=fs.load_commitments(m),
            existing_subdirs=existing_subdirs,
            known_names=fs.list_known_names(),
        )
        store.save_proposal(
            stem=stem,
            proposed_subdir=result.subdir,
            proposed_tags=result.tags,
            status="ready",
            error_message=None,
        )
    except Exception as e:
        store.update_proposal_status(stem, "error", f"categorize failed: {e}")


class IngestCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._queue: deque[tuple[Path, str]] = deque()
        self._in_flight_stem: str | None = None

    def reset_for_tests(self) -> None:
        with self._lock:
            self._queue.clear()
            self._in_flight_stem = None

    def on_new_file(self, external_path: Path) -> None:
        stem = external_path.stem
        inbox_dir = fs.DATA_DIR / store.INBOX_SUBDIR
        inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_path = inbox_dir / f"{stem}.mov"
        if inbox_path.exists():
            return  # already ingested
        shutil.copy2(external_path, inbox_path)
        store.save_proposal(
            stem=stem,
            proposed_subdir="",
            proposed_tags=[],
            status="transcribing",
            error_message=None,
        )
        with self._lock:
            self._queue.append((inbox_path, stem))
        self._maybe_start_next()

    def _maybe_start_next(self) -> None:
        with self._lock:
            if self._in_flight_stem is not None:
                return
            if not self._queue:
                return
            inbox_path, stem = self._queue.popleft()
            self._in_flight_stem = stem

        argv = _PIPELINE_ARGV_BUILDER(inbox_path)
        runner = pipeline.get_runner()
        runner.set_on_complete(self._on_pipeline_done)
        try:
            runner.start(argv, cwd=str(ROOT))
        except pipeline.AlreadyRunning:
            # Put back in queue, reset in-flight, and try again next time
            with self._lock:
                self._queue.appendleft((inbox_path, stem))
                self._in_flight_stem = None

    def _on_pipeline_done(self, argv: list[str], rc: int) -> None:
        stem = self._in_flight_stem
        if stem is not None:
            if rc != 0:
                store.update_proposal_status(stem, "error", f"pipeline exit {rc}")
            else:
                store.update_proposal_status(stem, "analyzing", None)
                _run_categorize(stem)
        with self._lock:
            self._in_flight_stem = None
        self._maybe_start_next()


_coordinator: IngestCoordinator | None = None


def get_coordinator() -> IngestCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = IngestCoordinator()
    return _coordinator
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ingest.py -v`
Expected: 4 passed.

Full suite: `pytest -v`
Expected: 60 passed (46 prior + 10 store + 4 categorize — wait, also 4 ingest). 46 + 10 + 4 + 4 = 64. Confirm via the actual count.

- [ ] **Step 5: Commit**

```bash
git add app/ingest.py tests/test_ingest.py
git commit -m "feat(ui): IngestCoordinator — copy to _inbox, kick pipeline, run categorize, queue concurrent ingests"
```

---

## Task 5: Watcher (`app/watcher.py`)

**Files:**
- Create: `app/watcher.py`, `tests/test_watcher.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add watchdog dep**

Append to `requirements.txt`:

```
watchdog>=4.0
```

Run: `pip install watchdog`

- [ ] **Step 2: Failing tests**

Create `tests/test_watcher.py`:

```python
import time
from pathlib import Path
from threading import Event

import pytest

from app import watcher


def _wait_for(pred, timeout=3.0):
    start = time.time()
    while time.time() - start < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_start_detects_new_mov(tmp_path):
    received: list[Path] = []
    event = Event()

    def on_new(p: Path):
        received.append(p)
        event.set()

    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        target = tmp_path / "meeting.mov"
        target.write_bytes(b"\x00" * 16)
        assert _wait_for(lambda: len(received) > 0, timeout=3.0)
        assert received[0].name == "meeting.mov"
    finally:
        w.stop()


def test_ignores_non_mov(tmp_path):
    received: list[Path] = []

    def on_new(p: Path):
        received.append(p)

    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        (tmp_path / "notes.txt").write_text("hi")
        time.sleep(0.6)
        assert received == []
    finally:
        w.stop()


def test_waits_until_file_is_stable(tmp_path):
    received: list[Path] = []

    def on_new(p: Path):
        received.append(p)

    w = watcher.Watcher(stability_seconds=0.4, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        target = tmp_path / "growing.mov"
        target.write_bytes(b"\x00" * 16)
        # Mutate for 0.5s so the 0.4s stability window restarts each write
        for _ in range(4):
            time.sleep(0.15)
            with target.open("ab") as f:
                f.write(b"\x01" * 16)
        # Now let it stabilize
        assert _wait_for(lambda: len(received) > 0, timeout=3.0)
    finally:
        w.stop()


def test_status_reflects_running_state(tmp_path):
    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    assert not w.is_running()
    w.start(tmp_path, lambda p: None)
    try:
        assert w.is_running()
    finally:
        w.stop()
    assert not w.is_running()
```

- [ ] **Step 3: Run — expect ImportError**

Run: `pytest tests/test_watcher.py -v`

- [ ] **Step 4: Implement `app/watcher.py`**

Create `app/watcher.py`:

```python
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver


class _Handler(FileSystemEventHandler):
    def __init__(self, on_event: Callable[[Path], None]):
        self._on_event = on_event

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() == ".mov":
            self._on_event(p)

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() == ".mov":
            self._on_event(p)


class Watcher:
    def __init__(self, stability_seconds: float = 3.0, poll_interval: float = 1.0):
        self._stability_seconds = stability_seconds
        self._poll_interval = poll_interval
        self._observer: PollingObserver | None = None
        self._watch_dir: Path | None = None
        self._pending: dict[Path, float] = {}
        self._fired: set[Path] = set()
        self._pending_lock = threading.Lock()
        self._timer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._callback: Callable[[Path], None] | None = None

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    def status(self) -> dict:
        return {
            "is_running": self.is_running(),
            "watch_dir": str(self._watch_dir) if self._watch_dir else None,
        }

    def start(self, watch_dir: Path, on_new_file: Callable[[Path], None]) -> None:
        if self.is_running():
            return
        watch_dir = Path(watch_dir).resolve()
        watch_dir.mkdir(parents=True, exist_ok=True)
        self._watch_dir = watch_dir
        self._callback = on_new_file
        self._pending.clear()
        self._fired.clear()
        self._stop_event.clear()

        handler = _Handler(self._schedule)
        self._observer = PollingObserver(timeout=self._poll_interval)
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()

        self._timer_thread = threading.Thread(target=self._stability_loop, daemon=True)
        self._timer_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
        self._observer = None
        self._watch_dir = None

    def _schedule(self, path: Path) -> None:
        with self._pending_lock:
            if path in self._fired:
                return
            self._pending[path] = time.monotonic()

    def _stability_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            now = time.monotonic()
            ready: list[Path] = []
            with self._pending_lock:
                for p, last in list(self._pending.items()):
                    try:
                        mtime = p.stat().st_mtime
                    except FileNotFoundError:
                        del self._pending[p]
                        continue
                    age = now - last
                    # Update last-seen timestamp to whichever is more recent
                    # (handles fast successive modifies)
                    fresh_last = max(last, mtime if mtime > last else last)
                    if now - fresh_last >= self._stability_seconds:
                        ready.append(p)
                        del self._pending[p]
                        self._fired.add(p)
                    else:
                        self._pending[p] = fresh_last
            for p in ready:
                try:
                    if self._callback is not None:
                        self._callback(p)
                except Exception:
                    pass
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_watcher.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/watcher.py tests/test_watcher.py requirements.txt
git commit -m "feat(ui): PollingObserver-based watcher with stability heuristic"
```

---

## Task 6: Server wiring (schema init + optional watcher startup)

**Files:**
- Modify: `server.py`, `.env.example`, `.gitignore`

- [ ] **Step 1: Add gitignore + env example entries**

Append to `.gitignore`:

```
# Web UI SQLite DB
ui.db
ui.db-journal
```

Append to `.env.example`:

```
WATCH_DIR=
```

- [ ] **Step 2: Update `server.py`**

Replace the contents of `server.py` with:

```python
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import ingest, store, watcher

ROOT = Path(__file__).parent

load_dotenv()

_watcher: watcher.Watcher | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    store.init_schema()

    from app.routes import meetings, speakers, pipeline_routes, media, inbox
    app.include_router(meetings.router)
    app.include_router(speakers.router)
    app.include_router(pipeline_routes.router)
    app.include_router(media.router)
    app.include_router(inbox.router)

    @app.on_event("startup")
    def _start_watcher():
        global _watcher
        watch_dir = os.getenv("WATCH_DIR")
        if not watch_dir:
            return
        _watcher = watcher.Watcher()
        _watcher.start(Path(watch_dir), ingest.get_coordinator().on_new_file)

    @app.on_event("shutdown")
    def _stop_watcher():
        global _watcher
        if _watcher is not None:
            _watcher.stop()
            _watcher = None

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def root():
        return RedirectResponse("/meetings", status_code=302)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
```

- [ ] **Step 3: Run the smoke tests to ensure nothing regressed**

Run: `pytest tests/test_smoke.py -v`
Expected: 2 passed.

Note: the FastAPI `TestClient` does not trigger `on_event` handlers in all versions; the watcher may or may not auto-start in tests. That's fine — inbox route tests will exercise the coordinator directly.

- [ ] **Step 4: Commit**

```bash
git add server.py .gitignore .env.example
git commit -m "feat(ui): server wires store schema + optional WATCH_DIR watcher startup"
```

---

## Task 7: Inbox routes (`app/routes/inbox.py`)

**Files:**
- Create: `app/routes/inbox.py`, `tests/test_routes_inbox.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_routes_inbox.py`:

```python
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs, ingest, pipeline, store
from server import create_app
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()
    yield TestClient(create_app())
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()


def _seed_proposal(stem: str, subdir: str, tags, status="ready"):
    store.save_proposal(
        stem=stem,
        proposed_subdir=subdir,
        proposed_tags=tags,
        status=status,
        error_message=None,
    )
    # Also drop a fake inbox .mov so routing can find it
    inbox_mov = fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov"
    inbox_mov.parent.mkdir(parents=True, exist_ok=True)
    inbox_mov.write_bytes(b"\x00" * 16)
    (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt").parent.mkdir(parents=True, exist_ok=True)
    (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt").write_text("[00:00:00 X] hi\n")
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md").parent.mkdir(parents=True, exist_ok=True)
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md").write_text("# K")
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-commitments.md").write_text("# C")


def test_inbox_index_lists_proposals(client):
    _seed_proposal("stem-a", "multiturbo",
                   [store.Tag(name="Darwin Henao", type="person")])
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "stem-a" in r.text
    assert "multiturbo" in r.text
    assert "Darwin Henao" in r.text


def test_inbox_apply_moves_files_and_saves_tags(client):
    _seed_proposal("m-1", "multiturbo",
                   [store.Tag(name="Darwin Henao", type="person")])
    r = client.post(
        "/inbox/m-1/apply",
        data={
            "target_subdir": "multiturbo",
            "tag_name": ["Darwin Henao", "multiturbo"],
            "tag_type": ["person", "topic"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/meetings/multiturbo/m-1"

    # Files moved
    assert (fs.DATA_DIR / "multiturbo" / "m-1.mov").exists()
    assert not (fs.DATA_DIR / "_inbox" / "m-1.mov").exists()
    assert (fs.TRANSCRIPTS_DIR / "multiturbo" / "m-1.txt").exists()
    assert (fs.INFORMATION_DIR / "multiturbo" / "m-1-knowledge.md").exists()
    assert (fs.INFORMATION_DIR / "multiturbo" / "m-1-commitments.md").exists()

    # Proposal deleted
    assert store.get_proposal("m-1") is None

    # Tags saved
    tags = store.list_meeting_tags("m-1")
    names = {t.name for t in tags}
    assert names == {"Darwin Henao", "multiturbo"}


def test_inbox_apply_creates_new_subdir_if_needed(client):
    _seed_proposal("m-2", "", [])
    r = client.post(
        "/inbox/m-2/apply",
        data={"target_subdir": "brand-new-category",
              "tag_name": [], "tag_type": []},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert (fs.DATA_DIR / "brand-new-category" / "m-2.mov").exists()


def test_inbox_apply_404_on_unknown_stem(client):
    r = client.post(
        "/inbox/ghost/apply",
        data={"target_subdir": "whatever", "tag_name": [], "tag_type": []},
    )
    assert r.status_code == 404


def test_inbox_dismiss_removes_proposal_without_moving_files(client):
    _seed_proposal("m-3", "multiturbo", [])
    r = client.post("/inbox/m-3/dismiss", follow_redirects=False)
    assert r.status_code == 303
    assert store.get_proposal("m-3") is None
    # Files untouched
    assert (fs.DATA_DIR / "_inbox" / "m-3.mov").exists()


def test_watcher_status_endpoints(client):
    r = client.get("/watcher/status")
    assert r.status_code == 200
    assert r.json()["is_running"] in (True, False)
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/test_routes_inbox.py -v`

- [ ] **Step 3: Implement `app/routes/inbox.py`**

Create `app/routes/inbox.py`:

```python
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import fs, ingest, store, watcher as watcher_mod

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent

# Shared watcher instance used by the lifecycle endpoints. server.py's startup
# hook also installs one; when that is present, /watcher/start is a no-op.
_shared_watcher: watcher_mod.Watcher | None = None


def _existing_subdirs() -> list[str]:
    return sorted({m.subdir for m in fs.list_meetings()
                   if m.subdir and m.subdir != store.INBOX_SUBDIR})


@router.get("/inbox")
def inbox_index(request: Request):
    proposals = store.list_pending_proposals()
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "active_tab": "inbox",
            "proposals": proposals,
            "existing_subdirs": _existing_subdirs(),
            "speakers_count": len(fs.list_unknown_clips()),
            "pipeline_running": False,  # Task 9 propagates the live value everywhere
            "inbox_count": len(proposals),
            "watcher_enabled": bool(os.getenv("WATCH_DIR")),
        },
    )


@router.post("/inbox/{stem}/apply")
def inbox_apply(
    stem: str,
    target_subdir: Annotated[str, Form()],
    tag_name: Annotated[list[str], Form()] = [],
    tag_type: Annotated[list[str], Form()] = [],
):
    proposal = store.get_proposal(stem)
    if proposal is None:
        raise HTTPException(status_code=404)

    target_subdir = target_subdir.strip()
    if not target_subdir:
        raise HTTPException(status_code=400, detail="target_subdir is required")

    # Move files from _inbox into target
    moves = [
        (fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov",
         fs.DATA_DIR / target_subdir / f"{stem}.mov"),
        (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt",
         fs.TRANSCRIPTS_DIR / target_subdir / f"{stem}.txt"),
        (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md",
         fs.INFORMATION_DIR / target_subdir / f"{stem}-knowledge.md"),
        (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-commitments.md",
         fs.INFORMATION_DIR / target_subdir / f"{stem}-commitments.md"),
    ]
    for src, dst in moves:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    # Save tags
    tags = []
    for n, t in zip(tag_name, tag_type):
        n = (n or "").strip()
        t = (t or "").strip()
        if n and t in ("person", "topic", "project"):
            tags.append(store.Tag(name=n, type=t))
    store.set_meeting_tags(stem, tags, source="auto" if proposal.proposed_subdir else "manual")

    store.delete_proposal(stem)
    return RedirectResponse(f"/meetings/{target_subdir}/{stem}", status_code=303)


@router.post("/inbox/{stem}/dismiss")
def inbox_dismiss(stem: str):
    if store.get_proposal(stem) is None:
        raise HTTPException(status_code=404)
    store.delete_proposal(stem)
    return RedirectResponse("/inbox", status_code=303)


@router.post("/watcher/start")
def watcher_start():
    global _shared_watcher
    watch_dir = os.getenv("WATCH_DIR")
    if not watch_dir:
        raise HTTPException(status_code=400, detail="WATCH_DIR not set in environment")
    if _shared_watcher is None:
        _shared_watcher = watcher_mod.Watcher()
    if not _shared_watcher.is_running():
        _shared_watcher.start(Path(watch_dir), ingest.get_coordinator().on_new_file)
    return JSONResponse(_shared_watcher.status())


@router.post("/watcher/stop")
def watcher_stop():
    global _shared_watcher
    if _shared_watcher is not None and _shared_watcher.is_running():
        _shared_watcher.stop()
    return JSONResponse({"is_running": False, "watch_dir": None})


@router.get("/watcher/status")
def watcher_status():
    global _shared_watcher
    if _shared_watcher is None:
        return JSONResponse({"is_running": False, "watch_dir": None})
    return JSONResponse(_shared_watcher.status())
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_routes_inbox.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/routes/inbox.py tests/test_routes_inbox.py
git commit -m "feat(ui): inbox routes — list, apply (move + save tags), dismiss, watcher toggle"
```

---

## Task 8: Inbox templates (`inbox.html`, `_inbox_card.html`) + 4th tab

**Files:**
- Create: `templates/inbox.html`, `templates/_inbox_card.html`
- Modify: `templates/base.html`, `static/app.css`

- [ ] **Step 1: Update `templates/base.html` — add the fourth tab link**

Replace the `<nav class="tabs">` block with:

```jinja
<nav class="tabs" aria-label="Main tabs">
  <a href="/meetings" class="tab {% if active_tab == 'meetings' %}active{% endif %}"
     {% if active_tab == 'meetings' %}aria-current="page"{% endif %}>Meetings</a>
  <a href="/inbox" class="tab {% if active_tab == 'inbox' %}active{% endif %}"
     {% if active_tab == 'inbox' %}aria-current="page"{% endif %}>
    Inbox
    {% if inbox_count %}<span class="count">{{ inbox_count }}</span>{% endif %}
  </a>
  <a href="/speakers" class="tab {% if active_tab == 'speakers' %}active{% endif %}"
     {% if active_tab == 'speakers' %}aria-current="page"{% endif %}>
    Speakers
    {% if speakers_count %}<span class="count">{{ speakers_count }}</span>{% endif %}
  </a>
  <a href="/pipeline" class="tab {% if active_tab == 'pipeline' %}active{% endif %}"
     {% if active_tab == 'pipeline' %}aria-current="page"{% endif %}>
    Pipeline
    {% if pipeline_running %}<span class="running">running</span>{% endif %}
  </a>
</nav>
```

- [ ] **Step 2: Create `templates/inbox.html`**

```jinja
{% extends "base.html" %}
{% block title %}Inbox — Transcribe{% endblock %}
{% block content %}
<section class="inbox-page">
  {% if not watcher_enabled %}
  <div class="banner">
    Watcher disabled. Set <code>WATCH_DIR</code> in <code>.env</code> and restart the server to enable auto-ingestion.
  </div>
  {% endif %}

  {% if proposals %}
    {% for p in proposals %}
      {% set proposal = p %}
      {% include "_inbox_card.html" %}
    {% endfor %}
  {% else %}
    <p class="subtitle">Inbox is empty. New recordings in <code>WATCH_DIR</code> will land here.</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 3: Create `templates/_inbox_card.html`**

```jinja
<article class="inbox-card">
  <header class="inbox-head">
    <h3>{{ proposal.stem }}</h3>
    <span class="status status-{{ proposal.status }}">{{ proposal.status }}</span>
  </header>
  {% if proposal.status == 'error' %}
    <p class="error-msg">{{ proposal.error_message }}</p>
  {% endif %}
  <form method="post" action="/inbox/{{ proposal.stem }}/apply" class="inbox-form">
    <label>
      Subdir:
      <input list="subdirs-{{ proposal.stem }}" name="target_subdir"
             value="{{ proposal.proposed_subdir }}"
             {% if proposal.status != 'ready' %}disabled{% endif %}>
      <datalist id="subdirs-{{ proposal.stem }}">
        {% for s in existing_subdirs %}<option value="{{ s }}">{% endfor %}
      </datalist>
    </label>
    <div class="tag-editor" data-stem="{{ proposal.stem }}">
      {% for t in proposal.proposed_tags %}
        <span class="tag tag-{{ t.type }}">
          <input type="hidden" name="tag_name" value="{{ t.name }}">
          <input type="hidden" name="tag_type" value="{{ t.type }}">
          {{ {"person":"👤","topic":"🏷","project":"📁"}[t.type] }} {{ t.name }}
        </span>
      {% endfor %}
    </div>
    <div class="inbox-actions">
      <button type="submit"
              {% if proposal.status != 'ready' %}disabled{% endif %}>Apply</button>
      <button type="button"
              formaction="/inbox/{{ proposal.stem }}/dismiss"
              formmethod="post"
              class="secondary">Dismiss</button>
    </div>
  </form>
</article>
```

- [ ] **Step 4: CSS**

Append to `static/app.css`:

```css
.inbox-page { display: flex; flex-direction: column; gap: 0.75rem; }
.banner { background: var(--bg); border: 1px solid var(--warn); border-radius: 8px; padding: 0.6rem 0.85rem; font-size: 0.85rem; }
.inbox-card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; display: flex; flex-direction: column; gap: 0.5rem; }
.inbox-head { display: flex; align-items: center; gap: 0.6rem; }
.inbox-head h3 { margin: 0; font-size: 0.95rem; flex: 1; }
.status { font-size: 0.7rem; border-radius: 10px; padding: 0.1rem 0.45rem; color: white; }
.status-transcribing, .status-analyzing { background: var(--warn); }
.status-ready { background: var(--ok); }
.status-error { background: #d0342c; }
.error-msg { color: #d0342c; font-size: 0.8rem; margin: 0; }
.inbox-form { display: flex; flex-direction: column; gap: 0.55rem; }
.inbox-form label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; }
.inbox-form input[name="target_subdir"] { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.3rem 0.5rem; color: var(--text); min-width: 220px; }
.tag-editor { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.tag { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 0.1rem 0.5rem; font-size: 0.75rem; }
.tag-person { border-color: var(--accent); }
.tag-topic { border-color: var(--warn); }
.tag-project { border-color: var(--ok); }
.inbox-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
.inbox-actions button { background: var(--accent); color: white; border: none; border-radius: 6px; padding: 0.35rem 0.8rem; font-weight: 600; cursor: pointer; }
.inbox-actions button.secondary { background: var(--bg); color: var(--text); border: 1px solid var(--border); }
.inbox-actions button[disabled] { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_routes_inbox.py -v`
Full suite: `pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add templates/base.html templates/inbox.html templates/_inbox_card.html static/app.css
git commit -m "feat(ui): Inbox tab page + card template + 4th nav tab"
```

---

## Task 9: Propagate `inbox_count` + `pipeline_running` to every context

**Files:**
- Modify: `app/routes/meetings.py`, `app/routes/speakers.py`, `app/routes/pipeline_routes.py`, `app/routes/inbox.py`

- [ ] **Step 1: Extract helper into `app/routes/_context.py`**

Create `app/routes/_context.py`:

```python
from app import fs, pipeline, store


def nav_counts() -> dict:
    """Context keys the base template needs on every page."""
    return {
        "speakers_count": len(fs.list_unknown_clips()),
        "pipeline_running": pipeline.get_runner().is_running(),
        "inbox_count": len(store.list_pending_proposals()),
    }
```

- [ ] **Step 2: Replace ad-hoc `_counts()` calls**

In `app/routes/meetings.py`, replace the existing `_counts()` definition with an import and call-through:

```python
from app.routes._context import nav_counts
```

Delete the `_counts()` function and replace `**_counts()` in both meeting routes with `**nav_counts()`.

In `app/routes/speakers.py`, replace the literal context keys `"speakers_count": len(unknown_clips)`, `"pipeline_running": pipeline.get_runner().is_running()` block with `**nav_counts()` (and keep the `unknown_clips` variable for the `clips` key in the context). Add the `from app.routes._context import nav_counts` import. The label-handler's `templates.get_template(...).render(...)` also needs the `inbox_count` — pass `**nav_counts()` there too.

In `app/routes/pipeline_routes.py`, replace the `"speakers_count": ..., "pipeline_running": r.is_running()` pair in the context dict with `**nav_counts()` (remove any duplicate keys — `r.is_running()` and `is_running` local still feed the form's disabled state separately).

In `app/routes/inbox.py`, replace the three individual keys with `**nav_counts()`.

- [ ] **Step 3: Regression test**

Append a new test to `tests/test_routes_shell.py`:

```python
def test_inbox_count_appears_on_every_tab(client, tmp_path, monkeypatch):
    from app import fs, store
    from tests.helpers.sample_assets import build_sample_tree
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    store.save_proposal(stem="x", proposed_subdir="",
                        proposed_tags=[], status="ready", error_message=None)

    for tab in ("/meetings", "/speakers", "/pipeline", "/inbox"):
        r = client.get(tab)
        assert r.status_code == 200
        # The inbox count appears in the nav badge (at least in text form)
        assert '<a href="/inbox"' in r.text
```

Note: `client` in `tests/test_routes_shell.py` uses the default `create_app()` without monkeypatching `fs.DATA_DIR` — add the setup above.

- [ ] **Step 4: Run full suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add app/routes templates tests/test_routes_shell.py
git commit -m "feat(ui): shared nav_counts() — inbox badge + pipeline pill on every tab"
```

---

## Task 10: Tag chips in Meetings tree + detail view

**Files:**
- Modify: `app/routes/meetings.py`, `templates/_meeting_tree.html`, `templates/_meeting_detail.html`, `static/app.css`, `tests/test_routes_meetings.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_routes_meetings.py`:

```python
def test_meeting_tree_shows_tag_chips(app_with_tree):
    from app import store
    import os
    monkeypatch_fixture = os.environ  # not used; placeholder
    store.DB_PATH  # ensure import
    # The app_with_tree fixture does not monkeypatch store.DB_PATH; we re-init
    # in a tmp location via pytest here:
    pass


def test_meeting_detail_shows_tag_section(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert "Tags" in r.text
    assert "Darwin Henao" in r.text


def test_meeting_tree_filters_by_tag(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings?tag=Darwin+Henao&tag_type=person")
    assert r.status_code == 200
    # The tagged meeting appears; untagged ones do not
    assert "2026-04-14 17-00-43" in r.text
    # Meeting without the tag should be absent
    assert "2026-04-17 09-00-00" not in r.text
```

Replace the three new test functions above with a single cohesive block and add a new fixture `app_with_tree_with_tags` at the top of the test file:

```python
@pytest.fixture
def app_with_tree_with_tags(tmp_path, monkeypatch):
    from app import store
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    store.set_meeting_tags(
        "2026-04-14 17-00-43",
        [store.Tag(name="Darwin Henao", type="person")],
        source="manual",
    )
    return TestClient(create_app())
```

Replace the earlier placeholder test with two real ones:

```python
def test_meeting_detail_shows_tag_section(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert "Darwin Henao" in r.text
    assert 'class="tag tag-person"' in r.text


def test_meeting_tree_filters_by_tag(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings?tag=Darwin+Henao&tag_type=person")
    assert r.status_code == 200
    assert "2026-04-14 17-00-43" in r.text
    assert "2026-04-17 09-00-00" not in r.text
```

- [ ] **Step 2: Modify the meetings route**

In `app/routes/meetings.py`:

Add import at top: `from app import store` (if not already present — add it).

Replace the `meetings_index` function body with:

```python
@router.get("/meetings")
def meetings_index(request: Request, tag: str | None = None, tag_type: str | None = None):
    meetings = fs.list_meetings()
    if tag and tag_type in ("person", "topic", "project"):
        allowed_stems = set(store.list_stems_with_tag(tag, tag_type))
        meetings = [m for m in meetings if m.stem in allowed_stems]
    tags_by_stem = {m.stem: store.list_meeting_tags(m.stem) for m in meetings}
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "meeting": None,
            "selected": None,
            "tags_by_stem": tags_by_stem,
            "current_tag_filter": (tag, tag_type) if tag else None,
            **nav_counts(),
        },
    )
```

Replace `meeting_detail` with:

```python
@router.get("/meetings/{subdir}/{stem}")
def meeting_detail(subdir: str, stem: str, request: Request, view: str = "transcript"):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(status_code=404)
    if view not in ("transcript", "knowledge", "commitments"):
        view = "transcript"
    meetings = fs.list_meetings()
    tags_by_stem = {mm.stem: store.list_meeting_tags(mm.stem) for mm in meetings}
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "active_tab": "meetings",
            "meetings": meetings,
            "meeting": m,
            "selected": m,
            "view": view,
            "transcript_html": _render_transcript(fs.load_transcript(m)),
            "knowledge_html": md_render.render(fs.load_knowledge(m)),
            "commitments_html": md_render.render(fs.load_commitments(m)),
            "tags_by_stem": tags_by_stem,
            "meeting_tags": store.list_meeting_tags(stem),
            "current_tag_filter": None,
            **nav_counts(),
        },
    )
```

- [ ] **Step 3: Update `templates/_meeting_tree.html`**

Replace the `<li>` block inside the loop with:

```jinja
<li>
  <a href="/meetings/{{ m.subdir }}/{{ m.stem }}"
     class="{% if selected and selected.subdir == m.subdir and selected.stem == m.stem %}hl{% endif %}">
    {{ m.stem }}
    {% if m.unknown_count %}<span class="badge">{{ m.unknown_count }}</span>{% endif %}
  </a>
  {% set tags = tags_by_stem.get(m.stem, []) %}
  {% if tags %}
    <div class="row-tags">
      {% for t in tags %}
        <a class="tag tag-{{ t.type }}"
           href="/meetings?tag={{ t.name|urlencode }}&tag_type={{ t.type }}"
           >{{ {"person":"👤","topic":"🏷","project":"📁"}[t.type] }} {{ t.name }}</a>
      {% endfor %}
    </div>
  {% endif %}
</li>
```

- [ ] **Step 4: Update `templates/_meeting_detail.html`**

After the `</nav>` closing the subtabs and before the `<div class="subview">`, insert:

```jinja
<div class="meeting-tags">
  <span class="label">Tags</span>
  {% if meeting_tags %}
    {% for t in meeting_tags %}
      <span class="tag tag-{{ t.type }}">{{ {"person":"👤","topic":"🏷","project":"📁"}[t.type] }} {{ t.name }}</span>
    {% endfor %}
  {% else %}
    <span class="subtitle">no tags</span>
  {% endif %}
</div>
```

- [ ] **Step 5: CSS**

Append to `static/app.css`:

```css
.row-tags { display: flex; flex-wrap: wrap; gap: 0.2rem; margin: 0.1rem 0 0.3rem 0.6rem; }
.row-tags .tag { font-size: 0.65rem; padding: 0.05rem 0.35rem; text-decoration: none; color: var(--text); }
.meeting-tags { display: flex; align-items: center; gap: 0.4rem; margin: 0.3rem 0 0.5rem; flex-wrap: wrap; }
.meeting-tags .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_routes_meetings.py -v`
Expected: 10 passed (8 prior + 2 new).

Full suite: `pytest -v`

- [ ] **Step 7: Commit**

```bash
git add app/routes/meetings.py templates/_meeting_tree.html templates/_meeting_detail.html static/app.css tests/test_routes_meetings.py
git commit -m "feat(ui): meeting tag chips in tree + detail + tag filter query"
```

---

## Task 11: POST `/meetings/{subdir}/{stem}/tags` — manual tag edit

**Files:**
- Modify: `app/routes/meetings.py`, `templates/_meeting_detail.html`, `tests/test_routes_meetings.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_routes_meetings.py`:

```python
def test_post_meeting_tags_replaces_tags(app_with_tree_with_tags):
    from app import store
    r = app_with_tree_with_tags.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/tags",
        data={"tag_name": ["Maria Lopez", "onboarding"],
              "tag_type": ["person", "topic"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    tags = store.list_meeting_tags("2026-04-14 17-00-43")
    names = sorted(t.name for t in tags)
    assert names == ["Maria Lopez", "onboarding"]
```

- [ ] **Step 2: Run — expect 405**

Run: `pytest tests/test_routes_meetings.py::test_post_meeting_tags_replaces_tags -v`

- [ ] **Step 3: Add the route**

Append to `app/routes/meetings.py`:

```python
from typing import Annotated
from fastapi import Form


@router.post("/meetings/{subdir}/{stem}/tags")
def set_tags(
    subdir: str,
    stem: str,
    tag_name: Annotated[list[str], Form()] = [],
    tag_type: Annotated[list[str], Form()] = [],
):
    if fs.find_meeting(subdir, stem) is None:
        raise HTTPException(status_code=404)
    tags = []
    for n, t in zip(tag_name, tag_type):
        n = (n or "").strip()
        if n and t in ("person", "topic", "project"):
            tags.append(store.Tag(name=n, type=t))
    store.set_meeting_tags(stem, tags, source="manual")
    return RedirectResponse(f"/meetings/{subdir}/{stem}", status_code=303)
```

(Make sure `RedirectResponse` is imported at the top of the file — it's already there from Task 12 of Round 1.)

- [ ] **Step 4: Add a small edit form to `_meeting_detail.html`**

Below the `<div class="meeting-tags">` block, insert:

```jinja
<details class="tag-edit">
  <summary>Edit tags</summary>
  <form method="post" action="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}/tags">
    <div class="tag-edit-rows">
      {% for t in meeting_tags %}
        <div class="tag-edit-row">
          <input name="tag_name" value="{{ t.name }}">
          <select name="tag_type">
            {% for opt in ['person', 'topic', 'project'] %}
              <option value="{{ opt }}" {% if t.type == opt %}selected{% endif %}>{{ opt }}</option>
            {% endfor %}
          </select>
        </div>
      {% endfor %}
      <div class="tag-edit-row">
        <input name="tag_name" placeholder="new tag">
        <select name="tag_type">
          <option value="topic">topic</option>
          <option value="person">person</option>
          <option value="project">project</option>
        </select>
      </div>
    </div>
    <button type="submit" class="mini-btn">Save tags</button>
  </form>
</details>
```

- [ ] **Step 5: CSS**

Append to `static/app.css`:

```css
.tag-edit { margin: 0.3rem 0; font-size: 0.85rem; }
.tag-edit summary { cursor: pointer; color: var(--muted); }
.tag-edit-rows { display: flex; flex-direction: column; gap: 0.3rem; margin: 0.4rem 0; }
.tag-edit-row { display: flex; gap: 0.4rem; }
.tag-edit-row input, .tag-edit-row select { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.25rem 0.5rem; color: var(--text); }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_routes_meetings.py -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add app/routes/meetings.py templates/_meeting_detail.html static/app.css tests/test_routes_meetings.py
git commit -m "feat(ui): POST /meetings/.../tags lets user edit manual tags"
```

---

## Task 12: Documentation + final verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append Round 2 documentation to `CLAUDE.md`**

Append to the end of `CLAUDE.md`:

```markdown

## Web UI (Round 2)

Round 2 adds:

- **Inbox tab** — new recordings arriving in `$WATCH_DIR` are auto-copied into `data/_inbox/`, run through `process.py`, then analyzed by Claude to propose a target subdir + tags. You approve in the Inbox tab; files move to `data/<subdir>/` and tags persist.
- **Tags** — stored in SQLite at `ui.db` (gitignored). Displayed as chips on meeting rows and the detail view. Click a tag to filter the Meetings tree. Manually edit tags on any meeting via the "Edit tags" disclosure.
- **Watcher** — `watchdog.PollingObserver` monitors `$WATCH_DIR` when set. Toggle with `POST /watcher/start|stop|status`. No-op if `WATCH_DIR` is unset.

Configuration:

```bash
# .env
WATCH_DIR=/Users/you/Movies/Meetings
```
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -v`
Expected: all green, well above the Round 1 baseline of 43.

- [ ] **Step 3: Manual end-to-end verification**

1. Set `WATCH_DIR` in `.env` to a scratch directory.
2. `python server.py` and visit `http://localhost:8000/inbox`. The banner is absent; `/watcher/status` returns `is_running: true`.
3. Drop a small `.mov` into `WATCH_DIR`. Within seconds the Inbox card appears with status `transcribing`, then `analyzing`, then `ready`.
4. Edit the subdir and tags if desired. Click Apply. File moves; redirected to the Meetings detail view which shows the tags and the Edit-tags disclosure.
5. Click a tag chip. Tree filters to matching meetings.
6. Drop a second file while the first is still running. Confirm it queues and processes after.
7. Regression: `python process.py --reclassify` from the CLI still works unchanged.

- [ ] **Step 4: Commit + push**

```bash
git add CLAUDE.md
git commit -m "docs: add Round 2 web UI section to CLAUDE.md"
git push -u origin webui-round2
```

---

## Self-review

**Spec coverage:**

- Watcher + stability → Task 5
- data/_inbox staging + auto-pipeline → Task 4 (ingest) + Task 6 (server wiring)
- Claude-proposed subdir + tags → Task 3 (categorize) + Task 4 (ingest invokes)
- SQLite persistence of tags + proposals → Task 1
- Inbox tab UI + apply/dismiss → Tasks 7, 8
- 4th tab with badge count → Tasks 8, 9
- Meeting tag chips + filter → Task 10
- Manual tag editing → Task 11
- `_inbox` excluded from Meetings tree → Task 2
- Docs → Task 12
- Watcher toggle endpoints → Task 7

**Deferred (per spec's "Out-of-scope"):**

- Retro-categorize button on existing meetings — Round 3.
- Deletion / un-route — Round 3.
- Bulk tag ops — Round 3.

**Type consistency:**

- `Tag` dataclass defined in Task 1 used consistently in Tasks 3, 4, 7, 10, 11.
- `Proposal` dataclass fields match between `store.save_proposal` call sites and `list_pending_proposals` consumers.
- `store.INBOX_SUBDIR` constant defined in Task 1, referenced in Tasks 2, 4, 7.
- `Watcher` start/stop/status API consistent across Task 5 definition, Task 6 server wiring, and Task 7 routes.
