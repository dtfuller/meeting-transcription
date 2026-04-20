import pytest
from fastapi.testclient import TestClient

from app import fs, store
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    return TestClient(create_app())


def test_speakers_lists_pending_clips(client):
    r = client.get("/speakers")
    assert r.status_code == 200
    assert "Unknown Speaker 1" in r.text
    assert "01m08s" in r.text
    assert "2026-04-16 17-01-16" in r.text


def test_speakers_includes_known_names_datalist(client):
    r = client.get("/speakers")
    assert "David Fuller" in r.text
    assert "Darwin Henao" in r.text
    assert "<datalist" in r.text


def test_speakers_count_in_nav(client):
    r = client.get("/speakers")
    assert '<span class="count">2</span>' in r.text


from app import clips


def test_post_label_moves_clip_and_increments_counter(client, tmp_path, monkeypatch):
    clips.reset_counter()
    r = client.post(
        "/speakers/label",
        data={
            "filename": "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
            "name": "Alejandra Gomez",
        },
    )
    assert r.status_code == 200
    # Response is the updated queue fragment
    assert "Unknown Speaker 1" not in r.text  # it was the first clip; now gone
    assert "Unknown Speaker 2" in r.text
    assert "Reclassify" in r.text  # toast visible
    # Physically moved
    assert (tmp_path / "known-names" / "to-use" /
            "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s.mov").exists()
    assert clips.labels_since_reset() == 1


import sys
import time
from pathlib import Path

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


def test_post_reclassify_all_starts_runner(client, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.speakers.build_reclassify_all_argv",
        lambda: [sys.executable, str(HELPER)],
    )
    r = client.post("/speakers/reclassify", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)


def test_reclassify_resets_labels_counter_on_success(client, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    clips.reset_counter()
    # Pretend the user labeled a couple of clips
    clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    clips.label_clip(
        "Unknown Speaker 2 - 2026-04-16 17-01-16 - 03m22s.mov",
        "Maria Lopez",
    )
    assert clips.labels_since_reset() == 2

    # Fake pipeline run whose argv includes --reclassify
    monkeypatch.setattr(
        "app.routes.speakers.build_reclassify_all_argv",
        lambda: [sys.executable, str(HELPER), "--reclassify"],
    )
    r = client.post("/speakers/reclassify", follow_redirects=False)
    assert r.status_code == 303

    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)
    assert pipeline.get_runner().last_return_code == 0
    assert clips.labels_since_reset() == 0


def test_post_discard_removes_clip_and_persists_blocklist(client, tmp_path):
    from app import store
    # Precondition: clip exists on disk and in the queue.
    clip_path = tmp_path / "known-names" / "to-classify" / \
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov"
    assert clip_path.exists()

    r = client.post(
        "/speakers/discard",
        data={
            "filename": "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
            "source_stem": "2026-04-16 17-01-16",
            "timestamp_text": "01m08s",
        },
    )
    assert r.status_code == 200
    # File removed from disk
    assert not clip_path.exists()
    # Blocklist row inserted
    assert ("2026-04-16 17-01-16", "01m08s") in store.list_dismissed_clip_keys()
    # The queue fragment no longer lists the discarded clip
    assert "01m08s" not in r.text


def test_discarded_clip_stays_hidden_even_if_file_reappears(client, tmp_path):
    from app import fs, store
    # First discard the clip
    filename = "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov"
    client.post(
        "/speakers/discard",
        data={
            "filename": filename,
            "source_stem": "2026-04-16 17-01-16",
            "timestamp_text": "01m08s",
        },
    )
    # Simulate --reclassify regenerating the same clip
    (tmp_path / "known-names" / "to-classify" / filename).write_bytes(b"\x00" * 16)
    # list_unknown_clips filters it out
    names = [c.filename for c in fs.list_unknown_clips()]
    assert filename not in names


def test_label_inline_returns_updated_stem_fragment(client, tmp_path):
    # Fixture has two clips for stem "2026-04-16 17-01-16"
    r = client.post(
        "/speakers/label-inline",
        data={
            "filename": "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
            "name": "Alejandra Gomez",
            "stem": "2026-04-16 17-01-16",
        },
    )
    assert r.status_code == 200
    # The other clip for this stem is still there
    assert "Unknown Speaker 2" in r.text
    # The one we labeled is gone
    assert "Unknown Speaker 1" not in r.text
    # Fragment is wrapped in the expected outerHTML target container
    assert 'class="unknown-speakers-inline"' in r.text
    # File was moved
    assert (tmp_path / "known-names" / "to-use" /
            "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s.mov").exists()
