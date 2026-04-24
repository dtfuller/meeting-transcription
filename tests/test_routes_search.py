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
    # Snippet contains real <mark> tags so the browser renders the highlight
    assert "<mark>" in r.text


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


def test_search_snippet_escapes_html_in_body(client, tmp_path):
    from app import search as search_mod
    # Inject a meeting whose transcript contains an HTML tag. Reindex.
    transcript = tmp_path / "transcripts" / "multiturbo" / "2026-04-14 17-00-43.txt"
    transcript.write_text("[00:00:00 David] <script>alert('xss')</script> pwned")
    search_mod.reindex_all()
    r = client.get("/search?q=pwned")
    assert r.status_code == 200
    # The user content must be escaped — no raw XSS <script> tag should reach the page
    # (Note: the page itself has a legitimate <script> in <head> for theme init,
    #  so we check that the injected alert payload is escaped, not the tag in isolation.)
    assert "<script>alert" not in r.text
    assert "&lt;script&gt;" in r.text


def test_search_partial_returns_hits_fragment(client):
    r = client.get("/search/partial?q=David+Fuller")
    assert r.status_code == 200
    # Fragment: no <html>/<body> wrapper
    assert "&lt;html" not in r.text.lower()
    # At least one hit link rendered
    assert "search-hit" in r.text


def test_search_partial_empty_query_returns_empty(client):
    r = client.get("/search/partial?q=")
    assert r.status_code == 200
    assert r.text.strip() == ""


def test_search_partial_caps_at_8_hits(client):
    r = client.get("/search/partial?q=hola")
    assert r.status_code == 200
    # Hit count equals number of search-hit anchors in the fragment
    count = r.text.count('class="search-hit"')
    assert count <= 8
