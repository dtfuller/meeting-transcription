import pytest
from fastapi.testclient import TestClient

from app import fs, store
from server import create_app
from tests.helpers.sample_assets import build_nested_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_nested_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    return TestClient(create_app())


def test_create_root_level_folder(client, tmp_path):
    r = client.post("/folders/create", data={"parent_path": "", "name": "Clients2"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients2").is_dir()
    assert (tmp_path / "transcripts" / "Clients2").is_dir()
    assert (tmp_path / "information" / "Clients2").is_dir()


def test_create_nested_folder(client, tmp_path):
    r = client.post("/folders/create", data={"parent_path": "Clients", "name": "Beta"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients" / "Beta").is_dir()


def test_create_refuses_collision(client):
    r = client.post("/folders/create", data={"parent_path": "", "name": "Clients"})
    assert r.status_code == 200
    assert "already exists" in r.text.lower()


def test_create_refuses_invalid_name(client):
    for bad in ["..", "_inbox", "a/b", ""]:
        r = client.post("/folders/create", data={"parent_path": "", "name": bad})
        assert r.status_code == 200
        assert "tree-banner" in r.text


def test_rename_moves_all_three_trees_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/folders/rename", data={"path": "Clients/Acme", "new_name": "Beta"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Clients" / "Beta" / "2026-04-20 09-00-00.mov").exists()
    assert (tmp_path / "transcripts" / "Clients" / "Beta" / "2026-04-20 09-00-00.txt").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_rename_refuses_root(client):
    r = client.post("/folders/rename", data={"path": "", "new_name": "foo"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_rename_refuses_inbox(client):
    r = client.post("/folders/rename", data={"path": "_inbox", "new_name": "foo"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_delete_empty_folder_removes_from_all_three_trees(client, tmp_path):
    (tmp_path / "data" / "Empty").mkdir()
    (tmp_path / "transcripts" / "Empty").mkdir(parents=True, exist_ok=True)
    (tmp_path / "information" / "Empty").mkdir(parents=True, exist_ok=True)
    r = client.post("/folders/delete", data={"path": "Empty"})
    assert r.status_code == 200
    assert not (tmp_path / "data" / "Empty").exists()


def test_delete_non_empty_folder_refused_with_banner(client):
    r = client.post("/folders/delete", data={"path": "Clients"})
    assert r.status_code == 200
    assert "move contents out" in r.text.lower()


def test_delete_refuses_inbox(client):
    r = client.post("/folders/delete", data={"path": "_inbox"})
    assert r.status_code == 200
    assert "tree-banner" in r.text


def test_move_folder_moves_tree_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/folders/move",
                    data={"path": "Clients/Acme", "new_parent_path": ""})
    assert r.status_code == 200
    assert (tmp_path / "data" / "Acme" / "2026-04-20 09-00-00.mov").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_move_folder_refuses_cycle(client):
    r = client.post("/folders/move",
                    data={"path": "Clients", "new_parent_path": "Clients/Acme"})
    assert r.status_code == 200
    assert "cycle" in r.text.lower() or "into its own" in r.text.lower()


def test_move_folder_refuses_destination_collision(client, tmp_path):
    (tmp_path / "data" / "multiturbo" / "Acme").mkdir(parents=True, exist_ok=True)
    r = client.post("/folders/move",
                    data={"path": "Clients/Acme", "new_parent_path": "multiturbo"})
    assert r.status_code == 200
    assert "already exists" in r.text.lower()


def test_meeting_move_changes_subdir_and_reindexes(client, tmp_path, monkeypatch):
    reindexed = []
    from app import search as _s
    monkeypatch.setattr(_s, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = client.post("/meetings/2026-04-20 09-00-00/move",
                    data={"new_subdir": "multiturbo"})
    assert r.status_code == 200
    assert (tmp_path / "data" / "multiturbo" / "2026-04-20 09-00-00.mov").exists()
    assert "2026-04-20 09-00-00" in reindexed


def test_meeting_move_refuses_inbox_destination(client):
    r = client.post("/meetings/2026-04-20 09-00-00/move",
                    data={"new_subdir": "_inbox"})
    assert r.status_code == 200
    assert "_inbox" in r.text


def test_tree_partial_endpoint_returns_aside(client):
    r = client.get("/meetings/tree-partial")
    assert r.status_code == 200
    assert "<aside" in r.text and 'class="tree"' in r.text
