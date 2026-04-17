import argparse
import json
import os
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import torch
from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI
from pyannote.audio import Inference, Model, Pipeline

DATA_DIR             = Path(__file__).parent / "data"
TRANSCRIPTS_DIR      = Path(__file__).parent / "transcripts"
KNOWN_NAMES_DIR      = Path(__file__).parent / "known-names" / "to-use"
TMP_DIR              = Path(__file__).parent / "tmp"

GROQ_MODEL           = "whisper-large-v3-turbo"
DIARIZATION_MODEL    = "pyannote/speaker-diarization-3.1"
EMBEDDING_MODEL      = "pyannote/embedding"
UNIFY_MODEL          = "gpt-5.4"

CHUNK_DURATION       = 720    # 12 min → ~22MB WAV, safely under Groq's 25MB limit
SIMILARITY_THRESHOLD = 0.70   # cosine similarity cutoff for known-speaker matching
CLASSIFY_DIR         = Path(__file__).parent / "known-names" / "to-classify"
CLIP_DURATION        = 20     # seconds — length of extracted unknown-speaker clips


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg"] + args, capture_output=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, "ffmpeg", stderr=result.stderr)


def get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def output_path_for(video: Path) -> Path:
    return TRANSCRIPTS_DIR / video.relative_to(DATA_DIR).with_suffix(".txt")


def wip_path_for(video: Path) -> Path:
    return output_path_for(video).with_suffix(".wip.json")


def load_wip(video: Path) -> dict:
    p = wip_path_for(video)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_wip(video: Path, data: dict) -> None:
    p = wip_path_for(video)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _spinner(label: str, stop_event: threading.Event, start: float) -> None:
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while not stop_event.is_set():
        elapsed = time.time() - start
        print(f"\r  {chars[i % len(chars)]} {label} ({elapsed:.0f}s)...", end="", flush=True)
        i += 1
        time.sleep(0.1)
    print()


