# Web UI — Round 1 design

## Context

Today the transcribe / extract / re-classify workflow is a CLI that writes to `data/`, `transcripts/`, `information/`, `known-names/`. Everything works, but the human-in-the-loop tasks live in Finder + VSCode + a terminal:

- Reading extracted `*-knowledge.md` / `*-commitments.md` means opening files one by one.
- Labeling a diarized-but-unidentified speaker means opening a `.mov` in QuickTime, typing a name, renaming the file, moving it from `known-names/to-classify/` to `known-names/to-use/`, remembering to re-run `process.py --reclassify`.
- Re-running the pipeline is `python process.py …` with no visible progress for the diarization stage.

A small local web UI collapses those three loops into one place. This spec is **Round 1 only** — a usable MVP.

### Phasing

- **Round 1 (this spec):** browse results, label unknown speakers, trigger + monitor the pipeline.
- **Round 2 (deferred):** directory watcher that auto-runs the pipeline on new recordings; auto-categorization (LLM routes a new meeting into the right `data/<subdir>/` and tags it with topics/people).
- **Round 3 (deferred):** transcript editing, cross-meeting search, commitments dashboard.

## Non-goals for Round 1

- Multi-user access, auth, deployment beyond `localhost`.
- Any automatic pipeline triggering — every run comes from an explicit click.
- Transcript or knowledge/commitments editing. Read-only.
- Auto-categorization, tagging, search.
- A database. All state is derivable from the filesystem.
- Concurrent pipeline runs. One run at a time; the Run button disables while a run is active.

## Stack

- **Backend:** FastAPI + `uvicorn`, running as `python server.py` (binds `127.0.0.1:8000`).
- **Templates:** Jinja2.
- **Frontend:** HTMX for partial swaps, native `<video>` for playback, Server-Sent Events for the live pipeline log. No JS build step, no `node_modules`.
- **Pipeline execution:** subprocess of the existing `process.py` — no duplication of orchestration logic.
- **Dependencies added to `requirements.txt`:** `fastapi`, `uvicorn`, `jinja2`, `python-multipart`. Nothing else.
- **CSS:** hand-written single file under `static/app.css`. Keep it small; match macOS default look (system fonts, `prefers-color-scheme`).

## Information architecture

Single page, top-level tabs — **Meetings**, **Speakers**, **Pipeline** — matching the mockups approved on 2026-04-17.

The **Speakers** tab label carries a warning-colored count of pending clips in `known-names/to-classify/`. The **Pipeline** tab carries a green "running" pill while a subprocess is active.

### Meetings tab

- Left pane: tree of `data/<subdir>/<stem>.mov` entries, grouped by subdir, sorted by date (stem is a timestamp). Each row shows an Unknown-Speaker badge if the corresponding transcript still contains the literal `Unknown Speaker`.
- Right pane: meeting detail. Head row: filename + action buttons **Open video** / **Re-extract** / **Reclassify**. Below: subtabs **Transcript** / **Knowledge** / **Commitments**, each just renders the corresponding file's contents.
  - Transcript: pre-formatted blocks `[HH:MM:SS Speaker] text`. Unknown Speaker lines highlighted (amber).
  - Knowledge / Commitments: render the markdown through a small server-side renderer (use `markdown` or `markdown-it-py` — whichever is lighter; add it to `requirements.txt`).
- **Open video** opens the original `.mov` in a modal player; the browser streams it from a backend range-supporting endpoint.
- **Re-extract** = POST that kicks off `python extract.py <transcript> --force`. Routes through the same pipeline runner as a full pipeline run (reuses the log/progress plumbing), but scoped to one file.
- **Reclassify** = POST that kicks off `python process.py <video.mov> --reclassify`. Same runner.

### Speakers tab

A vertical queue of cards. Each card corresponds to one `.mov` in `known-names/to-classify/` (filename format `Unknown Speaker N - <stem> - MMmSSs.mov`, already produced by `transcribe.extract_unknown_speaker_clips`).

Card contents:

- Inline `<video>` player showing the 20-second clip (controls, no autoplay).
- Source metadata parsed from the filename: raw speaker label, meeting stem, timestamp.
- Name `<input>` with datalist autocompletion from the existing stems in `known-names/to-use/` (prefix-before-` - ` per `extract_reference_embeddings`). Typing an existing name → clip becomes an additional reference clip for that person.
- **Save** button → POST `/speakers/label`.

**Save behavior:**

