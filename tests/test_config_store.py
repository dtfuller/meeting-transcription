import json

import pytest

from app import config_store


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "ui.json")
    yield


def test_load_returns_empty_dict_when_missing():
    assert config_store.load() == {}


def test_save_then_load_roundtrip():
    config_store.save({"watch_dir": "/Users/me/Movies/Meetings", "extra": 42})
    loaded = config_store.load()
    assert loaded == {"watch_dir": "/Users/me/Movies/Meetings", "extra": 42}


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    config_store.save({"a": 1})
    # Only ui.json should exist in the dir, no stray .tmp
    children = {p.name for p in tmp_path.iterdir()}
    assert children == {"ui.json"}


def test_load_returns_empty_dict_on_corrupt_json(tmp_path):
    (tmp_path / "ui.json").write_text("not valid json {")
    assert config_store.load() == {}


def test_get_returns_default_when_key_missing():
    assert config_store.get("watch_dir") is None
    assert config_store.get("watch_dir", "/fallback") == "/fallback"


def test_get_returns_stored_value():
    config_store.save({"watch_dir": "/x"})
    assert config_store.get("watch_dir") == "/x"


def test_watch_dir_returns_config_value_when_set(monkeypatch):
    config_store.save({"watch_dir": "/from/config"})
    monkeypatch.delenv("WATCH_DIR", raising=False)
    assert config_store.watch_dir() == "/from/config"


def test_watch_dir_falls_back_to_env_when_config_missing(monkeypatch):
    monkeypatch.setenv("WATCH_DIR", "/from/env")
    assert config_store.watch_dir() == "/from/env"


def test_watch_dir_config_wins_over_env(monkeypatch):
    config_store.save({"watch_dir": "/from/config"})
    monkeypatch.setenv("WATCH_DIR", "/from/env")
    assert config_store.watch_dir() == "/from/config"


def test_watch_dir_returns_none_when_neither_set(monkeypatch):
    monkeypatch.delenv("WATCH_DIR", raising=False)
    assert config_store.watch_dir() is None