def with_spinner(label: str, fn):
    stop = threading.Event()
    t0 = time.time()
    thread = threading.Thread(target=_spinner, args=(label, stop, t0), daemon=True)
    thread.start()
    try:
        result = fn()
    finally:
        stop.set()
        thread.join()
    return result, time.time() - t0


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def extract_full_audio(video: Path, dest: Path) -> Path:
    run_ffmpeg(["-y", "-i", str(video),
                "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                str(dest)])
    return dest


def extract_audio_chunk(video: Path, dest: Path, start: int, duration: int) -> Path:
    run_ffmpeg(["-y", "-i", str(video),
                "-ss", str(start), "-t", str(duration),
                "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                str(dest)])
    size_mb = dest.stat().st_size / (1024 * 1024)
    if size_mb >= 24:
        raise RuntimeError(
            f"Chunk WAV is {size_mb:.1f}MB (≥24MB). Lower CHUNK_DURATION in the script."
        )
    return dest


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_clients() -> tuple[Groq, OpenAI]:
    missing = [k for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "HUGGINGFACE_TOKEN")
               if not os.environ.get(k)]
    if missing:
        sys.exit(
            f"Error: missing env var(s): {', '.join(missing)}\n"
            "Add them to .env or export them in your shell."
        )
    return Groq(), OpenAI()


def load_diarization_pipeline(hf_token: str) -> Pipeline:
    try:
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=hf_token)
        if torch.backends.mps.is_available():
            print("  Using MPS (Apple Silicon GPU) for diarization")
            pipeline.to(torch.device("mps"))
        return pipeline
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg or "gated" in msg.lower():
            sys.exit(
                f"HuggingFace access denied for {DIARIZATION_MODEL}.\n"
                f"Accept the model terms at: https://hf.co/{DIARIZATION_MODEL}\n"
                f"Then retry."
            )
        raise


def load_embedding_model(hf_token: str) -> Inference:
    try:
        model = Model.from_pretrained(EMBEDDING_MODEL, token=hf_token)
        return Inference(model, window="whole")
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg or "gated" in msg.lower():
            sys.exit(
                f"HuggingFace access denied for {EMBEDDING_MODEL}.\n"
                f"Accept the model terms at: https://hf.co/{EMBEDDING_MODEL}\n"
                f"Then retry."
            )
        raise


# ---------------------------------------------------------------------------
# Speaker reference embeddings
# ---------------------------------------------------------------------------

def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def extract_reference_embeddings(embedding_model: Inference) -> dict[str, np.ndarray]:
    """
    Load speaker embeddings from known-names/to-use/.
    Files are grouped by the part of their stem before the first ' - ', so multiple clips
    per person are averaged into one robust voiceprint:
      David Fuller.mov              → "David Fuller"
      David Fuller - 2026-01-15.mov → "David Fuller" (averaged with above)
    """
    print("Loading speaker reference embeddings...")
    TMP_DIR.mkdir(exist_ok=True)

    # Group clips by person name (prefix before first ' - ')
    by_person: dict[str, list[Path]] = {}
    for mov in sorted(KNOWN_NAMES_DIR.glob("*.mov")):
        person = mov.stem.split(" - ")[0].strip()
        by_person.setdefault(person, []).append(mov)

    refs: dict[str, np.ndarray] = {}
    for person, clips in sorted(by_person.items()):
        embs = []
        for mov in clips:
            tmp_wav = TMP_DIR / f"_ref_{mov.stem}.wav"
            try:
                extract_full_audio(mov, tmp_wav)
                emb = embedding_model(str(tmp_wav))
                emb = _normalize(np.squeeze(np.array(emb)))
                embs.append(emb)
            except Exception as e:
                print(f"  Warning: could not load reference clip '{mov.stem}': {e}")
            finally:
                tmp_wav.unlink(missing_ok=True)
        if embs:
            refs[person] = _normalize(np.mean(embs, axis=0))
            label = person if len(clips) == 1 else f"{person} ({len(clips)} clips)"
            print(f"  Loaded: {label}")
    return refs


# ---------------------------------------------------------------------------
# Diarization
# ---------------------------------------------------------------------------

def diarize(audio_path: Path, pipeline: Pipeline) -> list[tuple[float, float, str]]:
    result = pipeline(str(audio_path))
    # pyannote >=3.3 returns DiarizeOutput(diarization=Annotation, ...); older returns Annotation directly
    annotation = (
        getattr(result, "speaker_diarization", None)
        or getattr(result, "diarization", None)
        or getattr(result, "annotation", None)
        or result
    )
    segments = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]
    return sorted(segments, key=lambda s: s[0])


def extract_speaker_cluster_embeddings(
    audio_path: Path,
    diarization_segments: list[tuple[float, float, str]],
    embedding_model: Inference,
) -> dict[str, np.ndarray]:
    """Extract one embedding per diarized speaker by cropping a representative segment to a tmp WAV."""
    by_speaker: dict[str, list[tuple[float, float]]] = {}
    for start, end, speaker in diarization_segments:
        by_speaker.setdefault(speaker, []).append((start, end))

    embeddings: dict[str, np.ndarray] = {}
    for speaker, segs in by_speaker.items():
        # Use the longest segment (≥2s preferred, fall back to whatever exists)
        candidates = sorted(segs, key=lambda s: s[1] - s[0], reverse=True)
        seg_start, seg_end = candidates[0]
        seg_dur = seg_end - seg_start
        if seg_dur < 0.5:
            continue

        tmp_wav = TMP_DIR / f"_spk_{speaker}.wav"
        try:
            run_ffmpeg([
                "-y", "-ss", str(seg_start), "-i", str(audio_path),
                "-t", str(seg_dur),
                "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                str(tmp_wav),
            ])
            emb = embedding_model(str(tmp_wav))
            emb = _normalize(np.squeeze(np.array(emb)))
            embeddings[speaker] = emb
        except Exception as e:
            print(f"    Warning: could not embed {speaker}: {e}")
        finally:
            tmp_wav.unlink(missing_ok=True)

    return embeddings


def identify_speakers(
    speaker_embeddings: dict[str, np.ndarray],
    reference_embeddings: dict[str, np.ndarray],
) -> dict[str, str]:
    speaker_map: dict[str, str] = {}
    unknown_count = 0
    for speaker, emb in speaker_embeddings.items():
        best_name, best_sim = None, -1.0
        for name, ref_emb in reference_embeddings.items():
            sim = float(np.dot(emb, ref_emb))
            if sim > best_sim:
                best_sim, best_name = sim, name
        print(f"    {speaker}: best match '{best_name}' sim={best_sim:.3f} (threshold={SIMILARITY_THRESHOLD})")
        if best_sim >= SIMILARITY_THRESHOLD:
            speaker_map[speaker] = best_name
        else:
            unknown_count += 1
            speaker_map[speaker] = f"Unknown Speaker {unknown_count}"
    return speaker_map


def extract_unknown_speaker_clips(
    video: Path,
    diarization_segments: list[tuple[float, float, str]],
    speaker_map: dict[str, str],
) -> None:
    """Extract a representative video clip for each unknown speaker to known-names/to-classify/."""
    CLASSIFY_DIR.mkdir(parents=True, exist_ok=True)

    by_speaker: dict[str, list[tuple[float, float]]] = {}
    for start, end, speaker in diarization_segments:
        by_speaker.setdefault(speaker, []).append((start, end))

    for raw_speaker, name in speaker_map.items():
        if "Unknown Speaker" not in name:
            continue
        segs = by_speaker.get(raw_speaker, [])
        if not segs:
            continue

        # Longest segment as the representative clip
        seg_start, seg_end = max(segs, key=lambda s: s[1] - s[0])
        clip_dur = min(CLIP_DURATION, seg_end - seg_start)

        ts = f"{int(seg_start) // 60:02d}m{int(seg_start) % 60:02d}s"
        out_path = CLASSIFY_DIR / f"{name} - {video.stem} - {ts}.mov"
        if out_path.exists():
            continue

        try:
            run_ffmpeg(["-y", "-ss", str(seg_start), "-i", str(video),
                        "-t", str(clip_dur), "-c", "copy", str(out_path)])
            print(f"  Clip saved → known-names/to-classify/{out_path.name}")
        except Exception as e:
            print(f"  Warning: could not extract clip for {name}: {e}")


# ---------------------------------------------------------------------------
# Transcription (Groq)
# ---------------------------------------------------------------------------

def transcribe_chunk(
    audio_path: Path,
    groq_client: Groq,
    offset: int,
) -> list[tuple[float, float, str]]:
    with open(audio_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            model=GROQ_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segs = result.segments
    if segs and isinstance(segs[0], dict):
        return [(s["start"] + offset, s["end"] + offset, s["text"]) for s in segs]
    return [(s.start + offset, s.end + offset, s.text) for s in segs]


def transcribe_video_audio(
    video: Path,
    groq_client: Groq,
    wip: dict,
    save_fn,
) -> list[tuple[float, float, str]]:
    duration = get_duration(video)
    chunk_starts = list(range(0, int(duration), CHUNK_DURATION))
    num_chunks = len(chunk_starts)
    cached = wip.setdefault("transcription", {})

    # Identify which chunks still need transcription
    todo = [(i, start) for i, start in enumerate(chunk_starts) if str(i) not in cached]
    n_cached = num_chunks - len(todo)
    if n_cached:
        print(f"  [{n_cached}/{num_chunks} chunk(s) loaded from WIP cache]")

    if todo:
        # Extract audio for chunks that need transcription
        chunk_files: list[tuple[int, Path, int]] = []
        for i, start in todo:
            chunk_dur = min(CHUNK_DURATION, int(duration) - start)
            chunk_wav = TMP_DIR / f"{video.stem}_chunk{i:02d}.wav"
            t0 = time.time()
            print(f"  [{i + 1}/{num_chunks}] Extracting audio "
                  f"({start // 60}–{(start + chunk_dur) // 60} min)...", end="", flush=True)
            extract_audio_chunk(video, chunk_wav, start, chunk_dur)
            print(f" done ({time.time() - t0:.1f}s)")
            chunk_files.append((i, chunk_wav, start))

        # Transcribe in parallel, saving each chunk to WIP as it completes
        print(f"  Transcribing {len(todo)} chunk(s) in parallel...")
        t_api = time.time()
        with ThreadPoolExecutor(max_workers=len(todo)) as executor:
            future_to_chunk = {
                executor.submit(transcribe_chunk, path, groq_client, offset): (i, path)
                for i, path, offset in chunk_files
            }
            done_count = 0
            for future in as_completed(future_to_chunk):
                i, path = future_to_chunk[future]
                segments = future.result()
                cached[str(i)] = [[s[0], s[1], s[2]] for s in segments]
                save_fn()  # persist after each chunk
                path.unlink(missing_ok=True)
                done_count += 1
                print(f"  Chunk {i + 1}/{num_chunks} transcribed "
                      f"({done_count}/{len(todo)} new complete)")
        print(f"  Transcription done ({time.time() - t_api:.1f}s)")

    # Reconstruct all segments from cache (cached + newly done)
    all_segments = []
    for segs in cached.values():
        all_segments.extend((s[0], s[1], s[2]) for s in segs)
    return sorted(all_segments, key=lambda s: s[0])


# ---------------------------------------------------------------------------
# Alignment + formatting
# ---------------------------------------------------------------------------

def align_transcript_to_speakers(
    transcription_segments: list[tuple[float, float, str]],
    diarization_segments: list[tuple[float, float, str]],
) -> list[tuple[float, str, str]]:
    aligned = []
    for t_start, t_end, text in transcription_segments:
        best_speaker, best_overlap = "Unknown Speaker", 0.0
        for d_start, d_end, speaker in diarization_segments:
            overlap = max(0.0, min(t_end, d_end) - max(t_start, d_start))
            if overlap > best_overlap:
                best_overlap, best_speaker = overlap, speaker
        aligned.append((t_start, best_speaker, text))
    return aligned


def format_transcript(aligned_segments: list[tuple[float, str, str]]) -> str:
    if not aligned_segments:
        return ""
    lines = []
    cur_start, cur_speaker, cur_text = aligned_segments[0]

    for start, speaker, text in aligned_segments[1:]:
        if speaker == cur_speaker:
            cur_text = cur_text.rstrip() + " " + text.strip()
        else:
            s = int(cur_start)
            ts = f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
            lines.append(f"[{ts} {cur_speaker}] {cur_text.strip()}")
            cur_start, cur_speaker, cur_text = start, speaker, text

    s = int(cur_start)
    ts = f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    lines.append(f"[{ts} {cur_speaker}] {cur_text.strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM unification pass
# ---------------------------------------------------------------------------

def unify_speakers(transcript: str, openai_client: OpenAI, known_names: list[str]) -> str:
    known = ", ".join(known_names) if known_names else "none"
    response = openai_client.chat.completions.create(
        model=UNIFY_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are editing a meeting transcript produced by chunked audio transcription. "
                    "Unknown speaker labels may be inconsistent across chunk boundaries — the same "
                    "person may appear as 'Unknown Speaker 1' in one section and 'Unknown Speaker 2' "
                    "in another.\n\n"
                    f"Known speakers (already correctly labeled, do not rename): {known}\n\n"
                    "Your task: unify unknown speaker labels so the same voice has the same label "
                    "throughout. Use contextual clues (speaking style, topics, who they respond to). "
                    "Preserve every timestamp and every word of spoken text exactly — only change "
                    "speaker labels. Return the full transcript and nothing else."
                ),
            },
            {"role": "user", "content": transcript},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Per-video orchestration
# ---------------------------------------------------------------------------

def needs_processing(video: Path, reclassify: bool, force: bool = False) -> bool:
    if force:
        return True
    out = output_path_for(video)
    if not out.exists() or out.stat().st_size == 0:
        return True
    if reclassify and "Unknown Speaker" in out.read_text(encoding="utf-8"):
        return True
    return False


def process_video(
    video: Path,
    groq_client: Groq,
    openai_client: OpenAI,
    diarization_pipeline: Pipeline,
    embedding_model: Inference,
    reference_embeddings: dict[str, np.ndarray],
    reclassify: bool = False,
    force: bool = False,
) -> bool:
    if not needs_processing(video, reclassify, force):
        print("  [skip] transcript already exists")
        return False

    out = output_path_for(video)
    out.parent.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(exist_ok=True)

    wip = load_wip(video)
    save_fn = lambda: save_wip(video, wip)

    full_wav = TMP_DIR / f"{video.stem}_full.wav"
    try:
        # 1. Extract full audio
        t0 = time.time()
        print("  Extracting full audio...", end="", flush=True)
        extract_full_audio(video, full_wav)
        total_duration = get_duration(full_wav)
        print(f" done ({time.time() - t0:.1f}s, {total_duration / 60:.1f} min)")

        # 2. Diarize + transcribe in parallel, using WIP cache where available
        has_diarization = "diarization" in wip
        t_parallel = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if not has_diarization:
                futures["diarize"] = executor.submit(diarize, full_wav, diarization_pipeline)
            else:
                print("  [cache] Diarization loaded from WIP")
            futures["transcribe"] = executor.submit(
                transcribe_video_audio, video, groq_client, wip, save_fn
            )
            raw_segments = (
                futures["diarize"].result() if "diarize" in futures
                else [tuple(s) for s in wip["diarization"]["segments"]]
            )
            transcription_segments = futures["transcribe"].result()
        print(f"  Parallel stage done ({time.time() - t_parallel:.1f}s)")

        # 3. Speaker identification (fast; skipped if cached)
        if has_diarization:
            speaker_map = wip["diarization"]["speaker_map"]
            print(f"  [cache] Speaker map loaded from WIP")
        else:
            speaker_embeddings = extract_speaker_cluster_embeddings(
                full_wav, raw_segments, embedding_model
            )
            speaker_map = identify_speakers(speaker_embeddings, reference_embeddings)
            wip["diarization"] = {
                "segments": [list(s) for s in raw_segments],
                "speaker_map": speaker_map,
            }
            save_fn()

        named_segments = [(s, e, speaker_map.get(sp, sp)) for s, e, sp in raw_segments]
        known = [n for n in speaker_map.values() if "Unknown" not in n]
        unknown = [n for n in speaker_map.values() if "Unknown" in n]
        print(f"  Identified: {', '.join(known) or 'none'} | Unknown: {len(unknown)}")
        if unknown:
            extract_unknown_speaker_clips(video, raw_segments, speaker_map)

        # 4. Align + format
        aligned = align_transcript_to_speakers(transcription_segments, named_segments)
        transcript = format_transcript(aligned)

        # 5. LLM unification if any unknown speakers
        if "Unknown Speaker" in transcript:
            known_names = list(reference_embeddings.keys())
            transcript, elapsed = with_spinner(
                "Unifying unknown speaker labels",
                lambda: unify_speakers(transcript, openai_client, known_names),
            )
            print(f"  Unification done ({elapsed:.1f}s)")

        out.write_text(transcript, encoding="utf-8")
        wip_path_for(video).unlink(missing_ok=True)  # WIP no longer needed
        print(f"  Saved → {out.relative_to(Path(__file__).parent)}")

    finally:
        full_wav.unlink(missing_ok=True)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="transcribe.py",
        description="Transcribe meeting videos in data/ with speaker labeling.",
        epilog=(
            "Examples:\n"
            "  python transcribe.py                         # process all new videos in data/\n"
            "  python transcribe.py data/Team               # only videos under data/Team/\n"
            "  python transcribe.py data/Team/mtg.mov       # only that one video\n"
            "  python transcribe.py --reclassify            # retry videos with Unknown Speakers\n"
            "  python transcribe.py data/Team --force       # reprocess data/Team/ end-to-end\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional .mov file(s) or sub-directory/-ies inside data/ to process. "
             "Defaults to the entire data/ tree.",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-process videos whose transcript still contains 'Unknown Speaker' "
             "(e.g. after adding new reference clips to known-names/to-use/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process selected videos even if a complete transcript already exists.",
    )
    return parser.parse_args()


def resolve_videos(paths: list[str]) -> list[Path]:
    if not paths:
        return sorted(DATA_DIR.rglob("*.mov"))

    collected: set[Path] = set()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.exists():
            sys.exit(f"Error: path does not exist: {raw}")
        if not p.is_relative_to(DATA_DIR):
            sys.exit(f"Error: path must be inside {DATA_DIR}: {raw}")
        if p.is_dir():
            collected.update(p.rglob("*.mov"))
        elif p.suffix.lower() == ".mov":
            collected.add(p)
        else:
            sys.exit(f"Error: not a .mov file or directory: {raw}")
    return sorted(collected)


def main() -> None:
    args = parse_args()
    reclassify = args.reclassify
    force = args.force

    # Validate paths up-front so typos don't cost a minute of model loading.
    videos = resolve_videos(args.paths)
    total = len(videos)
    if total == 0:
        print("No .mov files matched.")
        return
    pending_count = sum(1 for v in videos if needs_processing(v, reclassify, force))
    if pending_count == 0:
        print(f"All {total} selected transcript(s) already exist. Nothing to do.")
        return

    load_dotenv()
    groq_client, openai_client = load_clients()
    hf_token = os.environ["HUGGINGFACE_TOKEN"]

    # Clean up stale tmp WAVs from previous interrupted runs (> 1 hour old)
    if TMP_DIR.exists():
        cutoff = time.time() - 3600
        for f in TMP_DIR.glob("*.wav"):
            if f.stat().st_mtime < cutoff:
                f.unlink()

    print("Loading diarization pipeline (downloads ~1GB on first run)...")
    diarization_pipeline = load_diarization_pipeline(hf_token)
    print("Loading embedding model...")
    embedding_model = load_embedding_model(hf_token)
    reference_embeddings = extract_reference_embeddings(embedding_model)

    pending = [v for v in videos if needs_processing(v, reclassify, force)]
    already_done = total - len(pending)

    print(f"\nFound {total} video(s): {len(pending)} to process", end="")
    if already_done:
        print(f", {already_done} already done", end="")
    print("\n")

    completed_times: list[float] = []
    session_start = time.time()

    if reclassify:
        print("  [--reclassify] will re-process videos with Unknown Speakers\n")
    if force:
        print("  [--force] will re-process selected videos even if already transcribed\n")

    for i, video in enumerate(videos, 1):
        is_pending = needs_processing(video, reclassify, force)

        eta_str = ""
        if completed_times and is_pending:
            avg = sum(completed_times) / len(completed_times)
            remaining = sum(1 for v in videos[i - 1:] if needs_processing(v, reclassify, force))
            eta_str = f"  (ETA ~{fmt_duration(avg * remaining)})"

        print(f"[{i}/{total}] {video.parent.name}/{video.name}{eta_str}")

        t0 = time.time()
        try:
            did_work = process_video(
                video, groq_client, openai_client,
                diarization_pipeline, embedding_model, reference_embeddings,
                reclassify=reclassify,
                force=force,
            )
            if did_work:
                completed_times.append(time.time() - t0)
        except Exception as e:
            print(f"  [error] {e}")
            continue

    total_time = time.time() - session_start
    done = sum(1 for v in videos if output_path_for(v).exists() and output_path_for(v).stat().st_size > 0)
    print(f"\nFinished. {done}/{total} transcripts available. Total time: {fmt_duration(total_time)}")


if __name__ == "__main__":
    main()
