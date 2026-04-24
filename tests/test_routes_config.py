import pytest
from fastapi.testclient import TestClient

from app import config_store, folder_picker, watcher
from server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "ui.json")
    # Reset the shared watcher to a fresh instance so tests don't bleed
    monkeypatch.setattr(watcher, "_shared", None)
    return TestClient(create_app())


def test_config_page_renders(client):
    r = client.get("/config")
    assert r.status_code == 200
    assert 'name="watch_dir"' in r.text


def test_config_page_prefills_current_watch_dir(client):
    config_store.save({"watch_dir": "/Users/me/Movies/X"})
    r = client.get("/config")
    assert 'value="/Users/me/Movies/X"' in r.text


def test_post_config_saves_and_reconfigures_watcher(client, monkeypatch, tmp_path):
    # Ensure a target dir exists
    target = tmp_path / "meetings"
    target.mkdir()
    r = client.post("/config",
                    data={"watch_dir": str(target)},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/config"
    assert config_store.get("watch_dir") == str(target)


def test_post_browse_returns_picked_path(client, monkeypatch):
    monkeypatch.setattr(folder_picker, "pick_folder",
                        lambda initial=None: "/Users/me/Movies/Picked")
    r = client.post("/config/browse")
    assert r.status_code == 200
    assert r.json()["path"] == "/Users/me/Movies/Picked"


def test_post_browse_returns_empty_path_when_cancelled(client, monkeypatch):
    monkeypatch.setattr(folder_picker, "pick_folder", lambda initial=None: None)
    r = client.post("/config/browse")
    assert r.status_code == 200
    assert r.json()["path"] is None


def test_post_config_rejects_nonexistent_path(client):
    r = client.post("/config",
                    data={"watch_dir": "/tmp/definitely-does-not-exist-12345"},
                    follow_redirects=False)
    assert r.status_code == 400


def test_config_page_prefills_from_env_when_ui_json_absent(client, monkeypatch):
    # No ui.json save; only env var set
    monkeypatch.setenv("WATCH_DIR", "/from/env/only")
    r = client.get("/config")
    assert r.status_code == 200
    assert 'value="/from/env/only"' in r.text
