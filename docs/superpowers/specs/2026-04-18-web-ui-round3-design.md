# Web UI — Round 3 design: config page, folder grouping, cross-meeting search

## Context

Rounds 1 and 2 shipped the browse / label / trigger / ingest / categorize loop. The user has been using the app and flagged three gaps that remain:

1. **Restart-to-change-WATCH_DIR is friction.** The watcher's only config knob is an env var read at server boot. Changing it means editing `.env` and restarting. In-app configuration is cleaner, and a native folder picker spares the user from typing OS paths.
2. **The Meetings tree gets long.** One subdir with 20+ dated meetings is a wall of rows. Grouping by month makes scanning a large archive tractable.
3. **No way to search across meetings.** Users who remember a phrase, a person mentioned in passing, or a commitment description can't find the originating meeting without opening each file.

Round 3 closes all three gaps on the existing FastAPI + HTMX + SQLite stack. Scope is deliberately narrow — transcript editing and a commitments dashboard are deferred to a later round.

## Scope

### Feature A — Config page (`/config`) with native folder picker

- New `/config` page with a form for `WATCH_DIR`.
- Settings persist in `ui.json` at the repo root (gitignored). `ui.json` takes precedence over `.env` for the keys it defines; `.env` remains authoritative for API keys and anything read only at server boot.
- "Browse…" button next to the path input opens a **native macOS folder picker** via `tkinter.filedialog.askdirectory()`, spawned in a thread so it doesn't block the server loop. The selected absolute path fills the input. (Alternatives considered: `<input webkitdirectory>` — browser-native but can't return absolute paths; typed-only — zero ergonomics gain over editing `.env`. tkinter is native, real, and works on the single-user local Mac we're actually targeting.)
- On Save: write `ui.json`, then stop-and-restart the watcher with the new path. No server restart needed.
- The Config page is reachable from the header (small gear icon next to the title) rather than as a fifth top-level tab — settings are infrequent access.

### Feature B — Meetings-tree month grouping

- In `_meeting_tree.html`, subdirs with ≤10 meetings stay flat (current behavior unchanged). Subdirs with >10 meetings group rows into `<details>` sections by `YYYY-MM` derived from the first 7 chars of the stem.
- Most-recent month's `<details>` is open by default; others closed.
- Each group summary shows the month and the count: `📅 2026-04 (7)`.
- Grouping happens per subdir, so a single archive can have `multiturbo` flat and `check-in-and-pickup-wall` grouped if only one crosses the threshold.
- Tag filter (`?tag=X&tag_type=Y`) runs AFTER grouping — the filtered meeting list flows through the same grouping function, so grouped view respects filters.

### Feature C — Cross-meeting full-text search

- SQLite FTS5 virtual table `meetings_fts(stem, subdir, kind, body)` where `kind ∈ {'transcript','knowledge','commitments'}`. Tokenizer: `unicode61` (handles Spanish diacritics correctly).
- **Indexing:**
  - On server startup: if the FTS table is empty, populate from the current filesystem (read every transcript + knowledge + commitments file for every meeting).
  - After `/inbox/{stem}/apply`, `/meetings/{subdir}/{stem}/reextract`, `/meetings/{subdir}/{stem}/reclassify` and ingest's auto-categorize completion: upsert the four possible rows for that stem.
  - After a pipeline run with `--reclassify` (global): best-effort full reindex in a background thread.
- **Search UI:** a search box in the header (visible on every tab), submits to `GET /search?q=...`. New page renders a list of matches grouped by meeting, each with the top snippet (FTS5 `snippet()` with `<mark>` tags) and a link that lands on the right meeting + subtab (`?view=knowledge` etc., based on `kind`).
- **Search semantics:** FTS5 default MATCH operator — supports `"exact phrase"`, implicit `AND` between terms, `NOT`, `OR`. No need to build our own parser.

## Non-goals (explicitly deferred)

- Transcript editing — still Round 4+. Requires careful UX (concurrent edits, undo, formatting preservation) and has no urgent pain signal yet.
- Commitments dashboard — Round 4+. Useful but needs its own design pass on commitments.md format (which is currently freeform Spanish markdown).
- Live search as you type (HTMX `hx-trigger="keyup changed delay:250ms"`) — nice-to-have, skip for first ship; the form-submit version gets shipped first and we add live search only if it turns out to matter.
- Per-user settings. All state stays global per-install.

## Stack additions

