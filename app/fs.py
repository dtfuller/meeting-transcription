from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
TRANSCRIPTS_DIR = ROOT / "transcripts"
INFORMATION_DIR = ROOT / "information"
KNOWN_NAMES_TO_USE = ROOT / "known-names" / "to-use"
KNOWN_NAMES_TO_CLASSIFY = ROOT / "known-names" / "to-classify"

_CLIP_TS_RE = re.compile(r"(\d+m\d+s)\.mov$")
_MONTH_RE = re.compile(r"^(\d{4}-\d{2})")


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


@dataclass(frozen=True)
class Folder:
    path: str   # ""=root, "Clients", "Clients/Acme"
    name: str   # leaf name ("Acme"); "" for root
    parent: str # parent path ("" for top-level folders)


@dataclass
class TreeNode:
    path: str
    name: str
    subfolders: list["TreeNode"]
    meetings: list[Meeting]


def list_folders() -> list[Folder]:
    """Every directory under DATA_DIR that is not _inbox or inside _inbox."""
    if not DATA_DIR.exists():
        return []
    folders: list[Folder] = []
    for p in sorted(DATA_DIR.rglob("*")):
        if not p.is_dir():
            continue
        rel = p.relative_to(DATA_DIR)
        if rel.parts and rel.parts[0] == "_inbox":
            continue
        folders.append(Folder(
            path=str(rel),
            name=rel.name,
            parent=str(rel.parent) if rel.parent != Path(".") else "",
        ))
    return folders


def build_tree(include_inbox: bool = False) -> TreeNode:
    """Builds a nested TreeNode matching the on-disk hierarchy.

    The returned node represents root (path="", name=""). Every folder and
    meeting is placed under its parent path. _inbox is excluded unless
    include_inbox is True (currently unused by callers — inbox is its own tab).
    """
    root = TreeNode(path="", name="", subfolders=[], meetings=[])
    by_path: dict[str, TreeNode] = {"": root}

    for folder in list_folders():
        node = TreeNode(path=folder.path, name=folder.name,
                        subfolders=[], meetings=[])
        by_path[folder.path] = node
        by_path.get(folder.parent, root).subfolders.append(node)

    for m in list_meetings(include_inbox=include_inbox):
        node = by_path.get(m.subdir, root)
        node.meetings.append(m)

    return root


def folder_exists(path: str) -> bool:
    """Root ('') is always considered to exist."""
    if not path:
        return True
    return (DATA_DIR / path).is_dir()


def folder_is_empty(path: str) -> bool:
    """True when there are no subfolders (excluding _inbox) and no .mov files
    anywhere beneath `path`. A missing directory is considered empty."""
    root = (DATA_DIR / path) if path else DATA_DIR
    if not root.is_dir():
        return True
    for p in root.rglob("*"):
        rel = p.relative_to(DATA_DIR)
        if rel.parts and rel.parts[0] == "_inbox":
            continue
        if p.is_dir():
            return False
        if p.suffix == ".mov":
            return False
    return True


def _meeting_from_mov(mov: Path) -> Meeting:
    rel = mov.relative_to(DATA_DIR)
    subdir = str(rel.parent) if rel.parent != Path(".") else ""
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


def find_meeting_by_stem(stem: str) -> Meeting | None:
    for m in list_meetings(include_inbox=True):
        if m.stem == stem:
            return m
    return None


def move_meeting_artifacts(stem: str, src_subdir: str, dst_subdir: str) -> list[Path]:
    """Move a meeting's four known files from <root>/<src>/<stem>{suffix} to
    <root>/<dst>/<stem>{suffix}. The .mov is required; the other three are
    optional (a meeting mid-pipeline may not have them yet). If any move
    after the first raises, earlier moves are rolled back."""
    suffixes = [
        (DATA_DIR,        ".mov",            False),  # required
        (TRANSCRIPTS_DIR, ".txt",            True),
        (INFORMATION_DIR, "-knowledge.md",   True),
        (INFORMATION_DIR, "-commitments.md", True),
    ]
    plan: list[tuple[Path, Path, bool]] = []
    for root, suffix, optional in suffixes:
        src = root / src_subdir / f"{stem}{suffix}"
        dst = root / dst_subdir / f"{stem}{suffix}"
        plan.append((src, dst, optional))

    # Preflight: required source must exist; all destinations must be free.
    first_src, _, _ = plan[0]
    if not first_src.exists():
        raise FileNotFoundError(f"{first_src} missing (required)")
    for _, dst, _ in plan:
        if dst.exists():
            raise FileExistsError(f"{dst} already exists")

    moved: list[tuple[Path, Path]] = []
    try:
        for src, dst, optional in plan:
            if not src.exists() and optional:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
        return [dst for _, dst in moved]
    except Exception:
        for src, dst in reversed(moved):
            try:
                shutil.move(str(dst), str(src))
            except Exception:
                _log.exception("rollback failed for %s -> %s", dst, src)
        raise


