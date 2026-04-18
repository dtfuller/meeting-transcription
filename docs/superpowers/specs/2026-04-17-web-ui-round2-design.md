# Web UI — Round 2 design: ingestion watcher + auto-categorize

## Context

Round 1 shipped a local web UI (FastAPI + HTMX) with three tabs: **Meetings** (browse transcripts/knowledge/commitments), **Speakers** (label unknown speakers), **Pipeline** (trigger + live-tail CLI runs). It's fully driven by the filesystem — no background work, every action is explicit.

Round 2 addresses the manual parts of the current workflow:

- **New recordings today:** the user records meetings into a macOS folder outside the repo (e.g. `~/Movies/<something>`), then manually copies each `.mov` into the correct `data/<subdir>/` before running the pipeline. Error-prone, easy to forget one.
- **Categorization today:** the subdir (e.g. `data/multiturbo` vs `data/check-in-and-pickup-wall`) is chosen manually by the human. There are no topic/people tags beyond the implicit subdir name — no way to filter "all meetings with Darwin Henao" or "everything that mentions Rappi's last-mile policy".

Round 2 introduces:

1. A **directory watcher** that sees new recordings in an external folder, copies them to `data/_inbox/`, and kicks the full pipeline automatically.
2. An **Inbox tab** where finished meetings wait for the human to approve an LLM-proposed **subdir + tags**. On Apply, the meeting moves to its target `data/<subdir>/` and its tags are persisted.
3. **Tag display + filter** in the Meetings tab so the archive becomes queryable.

Scope is narrow and additive: `transcribe.py`, `extract.py`, `process.py`, and the Round 1 routes are untouched except for a small set of necessary extensions.

## Non-goals

- Transcript editing, cross-meeting full-text search, commitments dashboards — all Round 3.
- Multi-user, auth, remote deployment.
- Running the watcher or auto-categorize as a standalone CLI (it only lives inside `server.py`).
- Moving the *original* recording in `~/Movies/...` — the watcher **copies**, never deletes the source.
- Renaming files. Stems stay as-is (e.g. `2026-04-16 17-01-16.mov`). Only the subdir changes when routed.
- Tag schemas. The LLM produces freeform `(name, type)` pairs with types constrained to `"person" | "topic" | "project"`; no controlled vocab.

## High-level shape

```
~/Movies/Meetings/*.mov              (external source, user-configured via WATCH_DIR env var)
          │   watchdog observer detects + waits for stability
          ▼
data/_inbox/<stem>.mov               (copy; original is untouched)
          │   process.py kicks off automatically
          ▼
transcripts/_inbox/<stem>.txt        (transcribe)
information/_inbox/<stem>-*.md       (extract)
          │   auto-categorize runs: Claude reads knowledge/commitments + existing subdirs + known speakers
          ▼
inbox_proposals[stem] = {subdir, tags}   (persisted in ui.db until applied)
          │   UI shows the proposal in the Inbox tab
          │   user approves (optionally editing)
          ▼
data/<subdir>/<stem>.mov             (filesystem move from _inbox → target)
transcripts/<subdir>/<stem>.txt
information/<subdir>/<stem>-*.md
meeting_tags[stem] = [...]           (persisted in ui.db)
```

## Stack additions

- `watchdog>=4.0` — the file-system observer library.
- SQLite via the Python stdlib `sqlite3` — no ORM, no Alembic. Schema is 3 tables; migrations are inline `CREATE TABLE IF NOT EXISTS`.
- No new frontend deps. Tags render as small chips; the Inbox tab reuses existing CSS patterns (card grid like Speakers).

## Configuration

One new env var (in `.env`, loaded by the existing `dotenv` setup):

- `WATCH_DIR=/Users/davidfuller/Movies/Meetings` — absolute path to the folder the watcher monitors. If unset, the watcher is disabled and the Inbox tab still works (for files manually dropped into `data/_inbox/`).

No change to `.env.example` format — add one line.

## Data model (SQLite at `<repo>/ui.db`, gitignored)

```sql
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
  proposed_tags_json TEXT NOT NULL,  -- JSON list of {name, type}
  status             TEXT NOT NULL CHECK(status IN ('pending', 'transcribing', 'analyzing', 'ready', 'error')),
  error_message      TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS meeting_tags_by_tag ON meeting_tags(tag_name, tag_type);
```

`stem` is the meeting's filename minus `.mov`, used everywhere else in the app too. On route, the `stem` is stable — only the subdir moves.

## New modules

