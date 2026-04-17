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
