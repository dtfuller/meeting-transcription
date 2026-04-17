# Web UI Round 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local single-user web UI that browses meetings, labels unknown speakers, and triggers/monitors the transcribe+extract pipeline — per `docs/superpowers/specs/2026-04-17-web-ui-round1-design.md`.

**Architecture:** Single FastAPI process binding `127.0.0.1:8000`. Server-rendered Jinja2 templates + HTMX fragments for interactions. Server-Sent Events stream live pipeline output. Pipeline execution reuses `process.py` as a subprocess — no duplication of orchestration. State is derived from the filesystem (`data/`, `transcripts/`, `information/`, `known-names/`); only ephemeral state is an in-memory "labels since last reclassify" counter.

**Tech Stack:** Python 3.11 · FastAPI · Uvicorn · Jinja2 · HTMX · markdown-it-py · pytest + httpx (TestClient).

---

## File structure

**New files (under repo root):**

```
server.py                              # entry point: `python server.py`
app/
  __init__.py
  fs.py                                # read-only filesystem queries
  clips.py                             # mutating clip-label operations + in-memory counter
  pipeline.py                          # PipelineRunner: subprocess + SSE fanout
  video.py                             # Range-aware .mov streaming
  markdown.py                          # markdown → safe HTML
  routes/
    __init__.py
    meetings.py
    speakers.py
    pipeline_routes.py
    media.py                           # video streaming routes
templates/
  base.html                            # tab shell, blocks: title, active_tab, content
  _clip_card.html                      # partial
  _meeting_tree.html                   # partial
  _meeting_detail.html                 # partial (Transcript/Knowledge/Commitments)
  _toast.html                          # partial (accumulating reclassify prompt)
  _log_line.html                       # partial (SSE line)
  meetings.html
  speakers.html
  pipeline.html
static/
  app.css
  htmx.min.js                          # vendored (no CDN)
tests/
  __init__.py
  conftest.py                          # fixtures: tmp_data_root, TestClient
  test_fs.py
  test_clips.py
  test_pipeline.py
  test_routes_meetings.py
  test_routes_speakers.py
  test_routes_pipeline.py
  test_video.py
  test_markdown.py
  helpers/
    __init__.py
    fake_pipeline.py                   # standalone script for runner tests
    sample_assets.py                   # builds fixture data/, transcripts/, etc.
```

**Modified files:**

- `requirements.txt` — add `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `markdown-it-py`, `pytest`, `httpx`.
- `CLAUDE.md` — append a "Web UI" section at the bottom explaining `python server.py`.

**Unchanged:** `transcribe.py`, `extract.py`, `process.py` — the UI is strictly additive.

---

## Critical decisions locked in from the spec

- **Paths resolve relative to `Path(__file__).parent` of `server.py`** (repo root), mirroring the existing scripts. Constants defined once in `app/fs.py`: `DATA_DIR`, `TRANSCRIPTS_DIR`, `INFORMATION_DIR`, `KNOWN_NAMES_TO_USE`, `KNOWN_NAMES_TO_CLASSIFY`.
- **Tree key:** `(subdir, stem)` where `stem` is the filename minus `.mov` (also minus `.txt`). These are the routing primitives — URLs like `/meetings/{subdir}/{stem}`.
- **Clip filename format** (per `transcribe.extract_unknown_speaker_clips` at `transcribe.py:332`): `Unknown Speaker N - <meeting-stem> - MMmSSs.mov`. When parsing, split once on ` - `, and reconstruct: `[raw_label, meeting_stem_with_possible_dashes, timestamp_string]`. Since timestamps are always `\d+m\d+s.mov`, parse from the right.
- **Known-name grouping** mirrors `transcribe.extract_reference_embeddings` at `transcribe.py:202-206`: prefix before the first ` - `. We copy that 5-line logic into `app/fs.py` rather than import transcribe.py (which would pull pyannote/torch on import).
- **Single pipeline run at a time** — `PipelineRunner` is a module-level singleton. Second concurrent start raises `AlreadyRunning`.
- **Toast counter:** `labels_since_reset` — incremented on every successful `/speakers/label`, reset when `PipelineRunner.on_complete` fires and the run's argv contained `--reclassify`.

---

## Task 1: Scaffolding, dependencies, TestClient smoke

**Files:**
- Create: `requirements.txt` (modify), `server.py`, `app/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
fastapi>=0.115
uvicorn[standard]>=0.30
jinja2>=3.1
python-multipart>=0.0.9
markdown-it-py>=3.0
pytest>=8.0
httpx>=0.27
```

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Create minimal app package**

Create `app/__init__.py` (empty).

Create `server.py`:

```python
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

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

Create `static/` directory with an empty `.gitkeep` file so `StaticFiles` mount doesn't explode in tests.

Run: `mkdir -p static && touch static/.gitkeep`

- [ ] **Step 3: Write smoke test**

Create `tests/__init__.py` (empty).

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())
```

Create `tests/test_smoke.py`:

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_root_redirects_to_meetings(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/meetings"
```

- [ ] **Step 4: Run tests — expect 2 passing, 0 failing**

Run: `pytest tests/test_smoke.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt server.py app/__init__.py static/.gitkeep tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "feat(ui): scaffold FastAPI app with healthz + root redirect"
```

---

## Task 2: Filesystem model — meetings, clips, known names

**Files:**
- Create: `app/fs.py`, `tests/helpers/__init__.py`, `tests/helpers/sample_assets.py`, `tests/test_fs.py`

- [ ] **Step 1: Write the test fixture helper**

Create `tests/helpers/__init__.py` (empty).

Create `tests/helpers/sample_assets.py`:

```python
"""
Build a fake repo layout under a tmp_path for filesystem tests.
"""
from pathlib import Path


def write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def build_sample_tree(root: Path) -> None:
    data = root / "data"
    transcripts = root / "transcripts"
    information = root / "information"
    to_use = root / "known-names" / "to-use"
    to_classify = root / "known-names" / "to-classify"

    # A fully-processed meeting
    (data / "multiturbo").mkdir(parents=True)
    (data / "multiturbo" / "2026-04-14 17-00-43.mov").write_bytes(b"\x00" * 16)
    write(transcripts / "multiturbo" / "2026-04-14 17-00-43.txt",
          "[00:00:00 David Fuller] hola\n[00:00:05 Darwin Henao] hola\n")
    write(information / "multiturbo" / "2026-04-14 17-00-43-knowledge.md", "# K\n")
    write(information / "multiturbo" / "2026-04-14 17-00-43-commitments.md", "# C\n")

    # A meeting with Unknown Speaker still in the transcript
    (data / "multiturbo" / "2026-04-16 17-01-16.mov").write_bytes(b"\x00" * 16)
    write(transcripts / "multiturbo" / "2026-04-16 17-01-16.txt",
          "[00:00:15 Darwin Henao] hola\n[00:01:08 Unknown Speaker 1] …\n")
    write(information / "multiturbo" / "2026-04-16 17-01-16-knowledge.md", "# K\n")
    write(information / "multiturbo" / "2026-04-16 17-01-16-commitments.md", "# C\n")

    # A meeting with no transcript yet
    (data / "check-in").mkdir(parents=True)
    (data / "check-in" / "2026-04-17 09-00-00.mov").write_bytes(b"\x00" * 16)

    # Known speakers
    to_use.mkdir(parents=True)
    (to_use / "David Fuller.mov").write_bytes(b"\x00")
    (to_use / "David Fuller - 2026-01-15.mov").write_bytes(b"\x00")
    (to_use / "Darwin Henao.mov").write_bytes(b"\x00")

    # Clips awaiting labels
    to_classify.mkdir(parents=True)
    (to_classify / "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov").write_bytes(b"\x00")
    (to_classify / "Unknown Speaker 2 - 2026-04-16 17-01-16 - 03m22s.mov").write_bytes(b"\x00")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fs.py`:

