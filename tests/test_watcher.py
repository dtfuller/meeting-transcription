import time
from pathlib import Path
from threading import Event

import pytest

from app import watcher


def _wait_for(pred, timeout=3.0):
    start = time.time()
    while time.time() - start < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_start_detects_new_mov(tmp_path):
    received: list[Path] = []
    event = Event()

    def on_new(p: Path):
        received.append(p)
        event.set()

    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        target = tmp_path / "meeting.mov"
        target.write_bytes(b"\x00" * 16)
        assert _wait_for(lambda: len(received) > 0, timeout=3.0)
        assert received[0].name == "meeting.mov"
    finally:
        w.stop()


def test_ignores_non_mov(tmp_path):
    received: list[Path] = []

    def on_new(p: Path):
        received.append(p)

    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        (tmp_path / "notes.txt").write_text("hi")
        time.sleep(0.6)
        assert received == []
    finally:
        w.stop()


def test_waits_until_file_is_stable(tmp_path):
    received: list[Path] = []

    def on_new(p: Path):
        received.append(p)

    w = watcher.Watcher(stability_seconds=0.4, poll_interval=0.1)
    w.start(tmp_path, on_new)
    try:
        target = tmp_path / "growing.mov"
        target.write_bytes(b"\x00" * 16)
        for _ in range(4):
            time.sleep(0.15)
            with target.open("ab") as f:
                f.write(b"\x01" * 16)
        assert _wait_for(lambda: len(received) > 0, timeout=3.0)
    finally:
        w.stop()


def test_status_reflects_running_state(tmp_path):
    w = watcher.Watcher(stability_seconds=0.1, poll_interval=0.1)
    assert not w.is_running()
    w.start(tmp_path, lambda p: None)
    try:
        assert w.is_running()
    finally:
        w.stop()
    assert not w.is_running()
