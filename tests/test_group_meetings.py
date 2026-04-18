from pathlib import Path

from app import fs
from app.fs import Meeting


def _mk(subdir: str, stem: str) -> Meeting:
    base = Path("/nonexistent") / subdir
    return Meeting(
        subdir=subdir,
        stem=stem,
        mov_path=base / f"{stem}.mov",
        transcript_path=Path("/nonexistent/transcripts") / subdir / f"{stem}.txt",
        knowledge_path=Path("/nonexistent/information") / subdir / f"{stem}-knowledge.md",
        commitments_path=Path("/nonexistent/information") / subdir / f"{stem}-commitments.md",
    )


def test_empty_list_returns_empty():
    assert fs.group_meetings([]) == []


def test_single_subdir_below_threshold_is_flat():
    meetings = [_mk("multiturbo", f"2026-04-{d:02d} 10-00-00") for d in range(1, 6)]
    result = fs.group_meetings(meetings, threshold=10)
    assert len(result) == 1
    block = result[0]
    assert block["subdir"] == "multiturbo"
    assert block["is_grouped"] is False
    assert block["flat"] == meetings
    assert block["months"] is None


def test_subdir_above_threshold_is_grouped_by_month():
    april = [_mk("multiturbo", f"2026-04-{d:02d} 10-00-00") for d in range(1, 6)]
    may = [_mk("multiturbo", f"2026-05-{d:02d} 10-00-00") for d in range(1, 7)]
    result = fs.group_meetings(april + may, threshold=10)
    block = result[0]
    assert block["is_grouped"] is True
    assert block["flat"] is None
    labels = [m["label"] for m in block["months"]]
    assert labels == ["2026-05", "2026-04"]
    assert block["months"][0]["open"] is True
    assert block["months"][1]["open"] is False
    assert block["months"][0]["meetings"] == may
    assert block["months"][1]["meetings"] == april


def test_mixed_subdirs_independent_grouping():
    small = [_mk("check-in", f"2026-01-{d:02d} 10-00-00") for d in range(1, 4)]
    large = [_mk("multiturbo", f"2026-0{m}-01 10-00-00") for m in range(1, 12)]
    result = fs.group_meetings(small + large, threshold=10)
    by_subdir = {b["subdir"]: b for b in result}
    assert by_subdir["check-in"]["is_grouped"] is False
    assert by_subdir["multiturbo"]["is_grouped"] is True


def test_stems_without_yyyy_mm_prefix_go_to_other_bucket():
    meetings = [_mk("mix", f"2026-01-{d:02d} 10-00-00") for d in range(1, 11)]
    meetings.append(_mk("mix", "random-name-with-no-date"))
    result = fs.group_meetings(meetings, threshold=10)
    block = result[0]
    assert block["is_grouped"] is True
    labels = [m["label"] for m in block["months"]]
    assert labels[-1] == "other"


def test_input_not_required_to_be_sorted():
    meetings = [
        _mk("x", "2026-05-10 10-00-00"),
        _mk("x", "2026-04-10 10-00-00"),
        _mk("x", "2026-05-01 10-00-00"),
    ] * 4
    result = fs.group_meetings(meetings, threshold=10)
    block = result[0]
    assert block["is_grouped"] is True
    labels = [m["label"] for m in block["months"]]
    assert labels == ["2026-05", "2026-04"]
