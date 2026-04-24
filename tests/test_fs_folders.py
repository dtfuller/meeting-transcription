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
