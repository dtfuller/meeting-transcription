import pytest

from app import clips, fs
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture(autouse=True)
def anchor(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    clips.reset_counter()
    yield


def test_label_clip_moves_and_renames():
    result = clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    assert result.new_path.exists()
    assert result.new_path.parent == fs.KNOWN_NAMES_TO_USE
    assert result.new_path.name == "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s.mov"
    assert not (fs.KNOWN_NAMES_TO_CLASSIFY /
                "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov").exists()


def test_label_clip_dedup_suffix_when_target_exists():
    clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    src = fs.KNOWN_NAMES_TO_CLASSIFY / "Unknown Speaker X - 2026-04-16 17-01-16 - 01m08s.mov"
    src.write_bytes(b"\x00")
    r = clips.label_clip(src.name, "Alejandra Gomez")
    assert r.new_path.name == "Alejandra Gomez - 2026-04-16 17-01-16 - 01m08s (2).mov"


def test_label_clip_rejects_traversal():
    with pytest.raises(ValueError):
        clips.label_clip("../etc/passwd", "Anyone")


def test_counter_increments_and_resets():
    assert clips.labels_since_reset() == 0
    clips.label_clip(
        "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov",
        "Alejandra Gomez",
    )
    assert clips.labels_since_reset() == 1
    clips.label_clip(
        "Unknown Speaker 2 - 2026-04-16 17-01-16 - 03m22s.mov",
        "Maria Lopez",
    )
    assert clips.labels_since_reset() == 2
    clips.reset_counter()
    assert clips.labels_since_reset() == 0
