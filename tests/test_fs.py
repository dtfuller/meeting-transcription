from pathlib import Path

import pytest

from app import fs
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def tree(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "ROOT", tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    return tmp_path


def test_list_meetings_returns_all_movs_grouped_by_subdir(tree):
    meetings = fs.list_meetings()
    keys = [(m.subdir, m.stem) for m in meetings]
    assert ("check-in", "2026-04-17 09-00-00") in keys
    assert ("multiturbo", "2026-04-14 17-00-43") in keys
    assert ("multiturbo", "2026-04-16 17-01-16") in keys
    assert len(keys) == 3


def test_meeting_has_status_flags(tree):
    meetings = {(m.subdir, m.stem): m for m in fs.list_meetings()}
    done = meetings[("multiturbo", "2026-04-14 17-00-43")]
    assert done.has_transcript and done.has_knowledge and done.has_commitments
    assert done.unknown_count == 0

    partial = meetings[("multiturbo", "2026-04-16 17-01-16")]
    assert partial.unknown_count == 1  # one "Unknown Speaker" line

    raw = meetings[("check-in", "2026-04-17 09-00-00")]
    assert not raw.has_transcript


def test_find_meeting_by_key(tree):
    m = fs.find_meeting("multiturbo", "2026-04-14 17-00-43")
    assert m is not None
    assert m.mov_path.exists()

    assert fs.find_meeting("does-not", "exist") is None


def test_load_transcript_knowledge_commitments(tree):
    m = fs.find_meeting("multiturbo", "2026-04-14 17-00-43")
    assert "David Fuller" in fs.load_transcript(m)
    assert fs.load_knowledge(m).startswith("# K")
    assert fs.load_commitments(m).startswith("# C")


def test_list_unknown_clips_parses_filename(tree):
    clips = fs.list_unknown_clips()
    assert len(clips) == 2
    c = clips[0]
    assert c.raw_label.startswith("Unknown Speaker")
    assert c.source_stem == "2026-04-16 17-01-16"
    assert c.timestamp_text == "01m08s"
    assert c.filename.endswith(".mov")


def test_list_known_names_groups_by_prefix(tree):
    names = fs.list_known_names()
    assert "David Fuller" in names  # grouped from two files
    assert "Darwin Henao" in names
    # Deduped
    assert names.count("David Fuller") == 1
