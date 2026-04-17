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

    @property
    def is_inbox(self) -> bool:
        return self.subdir == "_inbox"


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


def list_meetings(include_inbox: bool = False) -> list[Meeting]:
    if not DATA_DIR.exists():
        return []
    meetings = (_meeting_from_mov(p) for p in DATA_DIR.rglob("*.mov"))
    if not include_inbox:
        meetings = (m for m in meetings if m.subdir != "_inbox")
    return sorted(meetings, key=lambda m: (m.subdir, m.stem))


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
