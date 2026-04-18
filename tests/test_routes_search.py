import pytest
from fastapi.testclient import TestClient

from app import fs, search, store
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
    search.reindex_all()
    return TestClient(create_app())


def test_search_page_renders_without_query(client):
    r = client.get("/search")
    assert r.status_code == 200
    assert 'name="q"' in r.text
    # No results section shown when q is absent
    assert "No matches" not in r.text or r.text.count("No matches") == 0


def test_search_page_with_query_shows_hits(client):
    r = client.get("/search?q=David+Fuller")
    assert r.status_code == 200
    # Matching meeting stem should appear
    assert "2026-04-14 17-00-43" in r.text
    # Snippet with &lt;mark&gt; tag
    assert "&lt;mark&gt;" in r.text


def test_search_hit_links_to_meeting_with_correct_view(client):
    r = client.get("/search?q=David+Fuller")
    # Transcript hit should link to ?view=transcript
    assert "?view=transcript" in r.text


def test_search_page_shows_no_matches_message(client):
    r = client.get("/search?q=xyznothing123")
    assert r.status_code == 200
    assert "No matches" in r.text


def test_search_page_echoes_query_in_input(client):
    r = client.get("/search?q=David+Fuller")
    # The input field should be pre-populated with the submitted query
    assert 'value="David Fuller"' in r.text
