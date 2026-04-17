from __future__ import annotations

import asyncio
import subprocess
import threading
from collections import deque
from typing import AsyncIterator, Callable


class AlreadyRunning(Exception):
    pass


class PipelineRunner:
    def __init__(self, history_max: int = 500):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._history: deque[str] = deque(maxlen=history_max)
        self._subscribers: list[asyncio.Queue[str]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last_return_code: int | None = None
        self._on_complete: Callable[[list[str], int], None] | None = None

    # --- public API -------------------------------------------------

    def set_on_complete(self, cb: Callable[[list[str], int], None]) -> None:
        """Invoked after the subprocess exits: cb(argv, returncode)."""
        self._on_complete = cb

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def history(self) -> list[str]:
        return list(self._history)

    def start(
        self,
        argv: list[str],
        cwd: str | None = None,
        on_complete: Callable[[list[str], int], None] | None = None,
    ) -> None:
        with self._lock:
            if self.is_running():
                raise AlreadyRunning()
            self._history.clear()
            self.last_return_code = None
            # Bind the callback atomically with the subprocess so a stale
            # caller's set_on_complete cannot overwrite an in-flight binding.
            if on_complete is not None:
                self._on_complete = on_complete
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=cwd,
            )
        threading.Thread(
            target=self._pump,
            args=(self._proc, list(argv)),
            daemon=True,
        ).start()

    def subscribe(self) -> AsyncIterator[str]:
        """Async generator yielding history (first) then live lines, then final 'EXIT N'."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        q: asyncio.Queue[str] = asyncio.Queue()
        for line in self._history:
            q.put_nowait(line)
        self._subscribers.append(q)

        async def _gen():
            try:
                while True:
                    item = await q.get()
                    yield item
                    if item.startswith("EXIT "):
                        return
            finally:
                if q in self._subscribers:
                    self._subscribers.remove(q)

        return _gen()

    def reset_for_tests(self) -> None:
        """Only for tests — block until current run is done, then clear state."""
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._history.clear()
        self._subscribers.clear()
        self.last_return_code = None

    # --- internals --------------------------------------------------

    def _fanout(self, line: str) -> None:
        self._history.append(line)
        if self._loop is None:
            return
        for q in list(self._subscribers):
            self._loop.call_soon_threadsafe(q.put_nowait, line)

    def _pump(self, proc: subprocess.Popen, argv: list[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            self._fanout(raw.rstrip("\n"))
        proc.wait()
        self.last_return_code = proc.returncode
        self._fanout(f"EXIT {proc.returncode}")
        # Consume the callback so stale bindings don't leak to the next run.
        with self._lock:
            cb = self._on_complete
            self._on_complete = None
        if cb is not None:
            try:
                cb(argv, proc.returncode)
            except Exception:
                pass


_runner: PipelineRunner | None = None


def get_runner() -> PipelineRunner:
    global _runner
    if _runner is None:
        _runner = PipelineRunner()
    return _runner
