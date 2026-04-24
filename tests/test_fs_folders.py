import pytest

from app import fs
from tests.helpers.sample_assets import build_nested_sample_tree, build_sample_tree


@pytest.fixture
def nested_tree(tmp_path, monkeypatch):
    build_nested_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    return tmp_path


def test_meeting_subdir_preserves_full_nested_path(nested_tree):
    meetings = {m.stem: m for m in fs.list_meetings()}
    nested = meetings["2026-04-20 09-00-00"]
    assert nested.subdir == "Clients/Acme"


def test_meeting_subdir_empty_string_for_root_level(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    # Seed a root-level .mov (no subdir).
    (tmp_path / "data" / "rootcast.mov").write_bytes(b"\x00" * 16)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    meetings = {m.stem: m for m in fs.list_meetings()}
    assert meetings["rootcast"].subdir == ""


def test_meeting_transcript_path_uses_nested_subdir(nested_tree):
    meetings = {m.stem: m for m in fs.list_meetings()}
    nested = meetings["2026-04-20 09-00-00"]
    assert nested.transcript_path == (
        nested_tree / "transcripts" / "Clients" / "Acme" / "2026-04-20 09-00-00.txt"
    )


def test_find_meeting_by_stem_resolves_nested(nested_tree):
    m = fs.find_meeting_by_stem("2026-04-20 09-00-00")
    assert m is not None
    assert m.subdir == "Clients/Acme"


def test_find_meeting_by_stem_returns_none_when_missing(nested_tree):
    assert fs.find_meeting_by_stem("does-not-exist") is None


def test_list_folders_walks_all_depths(nested_tree):
    folders = {f.path: f for f in fs.list_folders()}
    assert "Clients" in folders
    assert "Clients/Acme" in folders
    assert folders["Clients/Acme"].name == "Acme"
    assert folders["Clients/Acme"].parent == "Clients"
    assert folders["Clients"].parent == ""


def test_list_folders_excludes_inbox(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    inbox = tmp_path / "data" / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "pending.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    paths = [f.path for f in fs.list_folders()]
    assert "_inbox" not in paths


def test_folder_exists_for_existing_and_missing(nested_tree):
    assert fs.folder_exists("Clients") is True
    assert fs.folder_exists("Clients/Acme") is True
    assert fs.folder_exists("nope") is False
    # Root "" is always considered existing.
    assert fs.folder_exists("") is True


def test_folder_is_empty_false_when_meeting_present(nested_tree):
    # "Clients" contains "Acme" which contains a meeting.
    assert fs.folder_is_empty("Clients") is False


def test_folder_is_empty_true_for_empty_dir(tmp_path, monkeypatch):
    (tmp_path / "data" / "Empty").mkdir(parents=True)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    assert fs.folder_is_empty("Empty") is True


def test_folder_is_empty_false_when_only_subfolder_present(tmp_path, monkeypatch):
    (tmp_path / "data" / "Parent" / "Child").mkdir(parents=True)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    assert fs.folder_is_empty("Parent") is False