```python
from pathlib import Path

import pytest

from app import fs
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def tree(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "ROOT", tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return tmp_path


def test_list_meetings_returns_all_movs_grouped_by_subdir(tree):
    meetings = fs.list_meetings()
    keys = [(m.subdir, m.stem) for m in meetings]
    assert ("check-in", "2026-04-17 09-00-00") in keys
    assert ("multiturbo", "2026-04-14 17-00-43") in keys
    assert ("multiturbo", "2026-04-16 17-01-16") in keys
    assert len(keys) == 3


def test_meeting_has_status_flags(tree):
    meetings = {(m.subdir, m.stem): m for m in fs.list_meetings()}
    done = meetings[("multiturbo", "2026-04-14 17-00-43")]
    assert done.has_transcript and done.has_knowledge and done.has_commitments
    assert done.unknown_count == 0

    partial = meetings[("multiturbo", "2026-04-16 17-01-16")]
    assert partial.unknown_count == 1  # one "Unknown Speaker" line

    raw = meetings[("check-in", "2026-04-17 09-00-00")]
    assert not raw.has_transcript


def test_find_meeting_by_key(tree):
    m = fs.find_meeting("multiturbo", "2026-04-14 17-00-43")
    assert m is not None
    assert m.mov_path.exists()

    assert fs.find_meeting("does-not", "exist") is None


def test_load_transcript_knowledge_commitments(tree):
    m = fs.find_meeting("multiturbo", "2026-04-14 17-00-43")
    assert "David Fuller" in fs.load_transcript(m)
    assert fs.load_knowledge(m).startswith("# K")
    assert fs.load_commitments(m).startswith("# C")


def test_list_unknown_clips_parses_filename(tree):
    clips = fs.list_unknown_clips()
    assert len(clips) == 2
    c = clips[0]
    assert c.raw_label.startswith("Unknown Speaker")
    assert c.source_stem == "2026-04-16 17-01-16"
    assert c.timestamp_text == "01m08s"
    assert c.filename.endswith(".mov")


def test_list_known_names_groups_by_prefix(tree):
    names = fs.list_known_names()
    assert "David Fuller" in names  # grouped from two files
    assert "Darwin Henao" in names
    # Deduped
    assert names.count("David Fuller") == 1
```

- [ ] **Step 3: Run — expect collection error**

Run: `pytest tests/test_fs.py -v`
Expected: ImportError / ModuleNotFoundError for `app.fs`.

- [ ] **Step 4: Implement `app/fs.py`**

Create `app/fs.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
TRANSCRIPTS_DIR = ROOT / "transcripts"
INFORMATION_DIR = ROOT / "information"
KNOWN_NAMES_TO_USE = ROOT / "known-names" / "to-use"
KNOWN_NAMES_TO_CLASSIFY = ROOT / "known-names" / "to-classify"

_UNKNOWN_MARKER = "Unknown Speaker"
_CLIP_TS_RE = re.compile(r"(\d+m\d+s)\.mov$")


@dataclass(frozen=True)
class Meeting:
    subdir: str
    stem: str
    mov_path: Path
    transcript_path: Path
    knowledge_path: Path
    commitments_path: Path

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path.exists() and self.transcript_path.stat().st_size > 0

    @property
    def has_knowledge(self) -> bool:
        return self.knowledge_path.exists()

    @property
    def has_commitments(self) -> bool:
        return self.commitments_path.exists()

    @property
    def unknown_count(self) -> int:
        if not self.has_transcript:
            return 0
        text = self.transcript_path.read_text(encoding="utf-8")
        # One badge per distinct "Unknown Speaker N" label
        labels = set(re.findall(r"Unknown Speaker \d+", text))
        return len(labels)


@dataclass(frozen=True)
class Clip:
    filename: str
    path: Path
    raw_label: str          # "Unknown Speaker 1"
    source_stem: str        # "2026-04-16 17-01-16"
    timestamp_text: str     # "01m08s"


def _meeting_from_mov(mov: Path) -> Meeting:
    rel = mov.relative_to(DATA_DIR)
    subdir = rel.parts[0] if len(rel.parts) > 1 else ""
    stem = mov.stem
    base = Path(subdir) / stem
    return Meeting(
        subdir=subdir,
        stem=stem,
        mov_path=mov,
        transcript_path=(TRANSCRIPTS_DIR / base).with_suffix(".txt"),
        knowledge_path=INFORMATION_DIR / subdir / f"{stem}-knowledge.md",
        commitments_path=INFORMATION_DIR / subdir / f"{stem}-commitments.md",
    )


def list_meetings() -> list[Meeting]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        (_meeting_from_mov(p) for p in DATA_DIR.rglob("*.mov")),
        key=lambda m: (m.subdir, m.stem),
    )


def find_meeting(subdir: str, stem: str) -> Meeting | None:
    mov = DATA_DIR / subdir / f"{stem}.mov"
    if not mov.exists():
        return None
    return _meeting_from_mov(mov)


def load_transcript(m: Meeting) -> str:
    return m.transcript_path.read_text(encoding="utf-8") if m.has_transcript else ""


def load_knowledge(m: Meeting) -> str:
    return m.knowledge_path.read_text(encoding="utf-8") if m.has_knowledge else ""


def load_commitments(m: Meeting) -> str:
    return m.commitments_path.read_text(encoding="utf-8") if m.has_commitments else ""


def list_unknown_clips() -> list[Clip]:
    if not KNOWN_NAMES_TO_CLASSIFY.exists():
        return []
    clips: list[Clip] = []
    for mov in sorted(KNOWN_NAMES_TO_CLASSIFY.glob("*.mov")):
        m = _CLIP_TS_RE.search(mov.name)
        if not m:
            continue
        timestamp_text = m.group(1)
        # Strip " - MMmSSs.mov" from the end
        head = mov.name[: m.start()].rstrip(" -")
        # Split head: "<raw_label> - <source_stem>"
        parts = head.split(" - ", 1)
        if len(parts) != 2:
            continue
        raw_label, source_stem = parts[0], parts[1]
        clips.append(Clip(
            filename=mov.name,
            path=mov,
            raw_label=raw_label,
            source_stem=source_stem,
            timestamp_text=timestamp_text,
        ))
    return clips


def list_known_names() -> list[str]:
    if not KNOWN_NAMES_TO_USE.exists():
        return []
    seen: dict[str, None] = {}
    for mov in sorted(KNOWN_NAMES_TO_USE.glob("*.mov")):
        person = mov.stem.split(" - ")[0].strip()
        seen.setdefault(person, None)
    return list(seen.keys())
```

- [ ] **Step 5: Run tests — expect all passing**

