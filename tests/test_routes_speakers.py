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