- No new Python deps — `sqlite3` (stdlib) has FTS5 in its default build, and `tkinter` is stdlib on macOS Python.
- No new frontend deps. Search results page reuses existing CSS patterns (cards or list rows).

## Data model changes (in `app/store.py`)

Add to `init_schema`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS meetings_fts USING fts5(
  stem, subdir, kind, body,
  tokenize='unicode61 remove_diacritics 2'
);
-- rank by BM25 (fts5 default)
```

New `app/config_store.py` for `ui.json` persistence — kept separate from `app/store.py` because one is SQLite and the other is JSON; mixing them muddies the interface.

## New modules

- `app/config_store.py` — `load() -> dict`, `save(settings: dict) -> None`, `get(key, default=None)`. `CONFIG_PATH = <repo>/ui.json`. Schema is free-form dict for now; only key we use today is `watch_dir`.
- `app/folder_picker.py` — `pick_folder(initial: str | None = None) -> str | None`. Opens `tkinter.filedialog.askdirectory()` in a blocking call from a worker thread; returns the chosen path or `None` if cancelled. Gracefully degrades to `None` if tkinter is unavailable (e.g., headless CI).
- `app/search.py` — `reindex_all()`, `reindex_meeting(stem)`, `delete_meeting_from_index(stem)`, `search(query: str, limit: int = 50) -> list[SearchHit]`. Uses `app.store.connect()`.
- `app/routes/config_routes.py` — GET/POST `/config`, POST `/config/browse` (returns `{"path": "..."}` JSON).
- `app/routes/search_routes.py` — GET `/search`.
- `templates/config.html` — form page.
- `templates/search.html` + `templates/_search_hit.html` — results page + card partial.

## Modified modules

- `app/store.py` — extend `init_schema` with the FTS5 virtual table.
- `app/watcher.py` — expose a `reconfigure(new_watch_dir: Path)` helper so the config save can restart the observer cleanly.
- `app/ingest.py` — after `_run_categorize` promotes to `"ready"`, also call `search.reindex_meeting(stem)`. After `/inbox/{stem}/apply`, call `search.reindex_meeting(stem)` (the stem is unchanged by route-apply, only the subdir moves, so content stays indexed).
- `app/routes/meetings.py` — after `/reextract` and `/reclassify`, schedule `search.reindex_meeting(stem)` via a tiny post-completion hook wrapped around the pipeline's `on_complete`. Also: group meetings in the tree template context.
- `server.py` — read `WATCH_DIR` from `config_store` first, fall back to env. Call `search.reindex_all()` on startup if FTS is empty. Include new routers.
- `templates/base.html` — add a small `<form class="search">` with a single `<input name="q">` in the header (between the title and the tab nav), and a gear icon link to `/config`.
- `templates/_meeting_tree.html` — render groups when present; each `<details>` wraps the `<ul>` of that month.
- `static/app.css` — search bar, search hit rows, config form, gear icon, `<details>` month-group styling.

## Tasks

Bite-sized TDD pattern per Round 2's cadence. Target: 11 tasks + docs.

1. **`app/config_store.py`** — load/save/get with tmp-path-monkeypatched tests (4 tests).
2. **`app/folder_picker.py`** — `pick_folder` stub with a monkeypatched `tkinter.filedialog.askdirectory` in tests (2 tests). Real tkinter call only when not patched.
3. **`app/routes/config_routes.py`** — GET `/config` renders current settings; POST `/config` saves + calls `watcher.reconfigure(...)`. `POST /config/browse` returns `{"path": ...}`. Test suite mocks `folder_picker.pick_folder` (4 tests).
4. **Watcher hot-reload** — `app/watcher.py:reconfigure(path)` that stops the observer (if running), starts it pointed at the new path, and returns the new status (2 tests).
5. **`server.py` + `app/config_store.py` integration** — on startup, resolve `watch_dir` as `config_store.get("watch_dir") or os.getenv("WATCH_DIR")`. Touch `templates/base.html` to add the gear icon + the search box in one go (rendering of search box happens with no backend change yet; it just POSTs to `/search`). 2 tests (config precedence; gear icon present).
6. **`app/fs.py:group_meetings(meetings, threshold=10)`** — pure helper that takes the `meetings` list and returns either a flat list or `list[{"subdir": str, "months": [{"month": "YYYY-MM", "meetings": [...], "open": bool}, ...]}]` depending on subdir size. (4 tests: flat, grouped, open-flag on most-recent month, filter-preservation.)
7. **Meetings tree renders groups** — `app/routes/meetings.py` passes grouped structure to the template; `_meeting_tree.html` renders `<details>` sections when grouped. No test churn beyond a couple asserting the new markup appears for a seeded large subdir (2 tests).
8. **FTS5 schema + `app/search.py:reindex_all` / `reindex_meeting` / `delete_meeting_from_index`** — schema init, indexing from fs; 5 tests.
9. **`app/search.py:search(query)`** — run FTS5 MATCH + snippet; return structured hits (4 tests).
10. **Reindex hooks** — ingest `_run_categorize` success path + meetings.py `/reextract` and `/reclassify` on_complete callbacks call `reindex_meeting(stem)`. 2 tests with the fake pipeline.
11. **Search page** — `app/routes/search_routes.py` GET `/search?q=foo`; `templates/search.html` + `_search_hit.html`; wire the header search form. 3 tests.
12. **Docs** — append Round 3 section to `CLAUDE.md`; run full suite.

## Critical files (paths at a glance)

**New:**
- `app/config_store.py`, `app/folder_picker.py`, `app/search.py`
- `app/routes/config_routes.py`, `app/routes/search_routes.py`
- `templates/config.html`, `templates/search.html`, `templates/_search_hit.html`
- `tests/test_config_store.py`, `tests/test_folder_picker.py`, `tests/test_routes_config.py`, `tests/test_watcher_reconfigure.py`, `tests/test_group_meetings.py`, `tests/test_search.py`, `tests/test_routes_search.py`

**Modified:**
- `app/store.py` (FTS5 schema)
- `app/watcher.py` (reconfigure helper)
- `app/ingest.py` (reindex hook after categorize success)
- `app/fs.py` (add `group_meetings`)
- `app/routes/meetings.py` (tree grouping + post-pipeline reindex hook)
- `server.py` (config_store precedence + reindex-on-boot)
- `templates/base.html` (header search + gear icon)
- `templates/_meeting_tree.html` (render groups when present)
- `static/app.css` (search, config, details-group, gear)
- `.gitignore` (add `ui.json`)
- `CLAUDE.md` (Round 3 section)

## Reused existing code

- `app.pipeline.PipelineRunner` — reindex hooks for `/reextract` and `/reclassify` use the existing `start(..., on_complete=...)` signature from Round 2's final-review fix.
- `app.store.connect()` — shared SQLite connection pattern for the FTS table.
- `app.fs.list_meetings()`, `load_transcript/knowledge/commitments` — inputs to the reindex and grouping paths.
- `app.routes._context.nav_counts()` — still used everywhere; new routes compose the same way.

## Verification

Automated: `pytest -v` goes from 83 → ~110. No prior tests regress.

Manual, after `python server.py`:

1. Visit `/config`. Change `WATCH_DIR` via the form (typed). Save. Drop a `.mov` into the new path. Within seconds it lands in the Inbox tab — no server restart.
2. Same flow but click "Browse…". Native macOS folder dialog opens. Pick a folder. Path fills the input. Save. Drop a `.mov` into the picked folder. Same auto-ingest behavior.
3. Open the Meetings tab on a subdir with >10 meetings. Rows are grouped by month; the most-recent month is open; older months are collapsed. Subdirs with ≤10 stay flat.
4. Type a phrase from any transcript into the header search box. Submit. Land on `/search` with hits grouped by meeting. Click a hit — lands on the correct meeting with the correct subtab.
5. Trigger a `/reextract` on a specific meeting; wait for completion; search for a phrase that only appears in the new knowledge output. First-hit is that meeting, confirming the reindex hook fired.

## Risks and mitigations

- **tkinter on the server process:** only runs on macOS single-user deployment (our target). On headless CI, `pick_folder` returns `None` gracefully; the typed-path path still works.
- **FTS5 availability:** Python's stdlib `sqlite3` on macOS system builds includes FTS5. Verify at `init_schema()`; if missing, log a warning and skip search features rather than crash.
- **Reindex cost:** each file read + FTS5 insert is sub-millisecond. 100 meetings × 3 files = 300 inserts on startup — negligible.
- **Search concurrent with pipeline:** FTS5 reads don't block writes at this scale. SQLite's default connection-per-request keeps them isolated.

## Explicitly out of scope (for Round 4+)

- Transcript inline editor.
- Commitments dashboard / aggregate views.
- Live search-as-you-type.
- Per-user settings.
