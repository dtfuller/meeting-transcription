import asyncio
import sys
import time
from pathlib import Path

import pytest

from app import pipeline

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture(autouse=True)
def clean_runner():
    pipeline.get_runner().reset_for_tests()
    yield
    pipeline.get_runner().reset_for_tests()


def test_start_and_collect_lines():
    r = pipeline.get_runner()
    assert not r.is_running()
    r.start([sys.executable, str(HELPER)])
    for _ in range(200):
        if not r.is_running():
            break
        time.sleep(0.05)
    assert not r.is_running()
    lines = r.history()
    content = "\n".join(lines)
    assert "starting" in content
    assert "done" in content
    assert r.last_return_code == 0


def test_concurrent_start_raises():
    r = pipeline.get_runner()
    r.start([sys.executable, str(HELPER)])
    try:
        with pytest.raises(pipeline.AlreadyRunning):
            r.start([sys.executable, str(HELPER)])
    finally:
        for _ in range(200):
            if not r.is_running(): break
            time.sleep(0.05)


@pytest.mark.asyncio
async def test_subscribe_yields_live_lines():
    r = pipeline.get_runner()
    r.start([sys.executable, str(HELPER)])
    gen = r.subscribe()
    seen = []
    async for evt in gen:
        seen.append(evt)
        if evt.startswith("EXIT "):
            break
    content = "\n".join(seen)
    assert "starting" in content
    assert "done" in content
    assert "EXIT 0" in content
