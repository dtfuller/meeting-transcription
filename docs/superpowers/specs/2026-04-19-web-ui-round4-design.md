# Web UI — Round 4 design: polish pack

## Context

Rounds 1–3 shipped the core product (browse / label / trigger / ingest / categorize / search + config + month grouping). Round 4 is a grab-bag of smaller quality-of-life improvements that don't need architectural thinking. Bigger items (workspaces, parallel jobs, transcript editor, commitments dashboard, configurable prompts) are parked as one-line backlog entries in CLAUDE.md and will each get their own spec when their round comes.

## Scope — five items

### 1. Config / inbox prefill consistency

- Extract `watch_dir() -> str | None` into `app/config_store.py` — returns `config_store.get("watch_dir") or os.getenv("WATCH_DIR") or None`. Single source of truth.
- `server.resolve_watch_dir()` becomes a thin alias.
- `app/routes/inbox.py:inbox_index` — compute `watcher_enabled = bool(config_store.watch_dir())` instead of only checking the env var.
- `app/routes/config_routes.py:config_index` — prefill the form with `config_store.watch_dir() or ""`. That way a user whose watch dir is only in `.env` still sees it in the `/config` form.

### 2. Process existing files on watcher startup

In `server.py`'s `_start_watcher` hook, **after** starting the observer, scan `watch_dir` for `*.mov` files and send any that aren't already ingested to `ingest.on_new_file(...)`.

- "Already ingested" = the stem appears in `fs.list_meetings(include_inbox=True)`. If yes: skip. If no: call `on_new_file`. IngestCoordinator's internal dedup + single-run-at-a-time queue handle the rest — the whole backlog drains in order.
- Run the scan in a short daemon thread so server startup stays instant.

### 3. UI color switch

- Header button next to the gear icon: sun/moon glyph (`☀` / `☾`).
- Clicking toggles between three states: `auto` (default, respect `prefers-color-scheme`), `light`, `dark`. Persist the choice in `localStorage` under `transcribe.theme`.
- CSS change: add `[data-theme="dark"] :root { ... }` and `[data-theme="light"] :root { ... }` selectors mirroring the existing `@media (prefers-color-scheme: dark)` block. JS sets `document.documentElement.dataset.theme` on load.
- Zero server changes — pure client-side.

### 4. Live search-as-you-type

- HTMX-ify the header search box:
  - `hx-get="/search/partial"`, `hx-trigger="keyup changed delay:250ms, search"`, `hx-target="#search-results-dropdown"`, `hx-swap="innerHTML"`.
  - Add `<div id="search-results-dropdown" class="search-dropdown"></div>` below the search form in `templates/base.html` — absolutely-positioned, hidden when empty.
- New route `GET /search/partial?q=...` returns a small HTML fragment of the top 8 hits (re-uses `_search_hit.html`). Empty query returns empty string.
- The existing `GET /search` full page stays (for "Enter" submit with full results). The dropdown just gives you the first 8 without leaving the current page; clicking a hit navigates normally.
- Click outside the dropdown to close — simple `window.addEventListener('click', ...)` toggle.

### 5. Retroactive categorize on existing meetings

- New button on the meeting detail next to the existing action buttons: **🏷 Suggest tags**.
- POST `/meetings/{subdir}/{stem}/suggest-tags` — runs `categorize.propose(...)` on the meeting's transcript+knowledge+commitments, returns `{"tags": [{"name", "type"}, ...]}` as JSON.
- The client-side JS on meeting detail fetches this, then pre-fills the existing "Edit tags" disclosure form with the proposed tags (appended to current tags, never replacing). The user reviews, edits if desired, and clicks the existing Save tags button.
- No data mutation happens until the user hits Save — the suggest endpoint is idempotent.
- Edge: `categorize.propose` requires the meeting to have a transcript + knowledge + commitments. If any are missing, return 400 with a friendly message.

## Tasks

Ten bite-sized tasks; per-task commits.

