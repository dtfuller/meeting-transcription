from __future__ import annotations

import shutil
import sys
import threading
from collections import deque
from pathlib import Path

from app import categorize, fs, pipeline, store

ROOT = Path(__file__).parent.parent
PROCESS_PY = ROOT / "process.py"


def _default_argv_builder(inbox_path: Path) -> list[str]:
    # process.py receives a path relative to repo root
    data_root = fs.DATA_DIR.parent
    rel = inbox_path.relative_to(data_root)
    return [sys.executable, str(PROCESS_PY), str(rel)]


# Module-level indirection lets tests monkeypatch without breaking production
_PIPELINE_ARGV_BUILDER = _default_argv_builder


def _run_categorize(stem: str) -> None:
    """Overridable so tests can skip network. Default: run Claude."""
    m = fs.find_meeting(store.INBOX_SUBDIR, stem)
    if m is None:
        store.update_proposal_status(stem, "error", "meeting file disappeared")
        return
    try:
        existing_subdirs = sorted(
            {mm.subdir for mm in fs.list_meetings() if mm.subdir and mm.subdir != store.INBOX_SUBDIR}
        )
        result = categorize.propose(
            transcript=fs.load_transcript(m),
            knowledge=fs.load_knowledge(m),
            commitments=fs.load_commitments(m),
            existing_subdirs=existing_subdirs,
            known_names=fs.list_known_names(),
        )
        store.save_proposal(
            stem=stem,
            proposed_subdir=result.subdir,
            proposed_tags=result.tags,
            status="ready",
            error_message=None,
        )
    except Exception as e:
        store.update_proposal_status(stem, "error", f"categorize failed: {e}")


class IngestCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._queue: deque[tuple[Path, str]] = deque()
        self._in_flight_stem: str | None = None

    def reset_for_tests(self) -> None:
        with self._lock:
            self._queue.clear()
            self._in_flight_stem = None

    def on_new_file(self, external_path: Path) -> None:
        stem = external_path.stem
        inbox_dir = fs.DATA_DIR / store.INBOX_SUBDIR
        inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_path = inbox_dir / f"{stem}.mov"
        if inbox_path.exists():
            return  # already ingested
        shutil.copy2(external_path, inbox_path)
        store.save_proposal(
            stem=stem,
            proposed_subdir="",
            proposed_tags=[],
            status="transcribing",
            error_message=None,
        )
        with self._lock:
            self._queue.append((inbox_path, stem))
        self._maybe_start_next()

    def _maybe_start_next(self) -> None:
        with self._lock:
            if self._in_flight_stem is not None:
                return
            if not self._queue:
                return
            inbox_path, stem = self._queue.popleft()
            self._in_flight_stem = stem

        argv = _PIPELINE_ARGV_BUILDER(inbox_path)
        runner = pipeline.get_runner()
        runner.set_on_complete(self._on_pipeline_done)
        try:
            runner.start(argv, cwd=str(ROOT))
        except pipeline.AlreadyRunning:
            # Put back in queue, reset in-flight, and try again next time
            with self._lock:
                self._queue.appendleft((inbox_path, stem))
                self._in_flight_stem = None

    def _on_pipeline_done(self, argv: list[str], rc: int) -> None:
        stem = self._in_flight_stem
        if stem is not None:
            if rc != 0:
                store.update_proposal_status(stem, "error", f"pipeline exit {rc}")
            else:
                store.update_proposal_status(stem, "analyzing", None)
                try:
                    _run_categorize(stem)
                except Exception as e:
                    store.update_proposal_status(stem, "error", f"categorize failed: {e}")
                else:
                    # Ensure status advances to ready if _run_categorize didn't set it
                    p = store.get_proposal(stem)
                    if p is not None and p.status == "analyzing":
                        store.update_proposal_status(stem, "ready")
        with self._lock:
            self._in_flight_stem = None
        self._maybe_start_next()


_coordinator: IngestCoordinator | None = None


def get_coordinator() -> IngestCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = IngestCoordinator()
    return _coordinator
