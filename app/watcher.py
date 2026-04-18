from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver


class _Handler(FileSystemEventHandler):
    def __init__(self, on_event: Callable[[Path], None]):
        self._on_event = on_event

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() == ".mov":
            self._on_event(p)

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() == ".mov":
            self._on_event(p)


class Watcher:
    def __init__(self, stability_seconds: float = 3.0, poll_interval: float = 1.0):
        self._stability_seconds = stability_seconds
        self._poll_interval = poll_interval
        self._observer: PollingObserver | None = None
        self._watch_dir: Path | None = None
        # Maps path -> (last_seen_mtime, monotonic_time_mtime_was_last_updated)
        self._pending: dict[Path, tuple[float, float]] = {}
        self._fired: set[Path] = set()
        self._pending_lock = threading.Lock()
        self._timer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._callback: Callable[[Path], None] | None = None

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    def status(self) -> dict:
        return {
            "is_running": self.is_running(),
            "watch_dir": str(self._watch_dir) if self._watch_dir else None,
        }

    def start(self, watch_dir: Path, on_new_file: Callable[[Path], None]) -> None:
        if self.is_running():
            return
        watch_dir = Path(watch_dir).resolve()
        watch_dir.mkdir(parents=True, exist_ok=True)
        self._watch_dir = watch_dir
        self._callback = on_new_file
        self._pending.clear()
        self._fired.clear()
        self._stop_event.clear()

        handler = _Handler(self._schedule)
        self._observer = PollingObserver(timeout=self._poll_interval)
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()

        self._timer_thread = threading.Thread(target=self._stability_loop, daemon=True)
        self._timer_thread.start()

    def reconfigure(self, new_watch_dir: Path) -> None:
        """Stop (if running) and restart pointed at a new directory.

        No-op if not currently running. Preserves the callback registered
        by the prior start() call.
        """
        if not self.is_running():
            return
        callback = self._callback
        self.stop()
        if callback is not None:
            self.start(new_watch_dir, callback)

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
        self._observer = None
        self._watch_dir = None

    def _schedule(self, path: Path) -> None:
        with self._pending_lock:
            if path in self._fired:
                return
            if path not in self._pending:
                try:
                    mtime = path.stat().st_mtime
                except FileNotFoundError:
                    mtime = 0.0
                self._pending[path] = (mtime, time.monotonic())

    def _stability_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            now = time.monotonic()
            ready: list[Path] = []
            with self._pending_lock:
                for p, (last_mtime, stable_since) in list(self._pending.items()):
                    try:
                        mtime = p.stat().st_mtime
                    except FileNotFoundError:
                        del self._pending[p]
                        continue
                    if mtime != last_mtime:
                        # File still changing — reset the stable clock
                        self._pending[p] = (mtime, now)
                    elif now - stable_since >= self._stability_seconds:
                        ready.append(p)
                        del self._pending[p]
                        self._fired.add(p)
            for p in ready:
                try:
                    if self._callback is not None:
                        self._callback(p)
                except Exception:
                    pass
