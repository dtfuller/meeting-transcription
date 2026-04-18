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
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    return TestClient(create_app())


def test_meetings_page_renders(client):
    r = client.get("/meetings")
    assert r.status_code == 200
    assert "Meetings" in r.text


def test_speakers_page_renders(client):
    r = client.get("/speakers")
    assert r.status_code == 200
    assert "Speakers" in r.text


def test_pipeline_page_renders(client):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Pipeline" in r.text


def test_inbox_page_renders(client):
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "Inbox" in r.text


def test_inbox_count_appears_on_every_tab(client):
    # Seed a proposal so inbox_count > 0
    store.save_proposal(stem="x", proposed_subdir="",
                        proposed_tags=[], status="ready", error_message=None)
    for tab in ("/meetings", "/speakers", "/pipeline", "/inbox"):
        r = client.get(tab)
        assert r.status_code == 200, tab
        # The badge '<span class="count">1</span>' shows up in the nav for Inbox
        assert '<a href="/inbox"' in r.text
        assert '<span class="count">1</span>' in r.text
