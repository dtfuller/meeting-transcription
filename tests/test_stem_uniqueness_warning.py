import logging

import pytest

from app import fs


def test_assert_stem_uniqueness_warns_on_duplicates(tmp_path, monkeypatch, caplog):
    (tmp_path / "data" / "A").mkdir(parents=True)
    (tmp_path / "data" / "B").mkdir(parents=True)
    (tmp_path / "data" / "A" / "dup.mov").write_bytes(b"\x00")
    (tmp_path / "data" / "B" / "dup.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    with caplog.at_level(logging.WARNING):
        fs.assert_stem_uniqueness_or_warn()
    assert any("duplicate stem 'dup'" in rec.message for rec in caplog.records)


def test_assert_stem_uniqueness_silent_on_unique(tmp_path, monkeypatch, caplog):
    (tmp_path / "data" / "A").mkdir(parents=True)
    (tmp_path / "data" / "A" / "unique.mov").write_bytes(b"\x00")
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    with caplog.at_level(logging.WARNING):
        fs.assert_stem_uniqueness_or_warn()
    assert not any("duplicate stem" in rec.message for rec in caplog.records)
