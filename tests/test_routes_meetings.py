from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def app_with_tree(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return TestClient(create_app())


def test_meetings_index_lists_tree(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert r.status_code == 200
    assert "multiturbo" in r.text
    assert "2026-04-14 17-00-43" in r.text
    assert "check-in" in r.text


def test_unknown_badge_shown_for_meetings_with_unknown_speakers(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert '2026-04-16 17-01-16' in r.text
    assert 'class="badge"' in r.text


def test_meeting_detail_renders_transcript(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert "David Fuller" in r.text
    assert "hola" in r.text


def test_meeting_detail_unknown_404(app_with_tree):
    r = app_with_tree.get("/meetings/does-not/exist")
    assert r.status_code == 404