- `app/store.py` — thin sqlite wrapper: `connect()`, `init_schema()`, `save_proposal()`, `get_proposal()`, `list_pending_proposals()`, `delete_proposal()`, `set_meeting_tags()`, `list_meeting_tags()`, `list_all_tags()`. No ORM; plain `?`-parameterized SQL.
- `app/watcher.py` — watchdog observer: `Watcher` class wrapping `PollingObserver` (more reliable across macOS than the native `FSEventsObserver` for external drives/iCloud folders). Exposes `start(watch_dir, on_new_file)`, `stop()`, `status()`. File-stability heuristic: modification time + size unchanged for ≥3 seconds triggers `on_new_file(path)`.
- `app/ingest.py` — the "copy to _inbox + kick pipeline" coordinator. On `on_new_file(path)`:
  1. Compute `stem = path.stem`. If `data/_inbox/<stem>.mov` already exists, skip.
  2. Copy `path → data/_inbox/<stem>.mov`.
  3. Insert `inbox_proposals` row with `status='transcribing'`, empty proposal fields.
  4. Kick `PipelineRunner.start([python, process.py, data/_inbox/<stem>.mov], on_complete=_on_pipeline_done)`.
  5. `_on_pipeline_done` runs auto-categorize and updates `status='ready'` (or `status='error'` on failure).
- `app/categorize.py` — LLM proposer. Input: transcript + knowledge.md + commitments.md + existing subdirs list + `list_known_names()`. Output: `{subdir: str, tags: [{name, type}]}`. Uses the existing Anthropic client pattern from `extract.py:42-48`.
- `app/routes/inbox.py` — new router:
  - `GET /inbox` — tab page listing proposals with status chips.
  - `POST /inbox/{stem}/apply` — form body: `target_subdir`, repeated `tag_name` + `tag_type` pairs. Does the filesystem moves (`data/_inbox/<stem>.* → data/<target_subdir>/<stem>.*`, same for `transcripts/` and `information/`), writes tags to `meeting_tags`, deletes the proposal row. Redirects to `/meetings/<target_subdir>/<stem>`.
  - `POST /inbox/{stem}/dismiss` — removes from the Inbox queue without moving files (leaves the files in `data/_inbox/`, removes the `inbox_proposals` row). For when the user wants to handle the meeting by hand in the Meetings tab.
  - `POST /watcher/start`, `POST /watcher/stop` — lifecycle.
- `templates/inbox.html` + `templates/_inbox_card.html` — the new tab + card partial.

## Modified modules

