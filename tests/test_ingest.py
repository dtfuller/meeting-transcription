import sys
import time
from pathlib import Path

import pytest

from app import fs, ingest, pipeline, store
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()
    monkeypatch.setattr(
        ingest,
        "_PIPELINE_ARGV_BUILDER",
        lambda inbox_path: [sys.executable, str(HELPER)],
    )
    monkeypatch.setattr(
        ingest,
        "_run_categorize",
        lambda stem: None,  # skip LLM during ingest tests
    )
    yield
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()


def _write_mov(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 32)


def test_on_new_file_copies_to_inbox_and_saves_pending_proposal(tmp_path):
    src = tmp_path / "external" / "new-meeting.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)

    inbox_path = fs.DATA_DIR / "_inbox" / "new-meeting.mov"
    assert inbox_path.exists()
    assert store.get_proposal("new-meeting") is not None


def test_pipeline_kicks_off_and_proposal_reaches_ready(tmp_path):
    src = tmp_path / "external" / "m.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    p = store.get_proposal("m")
    assert p is not None
    assert p.status == "ready"
    assert p.error_message is None


def test_skips_duplicate_file(tmp_path):
    src = tmp_path / "external" / "dup.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    # Second call should no-op since data/_inbox/dup.mov now exists
    ingest.get_coordinator().on_new_file(src)
    # Pipeline should NOT re-run
    assert not pipeline.get_runner().is_running()


def test_concurrent_ingest_queues_second_file(tmp_path, monkeypatch):
    # First pipeline is long; second should queue and run after
    monkeypatch.setattr(
        ingest,
        "_PIPELINE_ARGV_BUILDER",
        lambda inbox_path: [sys.executable, "-c", "import time; time.sleep(0.3)"],
    )
    a = tmp_path / "external" / "a.mov"
    b = tmp_path / "external" / "b.mov"
    _write_mov(a); _write_mov(b)

    ingest.get_coordinator().on_new_file(a)
    ingest.get_coordinator().on_new_file(b)

    # Wait for both to finish
    for _ in range(400):
        if (not pipeline.get_runner().is_running()
                and store.get_proposal("a")
                and store.get_proposal("b")
                and store.get_proposal("a").status == "ready"
                and store.get_proposal("b").status == "ready"):
            break
        time.sleep(0.05)

    assert store.get_proposal("a").status == "ready"
    assert store.get_proposal("b").status == "ready"