def move_folder_tree(src_path: str, dst_path: str) -> list[str]:
    """Move an entire folder (with all descendants) across the three parallel
    trees. Returns the list of meeting stems now under the new location so
    callers can reindex. Raises FileExistsError on collisions; ValueError for
    empty src; FileNotFoundError if the source doesn't exist on disk."""
    if not src_path:
        raise ValueError("Cannot move root")

    roots = [DATA_DIR, TRANSCRIPTS_DIR, INFORMATION_DIR]
    sources = [r / src_path for r in roots]
    destinations = [r / dst_path for r in roots]

    if not sources[0].is_dir():
        raise FileNotFoundError(f"{sources[0]} is not a directory")
    for dst in destinations:
        if dst.exists():
            raise FileExistsError(f"{dst} already exists")

    moved: list[tuple[Path, Path]] = []
    try:
        for src, dst in zip(sources, destinations):
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
        new_root = DATA_DIR / dst_path
        return sorted(p.stem for p in new_root.rglob("*.mov"))
    except Exception:
        for src, dst in reversed(moved):
            try:
                shutil.move(str(dst), str(src))
            except Exception:
                _log.exception("rollback failed for %s -> %s", dst, src)
        raise


def assert_stem_uniqueness_or_warn() -> None:
    """Emit a WARNING log line for every stem that appears more than once
    across data/ (including _inbox). Never raises — duplicates are legal on
    disk, they just break move/rename preflight checks."""
    by_stem: dict[str, list[str]] = {}
    for m in list_meetings(include_inbox=True):
        by_stem.setdefault(m.stem, []).append(m.subdir or "(root)")
    for stem, locations in by_stem.items():
        if len(locations) > 1:
            _log.warning("duplicate stem %r found at %s", stem, locations)


def load_transcript(m: Meeting) -> str:
    return m.transcript_path.read_text(encoding="utf-8") if m.has_transcript else ""


def load_knowledge(m: Meeting) -> str:
    return m.knowledge_path.read_text(encoding="utf-8") if m.has_knowledge else ""


def load_commitments(m: Meeting) -> str:
    return m.commitments_path.read_text(encoding="utf-8") if m.has_commitments else ""


def parse_clip_filename(filename: str) -> Clip | None:
    """Parse a to-classify clip filename into a Clip. Returns None if the
    name doesn't match the '<raw_label> - <source_stem> - MMmSSs.mov' shape."""
    m = _CLIP_TS_RE.search(filename)
    if not m:
        return None
    timestamp_text = m.group(1)
    head = filename[: m.start()].rstrip(" -")
    parts = head.split(" - ", 1)
    if len(parts) != 2:
        return None
    raw_label, source_stem = parts[0], parts[1]
    return Clip(
        filename=filename,
        path=KNOWN_NAMES_TO_CLASSIFY / filename,
        raw_label=raw_label,
        source_stem=source_stem,
        timestamp_text=timestamp_text,
    )


def list_unknown_clips() -> list[Clip]:
    if not KNOWN_NAMES_TO_CLASSIFY.exists():
        return []
    # Lazy import to avoid a package-level cycle (fs is imported by store callers).
    from app import store
    dismissed = store.list_dismissed_clip_keys()
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
        if (source_stem, timestamp_text) in dismissed:
            continue
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


def group_meetings(meetings: list[Meeting], threshold: int = 10) -> list[dict]:
    """Group meetings by (subdir, YYYY-MM) when a subdir has >threshold entries.

    Returns a list of subdir blocks. Each block has ``subdir``, ``is_grouped``
    (True/False), and either ``flat`` (a list of Meeting) or ``months`` (a list
    of ``{"label", "meetings", "open"}`` dicts sorted newest-first; the
    most-recent month has ``open=True``).
    """
    by_subdir: dict[str, list[Meeting]] = {}
    for m in meetings:
        by_subdir.setdefault(m.subdir, []).append(m)

    blocks: list[dict] = []
    for subdir in sorted(by_subdir):
        items = by_subdir[subdir]
        if len(items) <= threshold:
            blocks.append({
                "subdir": subdir,
                "is_grouped": False,
                "flat": items,
                "months": None,
            })
            continue
        by_month: dict[str, list[Meeting]] = {}
        for m in items:
            match = _MONTH_RE.match(m.stem)
            label = match.group(1) if match else "other"
            by_month.setdefault(label, []).append(m)
        # Sort descending, with "other" always last regardless of character order.
        sorted_labels = sorted(
            by_month.keys(),
            key=lambda label: (label == "other", label),
            reverse=True,
        )
        # The descending sort above puts "other" first because (True, ...) > (False, ...).
        # Move it to the end if present.
        if "other" in sorted_labels:
            sorted_labels = [l for l in sorted_labels if l != "other"] + ["other"]
        months = [
            {
                "label": label,
                "meetings": by_month[label],
                "open": i == 0,
            }
            for i, label in enumerate(sorted_labels)
        ]
        blocks.append({
            "subdir": subdir,
            "is_grouped": True,
            "flat": None,
            "months": months,
        })
    return blocks
