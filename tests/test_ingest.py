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


def test_scan_existing_sends_unknown_files_to_ingest(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    _write_mov(external / "new-a.mov")
    _write_mov(external / "new-b.mov")

    sent: list[Path] = []
    # Bypass the real pipeline kickoff; just capture the calls
    original = ingest.get_coordinator().on_new_file
    ingest.get_coordinator().on_new_file = lambda p: sent.append(p)
    try:
        n = ingest.scan_existing(external)
    finally:
        ingest.get_coordinator().on_new_file = original

    assert n == 2
    names = sorted(p.name for p in sent)
    assert names == ["new-a.mov", "new-b.mov"]


def test_scan_existing_skips_already_known_stems(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    _write_mov(external / "2026-04-14 17-00-43.mov")  # stem matches sample_assets
    _write_mov(external / "fresh.mov")

    sent: list[Path] = []
    original = ingest.get_coordinator().on_new_file
    ingest.get_coordinator().on_new_file = lambda p: sent.append(p)
    try:
        n = ingest.scan_existing(external)
    finally:
        ingest.get_coordinator().on_new_file = original

    # Only "fresh" should pass through; the 04-14 meeting is already in the
    # sample tree.
    assert n == 1
    assert sent[0].name == "fresh.mov"


def test_on_new_file_skips_blocklisted_stem(tmp_path):
    store.add_dismissed_inbox_stem("blocked")
    src = tmp_path / "external" / "blocked.mov"
    _write_mov(src)

    ingest.get_coordinator().on_new_file(src)

    # No copy and no proposal row should have been created.
    assert not (fs.DATA_DIR / "_inbox" / "blocked.mov").exists()
    assert store.get_proposal("blocked") is None


def test_enqueue_existing_skips_blocklisted_stem(tmp_path):
    store.add_dismissed_inbox_stem("blocked2")
    inbox_dir = fs.DATA_DIR / "_inbox"
    inbox_path = inbox_dir / "blocked2.mov"
    _write_mov(inbox_path)

    ingest.get_coordinator().enqueue_existing(inbox_path, "blocked2")

    coord = ingest.get_coordinator()
    assert coord._in_flight_stem is None
    assert not any(s == "blocked2" for _, s in coord._queue)


def test_reconcile_stuck_proposals_reenqueues_transcribing_rows(tmp_path):
    # Simulate: a proposal stuck in 'transcribing' whose file still lives in _inbox.
    inbox_dir = fs.DATA_DIR / "_inbox"
    stem = "orphan-meeting"
    _write_mov(inbox_dir / f"{stem}.mov")
    store.save_proposal(
        stem=stem,
        proposed_subdir="",
        proposed_tags=[],
        status="transcribing",
        error_message=None,
    )
    # Another stuck proposal whose file is GONE — should be skipped.
    store.save_proposal(
        stem="ghost",
        proposed_subdir="",
        proposed_tags=[],
        status="analyzing",
        error_message=None,
    )
    # A 'ready' proposal — should be ignored.
    _write_mov(inbox_dir / "done.mov")
    store.save_proposal(
        stem="done",
        proposed_subdir="",
        proposed_tags=[],
        status="ready",
        error_message=None,
    )

    n = ingest.reconcile_stuck_proposals()
    assert n == 1

    # The pipeline should have been kicked for the orphan; wait for completion.
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)
    # The in-flight stem is cleared once done.
    assert ingest.get_coordinator()._in_flight_stem is None
