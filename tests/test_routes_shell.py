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


def test_header_contains_search_form(client):
    r = client.get("/meetings")
    assert r.status_code == 200
    assert '<form class="search"' in r.text
    assert 'name="q"' in r.text
    assert 'action="/search"' in r.text


def test_header_contains_config_link(client):
    r = client.get("/meetings")
    assert r.status_code == 200
    # gear icon link to /config
    assert 'href="/config"' in r.text


def test_config_store_watch_dir_takes_precedence_over_env(tmp_path, monkeypatch):
    from app import config_store, watcher as watcher_mod
    # Fresh shared watcher
    monkeypatch.setattr(watcher_mod, "_shared", None)
    # Store config
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "ui.json")
    config_dir = tmp_path / "from_config"
    config_dir.mkdir()
    config_store.save({"watch_dir": str(config_dir)})
    # Env also sets a different dir
    env_dir = tmp_path / "from_env"
    env_dir.mkdir()
    monkeypatch.setenv("WATCH_DIR", str(env_dir))

    # Re-import the helper function from server
    from server import resolve_watch_dir
    assert resolve_watch_dir() == str(config_dir)


def test_resolve_watch_dir_falls_back_to_env(tmp_path, monkeypatch):
    from app import config_store
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "ui.json")
    env_dir = tmp_path / "only_env"
    env_dir.mkdir()
    monkeypatch.setenv("WATCH_DIR", str(env_dir))
    from server import resolve_watch_dir
    assert resolve_watch_dir() == str(env_dir)


def test_resolve_watch_dir_none_when_neither_set(tmp_path, monkeypatch):
    from app import config_store
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "ui.json")
    monkeypatch.delenv("WATCH_DIR", raising=False)
    from server import resolve_watch_dir
    assert resolve_watch_dir() is None
