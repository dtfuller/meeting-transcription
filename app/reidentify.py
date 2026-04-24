"""Lightweight speaker re-identification without re-processing videos.

This module backs the /speakers "Rematch queue" button and the inline
transcript-patching that happens when a user manually labels a clip. Unlike
the full transcribe.py pipeline, it never touches the original video —
it just embeds the 20-second clips already sitting in
``known-names/to-classify/`` and edits the finalized transcripts in place.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app import clips as clips_mod, fs, search

TMP_DIR = Path(__file__).parent.parent / "tmp"
SIMILARITY_THRESHOLD = 0.70  # same cutoff used in transcribe.py

_TIMESTAMP_RE = re.compile(r"\[(\d{2}):(\d{2}):(\d{2}) (Unknown Speaker \d+)\]")
_CLIP_TS_RE = re.compile(r"^(\d+)m(\d+)s$")


@dataclass
class RematchResult:
    matched: list[tuple[str, str]]   # [(clip_filename, matched_name), ...]
    unmatched: list[str]             # [clip_filename, ...]


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def _load_inference():
    # Lazy import: pyannote pulls in torch and hits HuggingFace.
    import os
    from pyannote.audio import Inference, Model

    token = os.getenv("HUGGINGFACE_TOKEN")
    model = Model.from_pretrained("pyannote/embedding", use_auth_token=token)
    return Inference(model, window="whole")


def _extract_wav(clip_path: Path, wav_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip_path),
         "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
         str(wav_path)],
        check=True, capture_output=True,
    )


def _compute_clip_embedding(clip_path: Path) -> np.ndarray:
    """Embed a clip file. Tests monkeypatch this to skip ffmpeg + pyannote."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_wav = TMP_DIR / f"_rematch_{clip_path.stem}.wav"
    try:
        _extract_wav(clip_path, tmp_wav)
        inference = _load_inference()
        emb = inference(str(tmp_wav))
        return _normalize(np.squeeze(np.array(emb)))
    finally:
        tmp_wav.unlink(missing_ok=True)


def _reference_embeddings() -> dict[str, np.ndarray]:
    """Build per-person averaged voiceprints from KNOWN_NAMES_TO_USE.

    Multiple clips sharing the same prefix before ' - ' are averaged into
    one robust reference, matching transcribe.extract_reference_embeddings.
    """
    if not fs.KNOWN_NAMES_TO_USE.exists():
        return {}
    by_person: dict[str, list[Path]] = {}
    for mov in sorted(fs.KNOWN_NAMES_TO_USE.glob("*.mov")):
        person = mov.stem.split(" - ")[0].strip()
        by_person.setdefault(person, []).append(mov)

    refs: dict[str, np.ndarray] = {}
    for person, movs in sorted(by_person.items()):
        embs = []
        for mov in movs:
            try:
                embs.append(_compute_clip_embedding(mov))
            except Exception:
                continue
        if embs:
            refs[person] = _normalize(np.mean(embs, axis=0))
    return refs


def _parse_clip_timestamp(ts_text: str) -> int | None:
    """'01m08s' → 68 seconds. Returns None on malformed input."""
    m = _CLIP_TS_RE.match(ts_text)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _hms_to_seconds(hh: str, mm: str, ss: str) -> int:
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def _labels_near_timestamp(text: str, ts_text: str,
                           window_s: int = 5) -> list[str]:
    """Distinct 'Unknown Speaker N' labels on transcript lines whose starting
    timestamp falls within ±window_s of the clip's recorded timestamp."""
    target = _parse_clip_timestamp(ts_text)
    if target is None:
        return []
    found: set[str] = set()
    for m in _TIMESTAMP_RE.finditer(text):
        line_s = _hms_to_seconds(m.group(1), m.group(2), m.group(3))
        if abs(line_s - target) <= window_s:
            found.add(m.group(4))
    return sorted(found)


def apply_label_to_transcript(source_stem: str, raw_label: str,
                              ts_text: str, new_name: str) -> bool:
    """Replace a clip's Unknown-Speaker label with the matched name in the
    source meeting's transcript. Returns True if the file was modified.

    Fast path: the clip's raw_label still appears literally in the transcript.
    Fallback: the unify pass renumbered labels; locate the actual label(s)
    near the clip's timestamp and replace those instead.
    """
    meeting = next(
        (m for m in fs.list_meetings(include_inbox=True) if m.stem == source_stem),
        None,
    )
    if meeting is None or not meeting.has_transcript:
        return False
    text = meeting.transcript_path.read_text(encoding="utf-8")

    # Needle includes the leading space and closing bracket so
    # "Unknown Speaker 1" doesn't swallow "Unknown Speaker 11".
    needle = f" {raw_label}]"
    if needle in text:
        new = text.replace(needle, f" {new_name}]")
    else:
        new = text
        for lbl in _labels_near_timestamp(text, ts_text):
            new = new.replace(f" {lbl}]", f" {new_name}]")

    if new == text:
        return False
    meeting.transcript_path.write_text(new, encoding="utf-8")
    try:
        search.reindex_meeting(source_stem)
    except Exception:
        pass
    return True


def rematch_unknown_clips() -> RematchResult:
    """Single-pass re-identification of the current /speakers queue.

    For each clip: embed it, cosine-match against current voiceprints.
    On a match, patch the source transcript and move the clip to
    known-names/to-use/ via clips.label_clip.
    """
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []

    queue = fs.list_unknown_clips()
    if not queue:
        return RematchResult(matched=matched, unmatched=unmatched)

    refs = _reference_embeddings()
    if not refs:
        return RematchResult(matched=matched,
                             unmatched=[c.filename for c in queue])

    for clip in queue:
        try:
            emb = _compute_clip_embedding(clip.path)
        except Exception:
            unmatched.append(clip.filename)
            continue

        best_name, best_sim = None, -1.0
        for name, ref in refs.items():
            sim = float(np.dot(emb, ref))
            if sim > best_sim:
                best_sim, best_name = sim, name

        if best_name is not None and best_sim >= SIMILARITY_THRESHOLD:
            apply_label_to_transcript(
                clip.source_stem, clip.raw_label, clip.timestamp_text, best_name,
            )
            try:
                clips_mod.label_clip(clip.filename, best_name)
            except (FileNotFoundError, ValueError):
                pass  # clip vanished between listing and labeling
            matched.append((clip.filename, best_name))
        else:
            unmatched.append(clip.filename)

    return RematchResult(matched=matched, unmatched=unmatched)
