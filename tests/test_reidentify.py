import numpy as np
import pytest

from app import fs, reidentify, store
from tests.helpers.sample_assets import build_sample_tree


# Synthetic unit vectors keyed by person/label name. Cosine similarity between
# two matching keys is 1.0; between mismatched keys, 0.0. Picking indices:
#   0 = David Fuller / Unknown Speaker 1 (target match)
#   1 = Darwin Henao
#   9 = Unknown Speaker 2 (deliberately orthogonal to every known name)
_VEC_INDEX = {
    "David Fuller": 0,
    "Darwin Henao": 1,
    "Unknown Speaker 1": 0,
    "Unknown Speaker 2": 9,
}


def _fake_embedding(path):
    """Derive a unit vector from the filename prefix before ' - '."""
    key = path.stem.split(" - ")[0]
    idx = _VEC_INDEX.get(key, 8)
    v = np.zeros(10, dtype=float)
    v[idx] = 1.0
    return v


@pytest.fixture
def sample_fs(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    monkeypatch.setattr(reidentify, "_compute_clip_embedding", _fake_embedding)
    return tmp_path


def test_rematch_matches_clip_and_patches_transcript(sample_fs):
    transcript_path = (sample_fs / "transcripts" / "multiturbo"
                       / "2026-04-16 17-01-16.txt")
    before = transcript_path.read_text(encoding="utf-8")
    assert "Unknown Speaker 1" in before

    result = reidentify.rematch_unknown_clips()

    matched_names = {name for _, name in result.matched}
    assert "David Fuller" in matched_names
    # Unknown Speaker 2 should stay unmatched (orthogonal vector).
    assert any("Unknown Speaker 2" in fn for fn in result.unmatched)

    after = transcript_path.read_text(encoding="utf-8")
    assert "Unknown Speaker 1" not in after
    assert "[00:01:08 David Fuller]" in after

    # File was moved into to-use/.
    to_use = sample_fs / "known-names" / "to-use"
    moved = list(to_use.glob("David Fuller - 2026-04-16 17-01-16 - 01m08s.mov"))
    assert moved, "clip should have been relabeled into to-use/"


def test_rematch_unmatched_clip_stays_in_queue(sample_fs):
    result = reidentify.rematch_unknown_clips()
    # The orthogonal clip remains.
    to_classify = sample_fs / "known-names" / "to-classify"
    still_there = list(to_classify.glob("Unknown Speaker 2 - *"))
    assert still_there, "unmatched clip should remain in to-classify/"
    assert any("Unknown Speaker 2" in fn for fn in result.unmatched)


def test_rematch_empty_queue_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    result = reidentify.rematch_unknown_clips()
    assert result.matched == []
    assert result.unmatched == []


def test_rematch_no_references_marks_all_unmatched(sample_fs, monkeypatch):
    # Nuke the references directory so _reference_embeddings returns {}.
    import shutil
    shutil.rmtree(sample_fs / "known-names" / "to-use")
    result = reidentify.rematch_unknown_clips()
    assert result.matched == []
    assert len(result.unmatched) == 2  # both seeded clips


def test_apply_label_falls_back_when_unify_renumbered_labels(sample_fs):
    """If the raw_label from the clip filename is no longer in the transcript
    (unify step renamed it), fall back to timestamp-neighborhood lookup."""
    transcript_path = (sample_fs / "transcripts" / "multiturbo"
                       / "2026-04-16 17-01-16.txt")
    # Simulate a post-unify rename: "Unknown Speaker 1" → "Unknown Speaker 5".
    transcript_path.write_text(
        "[00:00:15 Darwin Henao] hola\n[00:01:08 Unknown Speaker 5] …\n",
        encoding="utf-8",
    )
    changed = reidentify.apply_label_to_transcript(
        source_stem="2026-04-16 17-01-16",
        raw_label="Unknown Speaker 1",  # stale; not literally in transcript
        ts_text="01m08s",
        new_name="David Fuller",
    )
    assert changed is True
    after = transcript_path.read_text(encoding="utf-8")
    assert "Unknown Speaker 5" not in after
    assert "[00:01:08 David Fuller]" in after


def test_apply_label_to_missing_transcript_returns_false(sample_fs):
    changed = reidentify.apply_label_to_transcript(
        source_stem="nonexistent-stem",
        raw_label="Unknown Speaker 1",
        ts_text="00m10s",
        new_name="Someone",
    )
    assert changed is False


def test_labels_near_timestamp_finds_neighbors():
    text = (
        "[00:01:05 Unknown Speaker 2] one\n"
        "[00:01:08 Unknown Speaker 5] two\n"
        "[00:05:00 Unknown Speaker 7] far away\n"
    )
    labels = reidentify._labels_near_timestamp(text, "01m08s", window_s=5)
    assert labels == ["Unknown Speaker 2", "Unknown Speaker 5"]


def test_labels_near_timestamp_does_not_substring_match():
    """'Unknown Speaker 1' must not be a replacement target when only
    'Unknown Speaker 11' is near the timestamp."""
    text = "[00:01:08 Unknown Speaker 11] hi\n"
    labels = reidentify._labels_near_timestamp(text, "01m08s", window_s=5)
    assert labels == ["Unknown Speaker 11"]