- `app/fs.py` — expose the `_inbox` subdir consistently. `list_meetings()` already walks `data/` recursively, so `_inbox` meetings naturally appear there; we want to **exclude** them from the Meetings tree (they shouldn't look "routed" yet) and surface only in the Inbox tab. Add a `list_meetings(include_inbox=False)` parameter; default behavior excludes `_inbox`.
- `app/routes/meetings.py` — pass `include_inbox=False` (already the default after the `fs.py` change). When rendering a meeting row in the tree, attach tag chips read from `store.list_meeting_tags(stem)`.
- `app/routes/pipeline_routes.py` and `app/routes/speakers.py` — both read counts (`speakers_count`, `pipeline_running`). Add `inbox_count` to the context so the nav pill on the new Inbox tab works on every page. Pattern already used for `speakers_count`.
- `templates/base.html` — add the fourth tab link: `<a href="/inbox" class="tab {% if active_tab == 'inbox' %}active{% endif %}">Inbox {% if inbox_count %}<span class="count">{{ inbox_count }}</span>{% endif %}</a>`.
- `server.py` — on startup, `app.store.init_schema()`, and (if `WATCH_DIR` is set) start the watcher thread. Graceful shutdown hook stops the observer.
- `requirements.txt` — add `watchdog>=4.0`.
- `.gitignore` — add `ui.db` and `ui.db-journal`.
- `.env.example` — add `WATCH_DIR=` placeholder.
- `CLAUDE.md` — append a Round 2 subsection documenting the watcher + inbox workflow.

## UI — Inbox tab

Reuse Round 1 visual vocabulary. Each proposal is a card with:

- Status pill: `transcribing` (amber), `analyzing` (amber), `ready` (green), `error` (red).
- Meeting stem + first 200 chars of the transcript (when ready).
- Target subdir dropdown: `<select>` populated from existing subdirs + a "New subdir…" inline text input option (shown when the user picks "Other").
- Tag chips: editable list rendered from proposed tags. Each chip has type indicator (👤 person / 🏷 topic / 📁 project) and an X to remove. A text input + type dropdown lets the user add new tags.
- **Apply** button — posts to `/inbox/{stem}/apply`.
- **Dismiss** button — posts to `/inbox/{stem}/dismiss`.
- When status is `transcribing` or `analyzing`, Apply/Dismiss are disabled and a small spinner shows; a "View progress →" link jumps to the Pipeline tab.

When the watcher is off, the tab shows a banner: "Watcher disabled. Set `WATCH_DIR` in `.env` and restart the server to enable."

## Meetings tab integration

Small, non-disruptive changes:

- Each meeting row in the tree renders its tags as tiny inline chips right of the badge (if any).
- Detail view adds a "Tags" section below the subtabs listing all tags with the ability to add/remove manually (POSTs to `/meetings/{subdir}/{stem}/tags`, which hits `store.set_meeting_tags`). This gives the user a retroactive tag path for existing meetings without running auto-categorize.
- A tag filter in the sidebar: clicking a chip filters the tree to only meetings with that tag. Implemented as a query string (`?tag=Darwin+Henao`) the GET handler reads.

## Critical files touched summary

**Create:**
- `app/store.py`, `app/watcher.py`, `app/ingest.py`, `app/categorize.py`
- `app/routes/inbox.py`
- `templates/inbox.html`, `templates/_inbox_card.html`
- `tests/test_store.py`, `tests/test_watcher.py`, `tests/test_ingest.py`, `tests/test_categorize.py`, `tests/test_routes_inbox.py`
- `tests/helpers/fake_anthropic.py` — stubbed Claude client for categorize tests (no network)

**Modify:**
- `app/fs.py` (add `include_inbox` param + `is_inbox` property on `Meeting`)
- `app/routes/meetings.py` (exclude inbox; tag chips in tree; `/meetings/{s}/{s}/tags` POST)
- `app/routes/speakers.py`, `app/routes/pipeline_routes.py` (add `inbox_count` to context)
- `templates/base.html` (fourth tab)
- `templates/_meeting_tree.html`, `templates/_meeting_detail.html` (tag chips)
- `server.py` (schema init + optional watcher startup)
- `static/app.css` (chip, spinner, inbox card styles)
- `requirements.txt`, `.gitignore`, `.env.example`, `CLAUDE.md`

## Reused existing code (do not duplicate)

- `app.pipeline.PipelineRunner` and `get_runner()` — the watcher/ingest does NOT spin its own subprocess; it reuses the single-run runner. If a run is already in progress, ingest enqueues the new file in `inbox_proposals` with `status='transcribing'` but the runner's `start()` will raise `AlreadyRunning` — ingest catches it and retries via the `on_complete` chain (append the new argv to a small queue in `app/ingest.py`; consumed one-at-a-time).
- `app.fs.list_known_names()` — fed to the categorize prompt so Claude can reason about who's mentioned.
- `app.fs.list_meetings()` — the existing subdir set comes from `{m.subdir for m in list_meetings()}` minus `_inbox`.
- `extract.py`'s Anthropic client setup pattern (`anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))`) — mirror in `app/categorize.py`, don't import from `extract.py` (avoids coupling).

## Verification

End-to-end manual flow after implementation:

1. Set `WATCH_DIR=/path/to/scratch` in `.env`. Create the scratch dir with one small `.mov`.
2. `python server.py` → visit `http://localhost:8000/inbox`. The card shows status `transcribing`, then `analyzing`, then `ready` with an LLM proposal.
3. Edit the subdir and tags if desired. Click Apply. File moves to `data/<subdir>/<stem>.mov`; tags persist. Page redirects to the Meetings detail for that meeting, which now shows the chips.
4. Drop a second `.mov` into `WATCH_DIR`. Confirm only one pipeline runs at a time (second file's card shows `transcribing` only after the first run completes).
5. Toggle the watcher off via `POST /watcher/stop`. Drop a third file — confirm it is NOT ingested. Toggle on — confirm it is.
6. Manually click a tag chip in the Meetings tree. Confirm the tree filters to matching meetings.

Automated checks:

- `pytest` — new tests must hit ≥20 new assertions (store, watcher stability heuristic, ingest with in-process fake pipeline, categorize with stub Anthropic client, inbox routes).
- Full suite must stay green (43 existing + new Round 2 tests).
- Static check: `python -c "import server; print(server.create_app())"` boots cleanly with and without `WATCH_DIR` set.

## Risks and mitigations

- **Watchdog on macOS + iCloud folders:** native `FSEventsObserver` can miss events for iCloud-shadowed files. Plan uses `PollingObserver` (1 s interval) to sidestep; CPU cost is negligible for a single-user tool.
- **Pipeline already running when a file arrives:** ingest appends to an in-memory queue in `app/ingest.py`; the pipeline runner's existing `on_complete` hook kicks the next queued item.
- **LLM proposes a new subdir that conflicts with an existing name:** categorize output post-processing normalizes whitespace/case before comparing to existing subdirs; exact match reuses, otherwise creates new.
- **Categorize cost:** each new meeting = one Claude call with the full knowledge.md + commitments.md (~2–5 KB). Negligible.

## Out-of-scope for Round 2 (tracked for later)

- Retro-categorize button on existing `data/<subdir>/` meetings — users can add tags manually today; auto-proposal on already-placed meetings is Round 3 once the primary flow is validated.
- Deletion / un-ingest / un-route from the Meetings tab. Current behavior: manual filesystem move reverses a route.
- Bulk tag operations ("apply 'multiturbo' to all these 8 meetings").
