# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Two-stage pipeline for processing meeting recordings (`.mov` files):

1. `transcribe.py` — turns videos in `data/` into speaker-labeled transcripts in `transcripts/`.
2. `extract.py` — feeds each transcript to Claude to produce two markdown files in `information/`: `*-knowledge.md` (context, decisions, learnings) and `*-commitments.md` (owner / task / date). Prompt is in Spanish and assumes a Rappi product-management context.

Run them in order; `extract.py` only processes transcripts already written by `transcribe.py`.

## Commands

```bash
pip install -r requirements.txt                          # first-time setup (pyenv: Python 3.11.6)
python transcribe.py --help                              # full CLI reference
python transcribe.py                                     # process all new videos in data/
python transcribe.py data/<subdir>                       # scope to a sub-directory
python transcribe.py data/<subdir>/<file>.mov            # scope to a single video
python transcribe.py --reclassify                        # redo videos whose transcripts still contain "Unknown Speaker"
python transcribe.py data/<subdir>/<file>.mov --force    # reprocess end-to-end even if transcript exists
python extract.py --help                                 # full CLI reference
python extract.py                                        # generate knowledge/commitments for new transcripts
python extract.py transcripts/<subdir> --force           # re-extract a sub-directory, overwriting outputs
```

Both scripts accept zero-or-more positional paths (files or sub-dirs, absolute or relative to CWD) which must resolve inside `data/` and `transcripts/` respectively. No paths → walk the entire tree.

Required env vars (in `.env`): `GROQ_API_KEY`, `OPENAI_API_KEY`, `HUGGINGFACE_TOKEN`, `ANTHROPIC_API_KEY`. System deps: `ffmpeg` and `ffprobe` on PATH.

HuggingFace model terms must be accepted manually at hf.co for `pyannote/speaker-diarization-3.1` and `pyannote/embedding` — the script exits with the URL if they aren't.

## Architecture — `transcribe.py`

The pipeline per video runs five stages; **stages 2a and 2b run in parallel** via `ThreadPoolExecutor`:

1. Extract full mono 16kHz WAV to `tmp/` (ffmpeg).
2. In parallel:
   - **Diarize** the full WAV with pyannote (MPS-accelerated on Apple Silicon) → `(start, end, speaker)` segments.
   - **Transcribe** the video in `CHUNK_DURATION=720s` WAV chunks via Groq Whisper. Chunks are transcribed concurrently (one thread per chunk) and each chunk's result is saved to a WIP JSON before moving on.
3. Identify each diarized speaker by embedding their longest segment and comparing (cosine similarity, threshold 0.70) against reference voiceprints built from `known-names/to-use/*.mov`. Multiple clips per person (files sharing the prefix before ` - `) are averaged into one embedding.
4. Align transcription segments to diarization segments by max time-overlap, then collapse consecutive same-speaker lines into `[HH:MM:SS Speaker] text` blocks.
5. If any `Unknown Speaker N` labels remain, send the whole transcript to OpenAI (`UNIFY_MODEL`) to merge labels that refer to the same voice across chunk boundaries, preserving timestamps and text verbatim.

Unknown speakers also get a 20-second representative `.mov` clip dropped into `known-names/to-classify/` so a human can rename it and move it to `known-names/to-use/` for future runs.

### Resumability

Each video has a `transcripts/.../<name>.wip.json` alongside its eventual output. The WIP caches:
- `transcription[<chunk_index>]` — per-chunk Groq results, written as each chunk finishes
- `diarization.segments` and `diarization.speaker_map` — written after stage 3

Re-running picks up from the last saved chunk / skips diarization entirely if already cached. The WIP is deleted only after the final `.txt` is written. `tmp/*.wav` older than an hour is garbage-collected at startup.

A video is considered "done" (and skipped) if its transcript exists and is non-empty. `--reclassify` forces reprocessing for any transcript still containing the literal string `Unknown Speaker` — use this after adding new reference clips to `known-names/to-use/`.

## Architecture — `extract.py`

Streams each transcript to Claude (`claude-opus-4-6`) with adaptive thinking. The model returns a single response containing `<knowledge>...</knowledge>` and `<commitments>...</commitments>` blocks, which are split by regex and written to sibling files. Output paths mirror the transcript's subdirectory under `transcripts/` into `information/`. Already-processed transcripts (both outputs exist) are skipped.

## Directory conventions

- `data/<subdir>/*.mov` — input videos; `<subdir>` is preserved in output paths.
- `transcripts/<subdir>/<name>.txt` — final transcript; `.wip.json` sibling during processing.
- `known-names/to-use/<Person>[ - <suffix>].mov` — reference clips for speaker ID. The prefix before ` - ` is the displayed name; multiple clips per person are averaged.
- `known-names/to-classify/` — auto-generated clips of unidentified speakers awaiting human labeling.
- `information/<subdir>/<name>-knowledge.md` and `-commitments.md` — extraction outputs.
- `tmp/` — scratch WAVs; safe to delete when no run is active.

## Web UI (Round 1)

Local-only FastAPI + HTMX app.

```bash
python server.py  # starts on http://127.0.0.1:8000
pytest            # runs the UI test suite
```

Three tabs: **Meetings** (browse transcripts + knowledge + commitments, re-extract / reclassify per meeting), **Speakers** (queue of pending clips from `known-names/to-classify/` — label + batch-reclassify), **Pipeline** (scope + mode form, live log streaming via SSE, one run at a time).

The server is additive — the existing `transcribe.py`, `extract.py`, `process.py` CLIs keep working unchanged.

## Web UI (Round 2)

Round 2 adds:

- **Inbox tab** — new recordings arriving in `$WATCH_DIR` are auto-copied into `data/_inbox/`, run through `process.py`, then analyzed by Claude to propose a target subdir + tags. You approve in the Inbox tab; files move to `data/<subdir>/` and tags persist.
- **Tags** — stored in SQLite at `ui.db` (gitignored). Displayed as chips on meeting rows and the detail view. Click a tag chip to filter the Meetings tree. Edit tags manually via the "Edit tags" disclosure on any meeting detail.
- **Watcher** — `watchdog.PollingObserver` monitors `$WATCH_DIR` when set. Toggle with `POST /watcher/start|stop|status`. No-op if `WATCH_DIR` is unset.

Configuration (in `.env`):

```
WATCH_DIR=/Users/you/Movies/Meetings
```

Module layout added in Round 2:

- `app/store.py` — SQLite wrapper (tags + inbox proposals).
- `app/watcher.py` — polling file-system observer with stability heuristic.
- `app/ingest.py` — coordinator that copies new files to `data/_inbox/`, enqueues the pipeline run, and triggers auto-categorize.
- `app/categorize.py` — Claude-powered subdir + tag proposer.
- `app/routes/inbox.py` — Inbox tab, apply/dismiss, watcher toggle.
- `app/routes/_context.py` — shared `nav_counts()` helper used by every tab.

The Round 1 CLI scripts (`transcribe.py`, `extract.py`, `process.py`) remain unchanged.
