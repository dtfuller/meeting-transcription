import pytest

from app import fs, search, store
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    yield


def test_fts_schema_exists():
    with store.connect() as c:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE name = 'meetings_fts'"
        ).fetchone()
    assert row is not None


def test_reindex_all_populates_from_filesystem():
    count = search.reindex_all()
    # Sample tree has 2 meetings with transcript + knowledge + commitments (6 rows)
    # plus 1 meeting with just a stub; total rows >= 6
    assert count >= 6
    assert search.row_count() == count


def test_reindex_meeting_upserts_rows():
    # Initial: index all
    search.reindex_all()
    initial = search.row_count()
    # Reindex one meeting — should not double-insert
    search.reindex_meeting("2026-04-14 17-00-43")
    assert search.row_count() == initial


def test_reindex_meeting_handles_missing_meeting_gracefully():
    search.reindex_all()
    # Vanishing meeting: pre-insert a fake row, then reindex with nonexistent stem
    with store.connect() as c:
        c.execute("INSERT INTO meetings_fts (stem, subdir, kind, body) VALUES (?, ?, ?, ?)",
                  ("ghost", "nowhere", "transcript", "hello"))
    search.reindex_meeting("ghost")
    # Ghost's rows should be gone (meeting not found on filesystem)
    with store.connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM meetings_fts WHERE stem = 'ghost'"
                      ).fetchone()["n"]
    assert n == 0


def test_delete_meeting_from_index():
    search.reindex_all()
    search.delete_meeting_from_index("2026-04-14 17-00-43")
    with store.connect() as c:
        n = c.execute(
            "SELECT COUNT(*) AS n FROM meetings_fts WHERE stem = ?",
            ("2026-04-14 17-00-43",),
        ).fetchone()["n"]
    assert n == 0
