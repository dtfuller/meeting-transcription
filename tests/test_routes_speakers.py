import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
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