Run: `pytest tests/test_fs.py -v`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/fs.py tests/test_fs.py tests/helpers/__init__.py tests/helpers/sample_assets.py
git commit -m "feat(ui): filesystem model for meetings, clips, known names"
```

---

## Task 3: Base template, static assets, empty tab routes

**Files:**
- Create: `templates/base.html`, `templates/meetings.html`, `templates/speakers.html`, `templates/pipeline.html`, `static/app.css`, `static/htmx.min.js`, `app/routes/__init__.py`, `app/routes/meetings.py`, `app/routes/speakers.py`, `app/routes/pipeline_routes.py`, `tests/test_routes_shell.py`
- Modify: `server.py` (register routers, templates)

- [ ] **Step 1: Vendor HTMX**

Download htmx.min.js (v1.9.x is stable). Do NOT use curl via Bash — the user should prefer an offline-checked copy. If the environment has internet:

Run: `curl -sSL https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js -o static/htmx.min.js`

Verify: `ls -l static/htmx.min.js` shows a file ≈ 50 KB.

If curl is unavailable, write a placeholder and mark "replace before shipping":

```bash
echo "// TODO: vendor htmx.min.js from https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js" > static/htmx.min.js
```

- [ ] **Step 2: Write the base template**

Create `templates/base.html`:

```jinja
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Transcribe{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/htmx.min.js"></script>
</head>
<body>
  <header class="app-bar">
    <h1>Transcribe</h1>
    <nav class="tabs">
      <a href="/meetings" class="tab {% if active_tab == 'meetings' %}active{% endif %}">Meetings</a>
      <a href="/speakers" class="tab {% if active_tab == 'speakers' %}active{% endif %}">
        Speakers
        {% if speakers_count %}<span class="count">{{ speakers_count }}</span>{% endif %}
      </a>
      <a href="/pipeline" class="tab {% if active_tab == 'pipeline' %}active{% endif %}">
        Pipeline
        {% if pipeline_running %}<span class="running">running</span>{% endif %}
      </a>
    </nav>
  </header>
  <main class="app-main">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

Create `templates/meetings.html`:

```jinja
{% extends "base.html" %}
{% block title %}Meetings — Transcribe{% endblock %}
{% block content %}
<section class="meetings-page">
  <p class="subtitle">Meetings tab — to be built.</p>
</section>
{% endblock %}
```

Create `templates/speakers.html`:

```jinja
{% extends "base.html" %}
{% block title %}Speakers — Transcribe{% endblock %}
{% block content %}
<section class="speakers-page">
  <p class="subtitle">Speakers tab — to be built.</p>
</section>
{% endblock %}
```

Create `templates/pipeline.html`:

```jinja
{% extends "base.html" %}
{% block title %}Pipeline — Transcribe{% endblock %}
{% block content %}
<section class="pipeline-page">
  <p class="subtitle">Pipeline tab — to be built.</p>
</section>
{% endblock %}
```

- [ ] **Step 3: Minimal CSS**

Create `static/app.css`:

```css
:root {
  --bg: #f5f5f7;
  --panel: #ffffff;
  --border: #d1d1d6;
  --text: #1d1d1f;
  --muted: #86868b;
  --accent: #0071e3;
  --warn: #ff9f0a;
  --ok: #34c759;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1d1d1f; --panel: #2d2d2f; --border: #424245;
    --text: #f5f5f7; --muted: #86868b; --accent: #0a84ff;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); }
.app-bar { display: flex; align-items: center; gap: 1.5rem; padding: 0.6rem 1.25rem; background: var(--panel); border-bottom: 1px solid var(--border); }
.app-bar h1 { font-size: 1rem; font-weight: 600; margin: 0; }
.tabs { display: flex; gap: 0.75rem; }
.tab { text-decoration: none; color: var(--muted); padding: 0.35rem 0.7rem; border-radius: 6px; font-size: 0.9rem; }
.tab.active { background: var(--bg); color: var(--accent); font-weight: 600; }
.tab .count { background: var(--warn); color: white; border-radius: 10px; padding: 0 0.4rem; margin-left: 0.25rem; font-size: 0.7rem; }
.tab .running { background: var(--ok); color: white; border-radius: 10px; padding: 0 0.4rem; margin-left: 0.25rem; font-size: 0.7rem; }
.app-main { padding: 1.25rem 1.5rem; }
.subtitle { color: var(--muted); }
```

- [ ] **Step 4: Create routers**

Create `app/routes/__init__.py` (empty).

Create `app/routes/meetings.py`:

```python
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/meetings")
def meetings_index(request: Request):
    return templates.TemplateResponse(
        "meetings.html",
        {"request": request, "active_tab": "meetings"},
    )
```

Create `app/routes/speakers.py`:

```python
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/speakers")
def speakers_index(request: Request):
    return templates.TemplateResponse(
        "speakers.html",
        {"request": request, "active_tab": "speakers"},
    )
```

Create `app/routes/pipeline_routes.py`:

```python
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/pipeline")
def pipeline_index(request: Request):
    return templates.TemplateResponse(
        "pipeline.html",
        {"request": request, "active_tab": "pipeline"},
    )
```

- [ ] **Step 5: Register routers in server.py**

Modify `server.py` — replace `create_app` with:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Meeting Transcribe UI")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    from app.routes import meetings, speakers, pipeline_routes
    app.include_router(meetings.router)
    app.include_router(speakers.router)
    app.include_router(pipeline_routes.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def root():
        return RedirectResponse("/meetings", status_code=302)

    return app
```

- [ ] **Step 6: Write routes-shell tests**

Create `tests/test_routes_shell.py`:

```python
def test_meetings_page_renders(client):
    r = client.get("/meetings")
    assert r.status_code == 200
    assert "Meetings" in r.text
    assert 'class="tab active"' in r.text


def test_speakers_page_renders(client):
    r = client.get("/speakers")
    assert r.status_code == 200
    assert "Speakers" in r.text


def test_pipeline_page_renders(client):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Pipeline" in r.text
```

- [ ] **Step 7: Run tests — expect 3 passing**

Run: `pytest tests/test_routes_shell.py -v`
Expected: `3 passed`.

- [ ] **Step 8: Manual check**

Run: `python server.py` in one terminal. Open `http://localhost:8000` in a browser. Click each tab, confirm the shell is there and the active tab highlights. Kill server with `Ctrl-C`.

- [ ] **Step 9: Commit**

```bash
git add server.py app/routes templates static tests/test_routes_shell.py
git commit -m "feat(ui): base template, HTMX, stub tab routes"
```

---

## Task 4: Meetings tree + detail (Transcript view)

**Files:**
- Create: `templates/_meeting_tree.html`, `templates/_meeting_detail.html`
- Modify: `templates/meetings.html`, `app/routes/meetings.py`
- Create: `tests/test_routes_meetings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_routes_meetings.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def app_with_tree(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    for attr in (
        "ROOT", "DATA_DIR", "TRANSCRIPTS_DIR", "INFORMATION_DIR",
        "KNOWN_NAMES_TO_USE", "KNOWN_NAMES_TO_CLASSIFY",
    ):
        monkeypatch.setattr(fs, attr, getattr(fs, attr))  # re-anchor under tmp in next lines
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return TestClient(create_app())


def test_meetings_index_lists_tree(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert r.status_code == 200
    assert "multiturbo" in r.text
    assert "2026-04-14 17-00-43" in r.text
    assert "check-in" in r.text


def test_unknown_badge_shown_for_meetings_with_unknown_speakers(app_with_tree):
    r = app_with_tree.get("/meetings")
    # Meeting with Unknown Speaker should show a badge
    assert '2026-04-16 17-01-16' in r.text
    # Badge markup should appear near that stem
    assert 'class="badge"' in r.text


def test_meeting_detail_renders_transcript(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert "David Fuller" in r.text
    assert "hola" in r.text


def test_meeting_detail_unknown_404(app_with_tree):
    r = app_with_tree.get("/meetings/does-not/exist")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect 4 failures**

Run: `pytest tests/test_routes_meetings.py -v`
Expected: failures (tree text not present, 404 for detail route not wired).

- [ ] **Step 3: Template partials**

Create `templates/_meeting_tree.html`:

```jinja
<aside class="tree">
  {% set current_subdir = namespace(v=None) %}
  {% for m in meetings %}
    {% if m.subdir != current_subdir.v %}
      {% if not loop.first %}</ul>{% endif %}
      <div class="folder">📁 {{ m.subdir }}</div>
      <ul>
      {% set current_subdir.v = m.subdir %}
    {% endif %}
    <li>
      <a href="/meetings/{{ m.subdir }}/{{ m.stem }}"
         class="{% if selected and selected.subdir == m.subdir and selected.stem == m.stem %}hl{% endif %}">
        {{ m.stem }}
        {% if m.unknown_count %}<span class="badge">{{ m.unknown_count }}</span>{% endif %}
      </a>
    </li>
  {% endfor %}
  {% if meetings %}</ul>{% endif %}
</aside>
```

Create `templates/_meeting_detail.html`:

```jinja
<section class="detail">
  <header class="detail-head">
    <h2>{{ meeting.stem }}</h2>
    <div class="actions">
      <a class="mini-btn" href="/video/meeting/{{ meeting.subdir }}/{{ meeting.stem }}" target="_blank">▶ Open video</a>
      <!-- re-extract / reclassify hooked up in later task -->
    </div>
  </header>
  <nav class="subtabs">
    <a class="subtab {% if view == 'transcript' %}active{% endif %}"
       href="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}?view=transcript">Transcript</a>
    <a class="subtab {% if view == 'knowledge' %}active{% endif %}"
       href="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}?view=knowledge">Knowledge</a>
    <a class="subtab {% if view == 'commitments' %}active{% endif %}"
       href="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}?view=commitments">Commitments</a>
  </nav>
  <div class="subview">
    {% if view == 'transcript' %}
      <pre class="transcript">{{ transcript_text }}</pre>
    {% elif view == 'knowledge' %}
      <article class="md">{{ knowledge_html|safe }}</article>
    {% elif view == 'commitments' %}
      <article class="md">{{ commitments_html|safe }}</article>
    {% endif %}
  </div>
</section>
```

- [ ] **Step 4: Update meetings.html**

Replace `templates/meetings.html`:

```jinja
{% extends "base.html" %}
{% block title %}Meetings — Transcribe{% endblock %}
{% block content %}
<section class="meetings-page">
  {% include "_meeting_tree.html" %}
  {% if meeting %}
    {% include "_meeting_detail.html" %}
  {% else %}
    <section class="detail empty"><p class="subtitle">Select a meeting from the left.</p></section>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 5: Update route**

Replace `app/routes/meetings.py`:

```python
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app import fs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _counts(request: Request) -> dict:
    return {
        "speakers_count": len(fs.list_unknown_clips()),
        "pipeline_running": False,  # wired up in pipeline task
    }


@router.get("/meetings")
def meetings_index(request: Request):
    return templates.TemplateResponse(
        "meetings.html",
        {
            "request": request,
            "active_tab": "meetings",
            "meetings": fs.list_meetings(),
            "meeting": None,
            "selected": None,
            **_counts(request),
        },
    )


@router.get("/meetings/{subdir}/{stem}")
def meeting_detail(subdir: str, stem: str, request: Request, view: str = "transcript"):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(status_code=404)
    if view not in ("transcript", "knowledge", "commitments"):
        view = "transcript"
    return templates.TemplateResponse(
        "meetings.html",
        {
            "request": request,
            "active_tab": "meetings",
            "meetings": fs.list_meetings(),
            "meeting": m,
            "selected": m,
            "view": view,
            "transcript_text": fs.load_transcript(m),
            "knowledge_html": fs.load_knowledge(m),       # raw MD for now; markdown-rendered in next task
            "commitments_html": fs.load_commitments(m),
            **_counts(request),
        },
    )
```

- [ ] **Step 6: Add CSS for tree + detail**

Append to `static/app.css`:

```css
.meetings-page { display: flex; gap: 1rem; align-items: flex-start; }
.tree { min-width: 220px; max-width: 280px; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.5rem 0.75rem; font-size: 0.85rem; }
.tree .folder { font-weight: 600; margin: 0.4rem 0 0.2rem; }
.tree ul { list-style: none; padding-left: 0.5rem; margin: 0; }
.tree li a { text-decoration: none; color: var(--text); display: inline-flex; align-items: center; padding: 0.15rem 0; gap: 0.3rem; }
.tree li a.hl { color: var(--accent); font-weight: 600; }
.tree .badge { background: var(--warn); color: white; border-radius: 10px; padding: 0 0.35rem; font-size: 0.65rem; }
.detail { flex: 1; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; }
.detail.empty { color: var(--muted); }
.detail-head { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }
.detail-head h2 { margin: 0; font-size: 1rem; flex: 1; }
.mini-btn { background: var(--bg); color: var(--text); border: 1px solid var(--border); padding: 0.25rem 0.55rem; border-radius: 6px; font-size: 0.8rem; text-decoration: none; cursor: pointer; }
.subtabs { display: flex; gap: 0.6rem; border-bottom: 1px solid var(--border); margin-bottom: 0.5rem; }
.subtab { text-decoration: none; color: var(--muted); padding: 0.3rem 0.1rem; font-size: 0.85rem; }
.subtab.active { color: var(--accent); font-weight: 600; border-bottom: 2px solid var(--accent); }
pre.transcript { white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 0.8rem; line-height: 1.55; color: var(--muted); margin: 0; }
```

- [ ] **Step 7: Run tests — expect 4 passing**

Run: `pytest tests/test_routes_meetings.py -v`
Expected: `4 passed`.

- [ ] **Step 8: Commit**

```bash
git add templates app/routes/meetings.py static/app.css tests/test_routes_meetings.py
git commit -m "feat(ui): meetings tree + detail with Transcript view"
```

---

## Task 5: Markdown rendering + Unknown-Speaker highlighting

**Files:**
- Create: `app/markdown.py`, `tests/test_markdown.py`
- Modify: `app/routes/meetings.py`, `templates/_meeting_detail.html`, `static/app.css`

- [ ] **Step 1: Write failing markdown unit test**

Create `tests/test_markdown.py`:

```python
from app import markdown as md


def test_headings_and_lists():
    html = md.render("# Title\n\n- a\n- b\n")
    assert "<h1>" in html and "Title" in html
    assert "<li>" in html and ">a<" in html


def test_no_script_tags():
    html = md.render("<script>alert(1)</script>\n\nhi")
    assert "<script>" not in html
    assert "hi" in html
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/test_markdown.py -v`

- [ ] **Step 3: Implement app/markdown.py**

Create `app/markdown.py`:

```python
from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})


def render(text: str) -> str:
    return _md.render(text or "")
```

`html: False` disables inline HTML passthrough, so `<script>` is rendered as literal text.

- [ ] **Step 4: Run tests — expect 2 passing**

Run: `pytest tests/test_markdown.py -v`

- [ ] **Step 5: Wire markdown into meetings route + add transcript highlighting**

In `app/routes/meetings.py`, change the detail route to pass rendered HTML and an annotated transcript:

```python
import html as html_escape
import re
from app import markdown as md_render

_UNK_RE = re.compile(r"(Unknown Speaker \d+)")


def _render_transcript(text: str) -> str:
    escaped = html_escape.escape(text)
    return _UNK_RE.sub(r'<span class="unk">\1</span>', escaped)
```

Replace the keys in the detail `TemplateResponse`:

```python
"transcript_html": _render_transcript(fs.load_transcript(m)),
"knowledge_html": md_render.render(fs.load_knowledge(m)),
"commitments_html": md_render.render(fs.load_commitments(m)),
```

- [ ] **Step 6: Update the template to use pre with |safe**

In `templates/_meeting_detail.html`, change the transcript line to:

```jinja
<pre class="transcript">{{ transcript_html|safe }}</pre>
```

- [ ] **Step 7: Highlight CSS**

Append to `static/app.css`:

```css
.transcript .unk { color: var(--warn); font-weight: 600; }
.md h1, .md h2, .md h3 { margin-top: 0.8rem; }
.md ul, .md ol { padding-left: 1.25rem; }
.md p { margin: 0.4rem 0; }
```

- [ ] **Step 8: Update meetings route tests**

Append to `tests/test_routes_meetings.py`:

```python
def test_unknown_speaker_highlighted(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-16 17-01-16")
    assert 'class="unk">Unknown Speaker 1' in r.text


def test_knowledge_view_renders_markdown(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43?view=knowledge")
    assert "<h1>" in r.text or "<h1 " in r.text
```

- [ ] **Step 9: Run all tests**

Run: `pytest tests/test_routes_meetings.py tests/test_markdown.py -v`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add app/markdown.py app/routes/meetings.py templates/_meeting_detail.html static/app.css tests/test_markdown.py tests/test_routes_meetings.py
git commit -m "feat(ui): render markdown + highlight Unknown Speaker lines"
```

---

## Task 6: Video streaming with HTTP Range

**Files:**
- Create: `app/video.py`, `app/routes/media.py`, `tests/test_video.py`
- Modify: `server.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_video.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return TestClient(create_app())


def test_meeting_video_200(client):
    r = client.get("/video/meeting/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/")
    assert r.headers.get("accept-ranges") == "bytes"


def test_meeting_video_range_206(client):
    r = client.get("/video/meeting/multiturbo/2026-04-14 17-00-43",
                   headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.headers["content-range"].startswith("bytes 0-3/")
    assert len(r.content) == 4


def test_meeting_video_404(client):
    r = client.get("/video/meeting/nope/missing")
    assert r.status_code == 404


def test_clip_video_200(client):
    r = client.get("/video/clip/Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov")
    assert r.status_code == 200


def test_clip_video_rejects_traversal(client):
    r = client.get("/video/clip/..%2Fsecrets.mov")
    assert r.status_code in (400, 404)
```

- [ ] **Step 2: Run — expect 404/errors**

Run: `pytest tests/test_video.py -v`

- [ ] **Step 3: Implement `app/video.py`**

Create `app/video.py`:

```python
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
```

- [ ] **Step 4: Implement `app/routes/media.py`**

Create `app/routes/media.py`:

```python
from fastapi import APIRouter, HTTPException, Request

from app import fs, video

router = APIRouter()


@router.get("/video/meeting/{subdir}/{stem}")
def stream_meeting(subdir: str, stem: str, request: Request):
    m = fs.find_meeting(subdir, stem)
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
```

- [ ] **Step 5: Register in server.py**

In `create_app`, add:

```python
from app.routes import media
app.include_router(media.router)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_video.py -v`
Expected: `5 passed`.

- [ ] **Step 7: Commit**

```bash
git add app/video.py app/routes/media.py server.py tests/test_video.py
git commit -m "feat(ui): range-aware video streaming for meetings + clips"
```

---

## Task 7: Speakers page — queue listing with inline player

**Files:**
- Create: `templates/_clip_card.html`, `templates/_toast.html`, `tests/test_routes_speakers.py`
- Modify: `templates/speakers.html`, `app/routes/speakers.py`, `static/app.css`

- [ ] **Step 1: Failing tests**

Create `tests/test_routes_speakers.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return TestClient(create_app())


def test_speakers_lists_pending_clips(client):
    r = client.get("/speakers")
    assert r.status_code == 200
    assert "Unknown Speaker 1" in r.text
    assert "01m08s" in r.text
    assert "2026-04-16 17-01-16" in r.text


def test_speakers_includes_known_names_datalist(client):
    r = client.get("/speakers")
    # Autocomplete datalist should include existing speakers
    assert "David Fuller" in r.text
    assert "Darwin Henao" in r.text
    assert "<datalist" in r.text


def test_speakers_count_in_nav(client):
    r = client.get("/speakers")
    # Warning pill with count = 2 (fixture has 2 clips)
    assert '<span class="count">2</span>' in r.text
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/test_routes_speakers.py -v`

- [ ] **Step 3: Clip card partial**

Create `templates/_clip_card.html`:

```jinja
<article class="clip-card" id="clip-{{ clip.filename|urlencode }}">
  <video class="clip-video" controls preload="metadata"
         src="/video/clip/{{ clip.filename|urlencode }}"></video>
  <div class="clip-meta">
    <div class="clip-label">{{ clip.raw_label }}</div>
    <div class="clip-source">{{ clip.source_stem }} · @ {{ clip.timestamp_text }}</div>
  </div>
  <form class="clip-form"
        hx-post="/speakers/label"
        hx-target="closest .speakers-queue"
        hx-swap="outerHTML">
    <input type="hidden" name="filename" value="{{ clip.filename }}">
    <input name="name" list="known-names" placeholder="Who is this?" autocomplete="off" required>
    <button type="submit">Save</button>
  </form>
</article>
```

Create `templates/_toast.html`:

```jinja
{% if labels_since_reset %}
<div class="toast" id="reclassify-toast">
  <span>You've labeled {{ labels_since_reset }} speaker(s).</span>
  <form hx-post="/speakers/reclassify" hx-target="body" hx-swap="outerHTML">
    <button type="submit">Reclassify {{ unknown_meetings_count }} meeting(s) now →</button>
  </form>
</div>
{% endif %}
```

- [ ] **Step 4: Update speakers.html**

Replace `templates/speakers.html`:

```jinja
{% extends "base.html" %}
{% block title %}Speakers — Transcribe{% endblock %}
{% block content %}
<section class="speakers-page">
  <div class="speakers-queue">
    {% if clips %}
      {% for clip in clips %}
        {% include "_clip_card.html" %}
      {% endfor %}
    {% else %}
      <p class="subtitle">No clips awaiting labels. You're all caught up.</p>
    {% endif %}
  </div>

  <datalist id="known-names">
    {% for n in known_names %}<option value="{{ n }}">{% endfor %}
  </datalist>

  {% include "_toast.html" %}
</section>
{% endblock %}
```

- [ ] **Step 5: Update route**

Replace `app/routes/speakers.py`:

```python
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import fs

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _unknown_meetings_count() -> int:
    return sum(1 for m in fs.list_meetings() if m.unknown_count > 0)


@router.get("/speakers")
def speakers_index(request: Request):
    clips = fs.list_unknown_clips()
    return templates.TemplateResponse(
        "speakers.html",
        {
            "request": request,
            "active_tab": "speakers",
            "clips": clips,
            "known_names": fs.list_known_names(),
            "speakers_count": len(clips),
            "pipeline_running": False,
            "labels_since_reset": 0,  # wired up in Task 9
            "unknown_meetings_count": _unknown_meetings_count(),
        },
    )
```

- [ ] **Step 6: CSS**

Append to `static/app.css`:

```css
.speakers-queue { display: flex; flex-direction: column; gap: 0.75rem; }
.clip-card { display: grid; grid-template-columns: 320px 1fr auto; gap: 0.75rem; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem 0.75rem; align-items: center; }
.clip-video { width: 320px; border-radius: 6px; background: black; }
.clip-meta .clip-label { font-weight: 600; font-size: 0.9rem; }
.clip-meta .clip-source { color: var(--muted); font-size: 0.8rem; }
.clip-form { display: flex; gap: 0.4rem; }
.clip-form input { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.5rem; font-size: 0.85rem; min-width: 180px; }
.clip-form button { background: var(--accent); color: white; border: none; border-radius: 6px; padding: 0.35rem 0.75rem; font-weight: 600; font-size: 0.85rem; cursor: pointer; }
.toast { position: sticky; bottom: 1rem; margin: 1rem auto 0; max-width: 540px; background: var(--panel); border: 1px solid var(--accent); border-radius: 10px; padding: 0.75rem 1rem; display: flex; gap: 0.75rem; align-items: center; box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
.toast button { background: var(--accent); color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 6px; font-weight: 600; cursor: pointer; }
```

- [ ] **Step 7: Run tests — expect 3 passing**

Run: `pytest tests/test_routes_speakers.py -v`

- [ ] **Step 8: Commit**

```bash
git add templates/speakers.html templates/_clip_card.html templates/_toast.html app/routes/speakers.py static/app.css tests/test_routes_speakers.py
git commit -m "feat(ui): speakers queue with inline clip players + autocomplete"
```

---

## Task 8: Clip labeling — `label_clip` + counter

**Files:**
- Create: `app/clips.py`, `tests/test_clips.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_clips.py`:

```python
import pytest

from app import clips, fs
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture(autouse=True)
def anchor(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    clips.reset_counter()
    yield


def test_label_clip_moves_and_renames():
    result = clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    assert result.new_path.exists()
    assert result.new_path.parent == fs.KNOWN_NAMES_TO_USE
    assert result.new_path.name == "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s.mov"
    # Original removed
    assert not (fs.KNOWN_NAMES_TO_CLASSIFY /
                "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov").exists()


def test_label_clip_dedup_suffix_when_target_exists():
    # First label
    clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    # Create a duplicate-named source
    src = fs.KNOWN_NAMES_TO_CLASSIFY / "Unknown Speaker X - 2026-04-16 17-01-16 - 01m08s.mov"
    src.write_bytes(b"\x00")
    r = clips.label_clip(src.name, "Alejandra Gomez")
    assert r.new_path.name == "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s (2).mov"


def test_label_clip_rejects_traversal():
    with pytest.raises(ValueError):
        clips.label_clip("../etc/passwd", "Anyone")


def test_counter_increments_and_resets():
    assert clips.labels_since_reset() == 0
    clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    assert clips.labels_since_reset() == 1
    clips.label_clip(
        "Unknown Speaker 2 - 2026-04-16 17-01-16 - 03m22s.mov",
        "Maria Lopez",
    )
    assert clips.labels_since_reset() == 2
    clips.reset_counter()
    assert clips.labels_since_reset() == 0
```

- [ ] **Step 2: Run — expect import error**

Run: `pytest tests/test_clips.py -v`

- [ ] **Step 3: Implement app/clips.py**

Create `app/clips.py`:

```python
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

    # Build destination name: "<name> - <source_stem> - <ts>.mov"
    # Preserve context from the source filename after the raw label.
    # Source format: "<raw_label> - <source_stem> - <ts>.mov"
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_clips.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/clips.py tests/test_clips.py
git commit -m "feat(ui): label_clip + labels-since-reset counter"
```

---

## Task 9: POST /speakers/label — wire form → clip move → HTMX re-render

**Files:**
- Modify: `app/routes/speakers.py`
- Modify: `tests/test_routes_speakers.py`

- [ ] **Step 1: New failing tests**

Append to `tests/test_routes_speakers.py`:

```python
from app import clips


def test_post_label_moves_clip_and_increments_counter(client, tmp_path, monkeypatch):
    clips.reset_counter()
    r = client.post(
        "/speakers/label",
        data={
            "filename": "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
            "name": "Alejandra Gomez",
        },
    )
    assert r.status_code == 200
    # Response is the updated queue fragment
    assert "Unknown Speaker 1" not in r.text  # it was the first clip; now gone
    assert "Unknown Speaker 2" in r.text
    assert "Reclassify" in r.text  # toast visible
    # Physically moved
    assert (tmp_path / "known-names" / "to-use" /
            "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s.mov").exists()
    assert clips.labels_since_reset() == 1
```

- [ ] **Step 2: Run — expect 405/404**

Run: `pytest tests/test_routes_speakers.py::test_post_label_moves_clip_and_increments_counter -v`

- [ ] **Step 3: Extend speakers route**

Modify `app/routes/speakers.py` — add at the top:

```python
from fastapi import Form
from fastapi.responses import HTMLResponse

from app import clips
```

Update the GET handler to use `clips.labels_since_reset()`:

```python
"labels_since_reset": clips.labels_since_reset(),
```

Add the POST handler:

```python
@router.post("/speakers/label", response_class=HTMLResponse)
def label(request: Request, filename: str = Form(...), name: str = Form(...)):
    clips.label_clip(filename, name)
    # Re-render the queue + toast; HTMX swaps .speakers-queue's outerHTML
    remaining = fs.list_unknown_clips()
    html = templates.get_template("_queue_with_toast.html").render(
        request=request,
        clips=remaining,
        known_names=fs.list_known_names(),
        labels_since_reset=clips.labels_since_reset(),
        unknown_meetings_count=_unknown_meetings_count(),
    )
    return HTMLResponse(html)
```

- [ ] **Step 4: Create the combined partial**

Create `templates/_queue_with_toast.html`:

```jinja
<div class="speakers-queue">
  {% if clips %}
    {% for clip in clips %}
      {% include "_clip_card.html" %}
    {% endfor %}
  {% else %}
    <p class="subtitle">No clips awaiting labels. You're all caught up.</p>
  {% endif %}
</div>
<datalist id="known-names">
  {% for n in known_names %}<option value="{{ n }}">{% endfor %}
</datalist>
{% include "_toast.html" %}
```

Update `templates/speakers.html` to use the same partial so the HTMX swap target matches:

```jinja
{% extends "base.html" %}
{% block title %}Speakers — Transcribe{% endblock %}
{% block content %}
<section class="speakers-page">
  {% include "_queue_with_toast.html" %}
</section>
{% endblock %}
```

Update `templates/_clip_card.html` — the form's `hx-target` now points to the grandparent `.speakers-page`:

```jinja
<form class="clip-form"
      hx-post="/speakers/label"
      hx-target="closest .speakers-page"
      hx-swap="innerHTML">
  …
</form>
```

- [ ] **Step 5: Run all speakers tests**

Run: `pytest tests/test_routes_speakers.py -v`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/routes/speakers.py templates/speakers.html templates/_clip_card.html templates/_queue_with_toast.html tests/test_routes_speakers.py
git commit -m "feat(ui): POST /speakers/label moves clip, re-renders queue + toast"
```

---

## Task 10: Pipeline runner — subprocess + SSE fanout

**Files:**
- Create: `app/pipeline.py`, `tests/helpers/fake_pipeline.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Write the fake pipeline script**

Create `tests/helpers/fake_pipeline.py`:

```python
"""Emits three lines with a tiny delay, then exits. Used for runner tests."""
import sys
import time

for line in ("starting", "middle", "done"):
    print(line, flush=True)
    time.sleep(0.05)
sys.exit(0)
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_pipeline.py`:

```python
import asyncio
import sys
from pathlib import Path

import pytest

from app import pipeline

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture(autouse=True)
def clean_runner():
    pipeline.get_runner().reset_for_tests()
    yield
    pipeline.get_runner().reset_for_tests()


def test_start_and_collect_lines():
    r = pipeline.get_runner()
    assert not r.is_running()
    r.start([sys.executable, str(HELPER)])
    # Poll until process finishes
    for _ in range(200):
        if not r.is_running():
            break
        import time; time.sleep(0.05)
    assert not r.is_running()
    lines = r.history()
    content = "\n".join(lines)
    assert "starting" in content
    assert "done" in content
    assert r.last_return_code == 0


def test_concurrent_start_raises():
    r = pipeline.get_runner()
    r.start([sys.executable, str(HELPER)])
    try:
        with pytest.raises(pipeline.AlreadyRunning):
            r.start([sys.executable, str(HELPER)])
    finally:
        # Wait for completion to leave a clean runner
        for _ in range(200):
            if not r.is_running(): break
            import time; time.sleep(0.05)


@pytest.mark.asyncio
async def test_subscribe_yields_live_lines():
    r = pipeline.get_runner()
    r.start([sys.executable, str(HELPER)])
    gen = r.subscribe()
    seen = []
    # Collect lines until we see the sentinel "EXIT 0"
    async for evt in gen:
        seen.append(evt)
        if evt.startswith("EXIT "):
            break
    content = "\n".join(seen)
    assert "starting" in content
    assert "done" in content
    assert "EXIT 0" in content
```

Add `pytest-asyncio` to requirements.txt:

```
pytest-asyncio>=0.23
```

Run: `pip install pytest-asyncio`

Add `tests/conftest.py` asyncio mode by appending:

```python
import pytest
pytest_plugins = ("pytest_asyncio",)
```

Configure asyncio mode in a new `pyproject.toml` (if none exists) or add a `pytest.ini`:

Create `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Run — expect ImportError**

Run: `pytest tests/test_pipeline.py -v`

- [ ] **Step 4: Implement `app/pipeline.py`**

Create `app/pipeline.py`:

```python
from __future__ import annotations

import asyncio
import subprocess
import threading
from collections import deque
from typing import AsyncIterator, Callable


class AlreadyRunning(Exception):
    pass


class PipelineRunner:
    def __init__(self, history_max: int = 500):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._history: deque[str] = deque(maxlen=history_max)
        self._subscribers: list[asyncio.Queue[str]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last_return_code: int | None = None
        self._on_complete: Callable[[list[str], int], None] | None = None

    # --- public API -------------------------------------------------

    def set_on_complete(self, cb: Callable[[list[str], int], None]) -> None:
        """Invoked after the subprocess exits: cb(argv, returncode)."""
        self._on_complete = cb

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def history(self) -> list[str]:
        return list(self._history)

    def start(self, argv: list[str], cwd: str | None = None) -> None:
        with self._lock:
            if self.is_running():
                raise AlreadyRunning()
            self._history.clear()
            self.last_return_code = None
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=cwd,
            )
        threading.Thread(
            target=self._pump,
            args=(self._proc, list(argv)),
            daemon=True,
        ).start()

    def subscribe(self) -> AsyncIterator[str]:
        """Async generator yielding history (first) then live lines, then final 'EXIT N'."""
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        q: asyncio.Queue[str] = asyncio.Queue()
        # seed with history
        for line in self._history:
            q.put_nowait(line)
        self._subscribers.append(q)

        async def _gen():
            try:
                while True:
                    item = await q.get()
                    yield item
                    if item.startswith("EXIT "):
                        return
            finally:
                if q in self._subscribers:
                    self._subscribers.remove(q)

        return _gen()

    def reset_for_tests(self) -> None:
        """Only for tests — block until current run is done, then clear state."""
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._history.clear()
        self._subscribers.clear()
        self.last_return_code = None

    # --- internals --------------------------------------------------

    def _fanout(self, line: str) -> None:
        self._history.append(line)
        if self._loop is None:
            return
        for q in list(self._subscribers):
            self._loop.call_soon_threadsafe(q.put_nowait, line)

    def _pump(self, proc: subprocess.Popen, argv: list[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            self._fanout(raw.rstrip("\n"))
        proc.wait()
        self.last_return_code = proc.returncode
        self._fanout(f"EXIT {proc.returncode}")
        if self._on_complete is not None:
            try:
                self._on_complete(argv, proc.returncode)
            except Exception:
                pass


_runner: PipelineRunner | None = None


def get_runner() -> PipelineRunner:
    global _runner
    if _runner is None:
        _runner = PipelineRunner()
    return _runner
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline.py tests/helpers/fake_pipeline.py tests/test_pipeline.py pytest.ini requirements.txt
git commit -m "feat(ui): PipelineRunner with subprocess + SSE fanout"
```

---

## Task 11: Pipeline page — form, run, SSE stream

**Files:**
- Modify: `templates/pipeline.html`, `app/routes/pipeline_routes.py`, `static/app.css`
- Create: `tests/test_routes_pipeline.py`

- [ ] **Step 1: Failing tests**

Create `tests/test_routes_pipeline.py`:

```python
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs, pipeline
from server import create_app
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    pipeline.get_runner().reset_for_tests()
    yield TestClient(create_app())
    pipeline.get_runner().reset_for_tests()


def test_pipeline_page_renders_form(client):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Run" in r.text
    # scope + mode fields present
    assert 'name="scope"' in r.text
    assert 'name="mode"' in r.text


def test_run_starts_subprocess_and_redirects(client, monkeypatch):
    # Replace process.py invocation with the fake helper
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, str(HELPER)],
    )
    r = client.post("/pipeline/run",
                    data={"scope": "all", "mode": "new"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"

    # Wait for background process to finish
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)
    assert pipeline.get_runner().last_return_code == 0


def test_second_run_while_active_returns_409(client, monkeypatch):
    # Launch a long-running fake
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, "-c", "import time; time.sleep(1)"],
    )
    r1 = client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                     follow_redirects=False)
    assert r1.status_code == 303

    r2 = client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                     follow_redirects=False)
    assert r2.status_code == 409


def test_stream_emits_history_and_exit(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, str(HELPER)],
    )
    client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                follow_redirects=False)
    # Wait until done, then request the stream — history should replay
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    r = client.get("/pipeline/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "starting" in body
    assert "done" in body
    assert "EXIT 0" in body
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/test_routes_pipeline.py -v`

- [ ] **Step 3: Implement the route**

Replace `app/routes/pipeline_routes.py`:

```python
import sys
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import fs, pipeline, clips

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

ROOT = Path(__file__).parent.parent.parent
PROCESS_PY = ROOT / "process.py"


def resolve_argv(scope: str, mode: str) -> list[str]:
    """Convert form fields → argv for process.py."""
    argv: list[str] = [sys.executable, str(PROCESS_PY)]
    if scope and scope != "all":
        argv.append(scope)  # path relative to cwd
    if mode == "reclassify":
        argv.append("--reclassify")
    return argv


def _meetings_as_scopes() -> list[str]:
    """All selectable scopes: 'all', each subdir, each individual .mov."""
    out = ["all"]
    subdirs = sorted({m.subdir for m in fs.list_meetings() if m.subdir})
    out += [f"data/{s}" for s in subdirs]
    out += [str(m.mov_path.relative_to(ROOT)) for m in fs.list_meetings()]
    return out


@router.get("/pipeline")
def pipeline_index(request: Request):
    r = pipeline.get_runner()
    return templates.TemplateResponse(
        "pipeline.html",
        {
            "request": request,
            "active_tab": "pipeline",
            "scopes": _meetings_as_scopes(),
            "is_running": r.is_running(),
            "history": r.history(),
            "speakers_count": len(fs.list_unknown_clips()),
            "pipeline_running": r.is_running(),
        },
    )


@router.post("/pipeline/run")
def pipeline_run(scope: str = Form("all"), mode: str = Form("new")):
    r = pipeline.get_runner()
    argv = resolve_argv(scope, mode)

    # Install the on-complete hook: reset label counter if reclassify succeeded
    def on_complete(argv: list[str], rc: int) -> None:
        if rc == 0 and "--reclassify" in argv:
            clips.reset_counter()

    r.set_on_complete(on_complete)

    try:
        r.start(argv, cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(status_code=409, detail="Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.get("/pipeline/stream")
async def pipeline_stream():
    r = pipeline.get_runner()

    async def event_source():
        async for line in r.subscribe():
            yield f"data: {line}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

- [ ] **Step 4: Update pipeline.html**

Replace `templates/pipeline.html`:

```jinja
{% extends "base.html" %}
{% block title %}Pipeline — Transcribe{% endblock %}
{% block content %}
<section class="pipeline-page">
  <form method="post" action="/pipeline/run" class="run-form">
    <label>Scope:
      <select name="scope">
        {% for s in scopes %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
      </select>
    </label>
    <label><input type="radio" name="mode" value="new" checked> New only</label>
    <label><input type="radio" name="mode" value="reclassify"> Reclassify</label>
    <button type="submit" {% if is_running %}disabled{% endif %}>▶ Run</button>
  </form>

  <pre id="log" class="log">
{% for line in history %}{{ line }}
{% endfor %}</pre>

  <script>
    (function () {
      const log = document.getElementById('log');
      const es = new EventSource('/pipeline/stream');
      es.onmessage = (e) => {
        log.textContent += '\n' + e.data;
        log.scrollTop = log.scrollHeight;
        if (e.data.startsWith('EXIT ')) {
          es.close();
          setTimeout(() => window.location.reload(), 500); // re-enable Run button
        }
      };
    })();
  </script>
</section>
{% endblock %}
```

- [ ] **Step 5: CSS**

Append to `static/app.css`:

```css
.pipeline-page { display: flex; flex-direction: column; gap: 0.75rem; }
.run-form { display: flex; gap: 0.75rem; align-items: center; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem 0.75rem; }
.run-form select, .run-form button { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.6rem; font-size: 0.85rem; }
.run-form button { background: var(--accent); color: white; border: none; font-weight: 600; cursor: pointer; }
.run-form button[disabled] { opacity: 0.5; cursor: not-allowed; }
pre.log { background: #0a0a0a; color: #9df; padding: 0.75rem 1rem; border-radius: 8px; font-family: ui-monospace, monospace; font-size: 0.75rem; line-height: 1.5; min-height: 200px; max-height: 60vh; overflow-y: auto; white-space: pre-wrap; margin: 0; }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_routes_pipeline.py -v`
Expected: `4 passed`.

- [ ] **Step 7: Commit**

```bash
git add app/routes/pipeline_routes.py templates/pipeline.html static/app.css tests/test_routes_pipeline.py
git commit -m "feat(ui): pipeline tab with run form + SSE streaming log"
```

---

## Task 12: Per-meeting actions — re-extract, reclassify-one

**Files:**
- Modify: `app/routes/meetings.py`, `templates/_meeting_detail.html`, `tests/test_routes_meetings.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_routes_meetings.py`:

```python
import sys
from pathlib import Path

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


def test_post_reextract_starts_runner(app_with_tree, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.meetings.build_reextract_argv",
        lambda m: [sys.executable, str(HELPER)],
    )
    r = app_with_tree.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/reextract",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    # Drain
    import time
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)


def test_post_reclassify_one_starts_runner(app_with_tree, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.meetings.build_reclassify_argv",
        lambda m: [sys.executable, str(HELPER)],
    )
    r = app_with_tree.post(
        "/meetings/multiturbo/2026-04-16 17-01-16/reclassify",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    import time
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)
```

- [ ] **Step 2: Run — expect 405**

Run: `pytest tests/test_routes_meetings.py -v`

- [ ] **Step 3: Extend meetings route**

Modify `app/routes/meetings.py` — add at the top:

```python
import sys
from fastapi.responses import RedirectResponse
from app import pipeline

ROOT = Path(__file__).parent.parent.parent
EXTRACT_PY = ROOT / "extract.py"
PROCESS_PY = ROOT / "process.py"


def build_reextract_argv(m: fs.Meeting) -> list[str]:
    return [sys.executable, str(EXTRACT_PY), str(m.transcript_path.relative_to(ROOT)), "--force"]


def build_reclassify_argv(m: fs.Meeting) -> list[str]:
    return [sys.executable, str(PROCESS_PY), str(m.mov_path.relative_to(ROOT)), "--reclassify"]
```

Add the POST handlers:

```python
@router.post("/meetings/{subdir}/{stem}/reextract")
def reextract(subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(build_reextract_argv(m), cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)


@router.post("/meetings/{subdir}/{stem}/reclassify")
def reclassify_one(subdir: str, stem: str):
    m = fs.find_meeting(subdir, stem)
    if m is None:
        raise HTTPException(404)
    try:
        pipeline.get_runner().start(build_reclassify_argv(m), cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(409, "Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)
```

- [ ] **Step 4: Template buttons**

Modify `templates/_meeting_detail.html` — in the `<div class="actions">`, replace the placeholder with:

```jinja
<form method="post" action="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}/reextract" style="display:inline;">
  <button class="mini-btn" type="submit" {% if not meeting.has_transcript %}disabled{% endif %}>↻ Re-extract</button>
</form>
<form method="post" action="/meetings/{{ meeting.subdir }}/{{ meeting.stem }}/reclassify" style="display:inline;">
  <button class="mini-btn" type="submit">🔄 Reclassify</button>
</form>
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_routes_meetings.py -v`
Expected: all green (original 6 + 2 new = 8).

- [ ] **Step 6: Commit**

```bash
git add app/routes/meetings.py templates/_meeting_detail.html tests/test_routes_meetings.py
git commit -m "feat(ui): per-meeting re-extract + reclassify buttons"
```

---

## Task 13: Speakers toast — reclassify-all button

**Files:**
- Modify: `app/routes/speakers.py`, `tests/test_routes_speakers.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_routes_speakers.py`:

```python
import sys
import time
from pathlib import Path

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


def test_post_reclassify_all_starts_runner(client, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.speakers.build_reclassify_all_argv",
        lambda: [sys.executable, str(HELPER)],
    )
    r = client.post("/speakers/reclassify", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)
```

- [ ] **Step 2: Run — expect 405**

Run: `pytest tests/test_routes_speakers.py -v`

- [ ] **Step 3: Extend speakers route**

Modify `app/routes/speakers.py` — add at the top:

```python
import sys
from fastapi.responses import RedirectResponse
from app import pipeline

ROOT = Path(__file__).parent.parent.parent
PROCESS_PY = ROOT / "process.py"


def build_reclassify_all_argv() -> list[str]:
    return [sys.executable, str(PROCESS_PY), "--reclassify"]
```

Add the POST handler:

```python
@router.post("/speakers/reclassify")
def reclassify_all():
    try:
        pipeline.get_runner().start(build_reclassify_all_argv(), cwd=str(ROOT))
    except pipeline.AlreadyRunning:
        raise HTTPException(status_code=409, detail="Pipeline already running")
    return RedirectResponse("/pipeline", status_code=303)
```

Also add:

```python
from fastapi import HTTPException
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_routes_speakers.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/routes/speakers.py tests/test_routes_speakers.py
git commit -m "feat(ui): toast reclassify-all button wired to pipeline runner"
```

---

## Task 14: Documentation + manual verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append UI section to CLAUDE.md**

Add to the bottom of `CLAUDE.md`:

```markdown
## Web UI (Round 1)

Local-only FastAPI + HTMX app.

```bash
python server.py  # starts on http://127.0.0.1:8000
pytest            # runs the UI test suite
```

Three tabs: **Meetings** (browse transcripts + knowledge + commitments, re-extract / reclassify per meeting), **Speakers** (queue of pending clips from `known-names/to-classify/` — label + batch-reclassify), **Pipeline** (scope + mode form, live log streaming via SSE, one run at a time).

The server is additive — the existing `transcribe.py`, `extract.py`, `process.py` CLIs keep working unchanged.
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 3: Manual end-to-end verification**

Per the spec's Verification section:

1. `python server.py` → open `http://localhost:8000`.
2. **Meetings:** pick a processed meeting; confirm Transcript shows with Unknown Speakers highlighted; Knowledge and Commitments render as markdown; click "Open video" → modal player. Badges match each meeting's unknown count.
3. **Speakers:** play a clip inline, type a name (use autocomplete), Save → the clip moves from `known-names/to-classify/` to `known-names/to-use/`, queue re-renders, toast appears with "Reclassify N meetings now". Label a second clip → counter increments; file moved.
4. Click the toast → land on Pipeline tab, log streams live. On completion, counter is reset (reclassify mode).
5. **Pipeline:** pick a scope = `data/multiturbo`, mode = "New only", Run → log streams. Second Run click while active is rejected (409). When done, page reloads, Run re-enabled.
6. Regression: open a terminal, run `python process.py data/multiturbo` — still works; UI reflects new transcript status when you reload.

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs: add Round 1 web UI section to CLAUDE.md"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-review notes

**Spec coverage:**
- Browse meetings / transcript / knowledge / commitments → Tasks 4, 5
- Unknown-Speaker highlighting → Task 5
- Video playback with Range → Task 6
- Speakers queue + inline player + autocomplete → Task 7
- Clip labeling with rename+move + dedup → Task 8
- Accumulating toast + counter reset on reclassify success → Tasks 8, 9, 11, 13
- Pipeline runner + single-run lock + SSE → Tasks 10, 11
- Per-meeting re-extract / reclassify → Task 12
- Batch reclassify → Task 13
- Documentation → Task 14

**Deferred per spec:** directory watcher, auto-categorize, transcript editing, search, tags/DB — all Round 2+.

**Type consistency:** `Meeting`, `Clip`, `LabelResult`, `PipelineRunner`, `AlreadyRunning` names match across task references. `labels_since_reset()` / `reset_counter()` naming stays consistent between `clips.py` and route handlers.