1. **`app/config_store.py:watch_dir()`** — 3 tests (env-only, config-only, both-set).
2. **Inbox + config routes switch to `config_store.watch_dir()`** — update `inbox.py` and `config_routes.py`; adjust 2 existing tests + 1 new.
3. **Watcher startup scan** — new helper `app/ingest.py:scan_existing(watch_dir)` + hook in `server._start_watcher`. 2 tests using a fake pipeline + fixture dir with 3 pre-existing .mov files.
4. **Color switch CSS** — add `[data-theme="light"]` and `[data-theme="dark"]` blocks mirroring `prefers-color-scheme`. No test.
5. **Color switch UI + JS** — header button toggles theme, persists to `localStorage`. Small Playwright-style assertion added to `tests/test_routes_shell.py` (just confirm the button element renders).
6. **`GET /search/partial`** — new route, `app/routes/search_routes.py`. Returns fragment. 2 tests.
7. **Header HTMX search wiring** — `templates/base.html` + dropdown CSS + outside-click-to-close JS. 1 test (fragment GET from the header works).
8. **POST `/meetings/.../suggest-tags`** — `app/routes/meetings.py` endpoint; returns JSON with proposed tags. 2 tests (happy path with fake Anthropic, 400 when content missing).
9. **Suggest-tags button + prefill JS** — `templates/_meeting_detail.html` button + inline JS that fetches and appends to the tag-edit-row inputs. 1 test for button presence.
10. **Backlog + docs** — append to `CLAUDE.md`: a one-line entry each for Workspaces, Parallel jobs, Transcript inline editor, Commitments dashboard, Configurable system prompts. Final suite run.

## Files touched

**New:** none major — a couple of small test files.

**Modified:**

- `app/config_store.py` — add `watch_dir()` helper
- `app/routes/inbox.py` — use the helper
- `app/routes/config_routes.py` — use the helper for prefill
- `app/routes/meetings.py` — add `/suggest-tags`
- `app/routes/search_routes.py` — add `/search/partial`
- `app/ingest.py` — add `scan_existing` helper
- `server.py` — wire the startup scan + delegate `resolve_watch_dir` to `config_store.watch_dir()`
- `templates/base.html` — color toggle button, HTMX search attrs, dropdown div, small JS
- `templates/_meeting_detail.html` — Suggest tags button + fetch JS
- `static/app.css` — theme blocks, search dropdown styles, toggle button styles
- `CLAUDE.md` — Round 4 section + backlog entries

## Backlog (append-only to CLAUDE.md)

- **Workspaces** — multiple independent `data/` trees (e.g. separate work vs personal), workspace switcher in nav, workspace-scoped `ui.db` and `ui.json`. Major refactor; needs its own spec.
- **Parallel jobs** — multiple concurrent pipeline runs with per-job SSE channels. Requires `PipelineRunner` to become a pool. Needs its own spec.
- **Transcript inline editor** — edit speaker labels and text on the Transcript subtab; save back to `transcripts/<subdir>/<stem>.txt`.
- **Commitments dashboard** — aggregate commitments across all meetings by owner / due date / status; needs a small parser over the current freeform Spanish markdown.
- **Configurable system prompts** — UI to edit the `extract.py` and `categorize.py` prompts. Persist in `ui.json`. Interacts with workspaces if those land first.

## Verification

- `pytest -v` goes from 130 → roughly 142 (≈12 new assertions across the 10 tasks).
- Manual, after `python server.py`:
  1. `/config` prefilled from `.env` if `ui.json` absent; banner on `/inbox` reflects both sources.
  2. Drop a few `.mov` into `WATCH_DIR` while the server is stopped, then start the server — they appear in the Inbox one by one.
  3. Click the sun/moon button in the header — theme toggles; reload preserves it.
  4. Type in the header search — dropdown shows top 8 hits as you type; click one; land on the meeting + right subtab.
  5. On any meeting with knowledge+commitments: click **🏷 Suggest tags**; proposed tags populate the Edit-tags form; Save persists.