1. Rename and move the clip to `known-names/to-use/<Name> - <source-stem> - MMmSSs.mov` (keep the source context in the filename so it's clear where the clip came from). Overwrite-safe: if the exact destination filename exists, append ` (2)`, ` (3)`, etc.
2. Remove the card from the queue.
3. Increment an in-memory "labels since last reclassify" counter.
4. If the counter > 0, render a toast: "**Reclassify N meetings now →**" where **N** = count of transcripts under `transcripts/` that still contain the literal `Unknown Speaker` (recomputed each save; stable across saves — the set doesn't shrink just from adding labels, only from actually reclassifying).
5. Clicking the toast fires `POST /speakers/reclassify`, which runs `process.py --reclassify` (whole tree, no path args — every transcript with Unknown Speaker needs a retry because the new embedding could match a speaker in any meeting, not just the one the clip came from). The user lands on the Pipeline tab to watch progress. On successful run completion, the counter resets.

The user can therefore label several speakers in a row and kick off exactly one reclassify at the end. **Note:** the counter is process-local — a server restart forgets "you have pending labels" but the labeled clips are persisted to disk, so the next pipeline run still picks them up. Graceful degradation.

### Pipeline tab

Form:

- **Scope:** select — `All new recordings` (default), one per `data/<subdir>`, or `Specific meeting…` (which reveals a second select of `data/<subdir>/<meeting>.mov`).
- **Mode:** radio — `New only` (default) vs `Reclassify` (always enabled; picking Reclassify re-processes any selected video whose transcript still contains `Unknown Speaker`).
- **Run** button. Disabled when a run is already active.

Below the form:

- Status row (only when running): `● running`, current file, ETA (passthrough from `process.py` output).
- Live log: a scrolling, monospace, dark-themed block that tails the subprocess's stdout via SSE. Server buffers the last ~500 lines for late-joiners.

Starting a run:

1. Resolve form → argv list for `process.py`.
2. Refuse if a run is already active (409).
3. Spawn `subprocess.Popen(["python", "process.py", ...], stdout=PIPE, stderr=STDOUT, bufsize=1, text=True)`.
4. A background thread reads lines off stdout, pushes each to an asyncio queue fed to all SSE subscribers, and trims the buffer.
5. On exit, emit a terminal SSE event with the return code; UI re-enables Run and clears the "running" pill.

## Backend module layout

Keep each module small and single-purpose so they stay easy to hold in head:

- `server.py` — FastAPI app, route registration, mounts templates + static. Entry point (`python server.py`).
- `app/fs.py` — read-only filesystem helpers:
  - `list_meetings()` → list of `Meeting` records (subdir, stem, mov_path, transcript_path, knowledge_path, commitments_path, unknown_count).
  - `load_transcript(meeting)`, `load_knowledge(meeting)`, `load_commitments(meeting)`.
  - `list_unknown_clips()` → list of `Clip` records from `known-names/to-classify/`.
  - `list_known_names()` → deduped list of person stems from `known-names/to-use/` (for autocomplete). Reuse the grouping-by-prefix logic from `transcribe.extract_reference_embeddings`.
- `app/clips.py` — mutating operations on `known-names/`:
  - `label_clip(clip_filename, name) -> new_path` — rename + move; compute affected meeting stems.
- `app/pipeline.py` — the single global pipeline runner:
  - `is_running() -> bool`
  - `start(args: list[str])` — spawns `process.py` with those args; raises if already running.
  - `subscribe() -> AsyncIterator[str]` — yields SSE lines (history first, then live).
- `app/video.py` — range-supporting `.mov` streaming endpoint used by both the meeting detail player and the speakers clip player.
- `app/markdown.py` — thin wrapper around a markdown lib; safe-HTML only.
- `templates/` — `base.html` (tabs, status pills), `meetings.html`, `speakers.html`, `pipeline.html`, and partials for tree/detail/clip-card/log-line.
- `static/app.css` — one stylesheet.
- `static/htmx.min.js` — vendored, no CDN.

Critical files already in the repo that the UI consumes:

- `process.py` — exec'd as the pipeline runner. No changes needed.
- `transcribe.py`, `extract.py` — reused by `process.py`. No changes needed. (If we want autocomplete to match the exact prefix-grouping, we can import `transcribe.extract_reference_embeddings`'s grouping logic, or copy the ~5 lines — duplication is cheaper than importing a file that also pulls in pyannote/torch at import time. Copy.)

## HTTP routes

```
GET  /                                     → 302 /meetings
GET  /meetings                             → full page, tree + empty detail
GET  /meetings/{subdir}/{stem}             → full page, tree + detail (Transcript default)
GET  /partials/meeting/{subdir}/{stem}?view=transcript|knowledge|commitments
                                           → HTMX fragment for the right pane
POST /meetings/{subdir}/{stem}/reextract   → kicks extract --force via pipeline runner → 303 /pipeline
POST /meetings/{subdir}/{stem}/reclassify  → kicks process --reclassify on one meeting → 303 /pipeline
GET  /video/meeting/{subdir}/{stem}        → streams data/<subdir>/<stem>.mov (Range support)

GET  /speakers                             → full page, list of pending clips
GET  /video/clip/{filename}                → streams known-names/to-classify/<filename>
POST /speakers/label                       → form: filename, name → 200 HTMX partial: updated queue + toast
POST /speakers/reclassify                  → kicks process --reclassify on affected meetings → 303 /pipeline

GET  /pipeline                             → full page, form + status + log shell
POST /pipeline/run                         → form: scope, mode → 303 /pipeline
GET  /pipeline/stream                      → text/event-stream, buffered history + live tail
```

## Open questions / TBDs

- Markdown renderer choice: `markdown` (stdlib-ish, battle-tested) vs `markdown-it-py` (faster, more spec-compliant). Pick one at implementation time; either works.
- Port: default 8000. Add `--port` flag if it clashes with something else the user runs.
- `.mov` codecs: almost all macOS screen recordings are H.264/AAC → play natively in Safari, Chrome, Firefox. If a recording is HEVC (newer iPhones), Chrome may refuse; we can transcode on the fly via ffmpeg pipe if that becomes a problem. Not pre-solving.

## Verification

Round 1 is verified by using the app end-to-end:

1. `python server.py`, open `http://localhost:8000`.
2. **Meetings:** click around `data/multiturbo`, confirm transcript/knowledge/commitments render, video opens, badges reflect `Unknown Speaker` presence.
3. **Speakers:** with at least one pending clip in `known-names/to-classify/`, label it (existing name from autocomplete), confirm file moves to `known-names/to-use/` with the right name, queue updates, toast appears; label a second clip, toast count updates; click "Reclassify now", land on Pipeline tab, see live log.
4. **Pipeline:** new-only run on a scoped subdir; confirm log streams, status row updates, Run re-enables when done; confirm second click while running is rejected; confirm exit code surfaces in the final log line.
5. **Regression:** running `python process.py` from a terminal after using the UI still works identically (server doesn't hold file locks).

The existing CLI (`transcribe.py`, `extract.py`, `process.py`) continues to work unchanged — the UI is additive.
