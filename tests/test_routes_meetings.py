from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def app_with_tree(tmp_path, monkeypatch):
    from app import store
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    return TestClient(create_app())


@pytest.fixture
def app_with_tree_with_tags(tmp_path, monkeypatch):
    from app import store
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    store.set_meeting_tags(
        "2026-04-14 17-00-43",
        [store.Tag(name="Darwin Henao", type="person")],
        source="manual",
    )
    return TestClient(create_app())


def test_meetings_index_lists_tree(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert r.status_code == 200
    assert "multiturbo" in r.text
    assert "2026-04-14 17-00-43" in r.text
    assert "check-in" in r.text


def test_unknown_badge_shown_for_meetings_with_unknown_speakers(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert '2026-04-16 17-01-16' in r.text
    assert 'class="badge"' in r.text


def test_meeting_detail_renders_transcript(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43?view=transcript")
    assert r.status_code == 200
    assert "David Fuller" in r.text
    assert "hola" in r.text


def test_meeting_detail_unknown_404(app_with_tree):
    r = app_with_tree.get("/meetings/does-not/exist")
    assert r.status_code == 404


def test_unknown_speaker_highlighted(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-16 17-01-16?view=transcript")
    assert 'class="unk">Unknown Speaker 1' in r.text


def test_knowledge_view_renders_markdown(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43?view=knowledge")
    assert "<h1>" in r.text or "<h1 " in r.text


import sys
import time
from pathlib import Path

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


def test_post_reextract_starts_runner(app_with_tree, monkeypatch):
    from app import pipeline, search
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.meetings.build_reextract_argv",
        lambda m: [sys.executable, str(HELPER)],
    )
    reindexed: list[str] = []
    monkeypatch.setattr(search, "reindex_meeting", lambda stem: reindexed.append(stem))
    r = app_with_tree.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/reextract",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)
    # Allow on_complete to fire after the pump thread exits
    for _ in range(20):
        if reindexed: break
        time.sleep(0.05)
    assert "2026-04-14 17-00-43" in reindexed


def test_post_reclassify_one_starts_runner(app_with_tree, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.meetings.build_reclassify_argv",
        lambda m: [sys.executable, str(HELPER)],
    )
    r = app_with_tree.post(
        "/meetings/multiturbo/2026-04-16 17-01-16/reclassify",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)


def test_meeting_detail_shows_tag_section(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert "Darwin Henao" in r.text
    assert 'class="tag tag-person"' in r.text


def test_meeting_tree_filters_by_tag(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings?tag=Darwin+Henao&tag_type=person")
    assert r.status_code == 200
    assert "2026-04-14 17-00-43" in r.text
    assert "2026-04-17 09-00-00" not in r.text


def test_post_meeting_tags_replaces_tags(app_with_tree_with_tags):
    from app import store
    r = app_with_tree_with_tags.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/tags",
        data={"tag_name": ["Maria Lopez", "onboarding"],
              "tag_type": ["person", "topic"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    tags = store.list_meeting_tags("2026-04-14 17-00-43")
    names = sorted(t.name for t in tags)
    assert names == ["Maria Lopez", "onboarding"]


def test_meeting_detail_has_prev_and_next(app_with_tree):
    # Sorted order: check-in/2026-04-17 → multiturbo/2026-04-14 → multiturbo/2026-04-16
    # The middle one has both neighbors. URLs are percent-encoded (%20 for space).
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert "/meetings/check-in/2026-04-17%2009-00-00" in r.text
    assert "/meetings/multiturbo/2026-04-16%2017-01-16" in r.text


def test_first_meeting_has_no_prev_link(app_with_tree):
    r = app_with_tree.get("/meetings/check-in/2026-04-17 09-00-00")
    assert r.status_code == 200
    assert '<span class="mini-btn disabled">← Prev' in r.text


def test_last_meeting_has_no_next_link(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-16 17-01-16")
    assert r.status_code == 200
    assert '<span class="mini-btn disabled">Next →' in r.text


def test_tree_renders_flat_for_small_subdir(app_with_tree):
    # Sample tree has 2 meetings in multiturbo, 1 in check-in — all below threshold.
    r = app_with_tree.get("/meetings")
    assert r.status_code == 200
    # No month-group details because nothing is grouped by month.
    # (folder-group <details> always wraps each subdir.)
    assert 'class="month-group"' not in r.text


def test_tree_renders_details_groups_when_subdir_exceeds_threshold(tmp_path, monkeypatch):
    # Build a fresh tree with 11 meetings in one subdir spanning two months.
    from app import fs, store
    from server import create_app
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    # 5 in April, 6 in May → 11 total, above the default threshold of 10
    for day in range(1, 6):
        p = tmp_path / "data" / "big" / f"2026-04-{day:02d} 10-00-00.mov"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" * 16)
    for day in range(1, 7):
        p = tmp_path / "data" / "big" / f"2026-05-{day:02d} 10-00-00.mov"
        p.write_bytes(b"\x00" * 16)

    client = TestClient(create_app())
    r = client.get("/meetings")
    assert r.status_code == 200
    assert '<details class="month-group" open>' in r.text  # most-recent May open
    assert "2026-05" in r.text
    assert "2026-04" in r.text


def test_meeting_detail_defaults_to_knowledge_subtab(app_with_tree):
    # Visiting a meeting without ?view= must land on Knowledge, not Transcript.
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200

    def subtab_is_active(label: str) -> bool:
        tail = r.text.find(f">{label}</a>")
        head = r.text.rfind("<a ", 0, tail)
        return "active" in r.text[head:tail]

    assert subtab_is_active("Knowledge")
    assert not subtab_is_active("Transcript")
    assert not subtab_is_active("Commitments")


def test_suggest_tags_returns_proposed_tags(app_with_tree_with_tags, monkeypatch):
    import json as json_mod
    from tests.helpers.fake_anthropic import FakeAnthropic
    fake = FakeAnthropic(text=json_mod.dumps({
        "subdir": "multiturbo",
        "tags": [
            {"name": "Darwin Henao", "type": "person"},
            {"name": "roadmap Q2", "type": "project"},
        ],
    }))
    from app import categorize
    monkeypatch.setattr(categorize, "_build_client", lambda: fake)

    r = app_with_tree_with_tags.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/suggest-tags",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tags"] == [
        {"name": "Darwin Henao", "type": "person"},
        {"name": "roadmap Q2", "type": "project"},
    ]


def test_suggest_tags_404_on_unknown_meeting(app_with_tree_with_tags):
    r = app_with_tree_with_tags.post("/meetings/ghost/missing/suggest-tags")
    assert r.status_code == 404


def test_suggest_tags_button_rendered_on_detail(app_with_tree_with_tags):
    r = app_with_tree_with_tags.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert "Suggest tags" in r.text
    assert 'id="suggest-tags-btn"' in r.text


def test_split_row_tags_caps_at_2_persons_and_1_other():
    from app import store
    from app.routes.meetings import _split_row_tags
    persons = [store.Tag(name=f"P{i}", type="person") for i in range(5)]
    topics = [store.Tag(name=f"T{i}", type="topic") for i in range(3)]
    projects = [store.Tag(name=f"J{i}", type="project") for i in range(2)]
    split = _split_row_tags(persons + topics + projects)
    visible_names = [t.name for t in split["visible"]]
    hidden_names = [t.name for t in split["hidden"]]
    assert visible_names == ["P0", "P1", "T0"]
    assert set(hidden_names) == {"P2", "P3", "P4", "T1", "T2", "J0", "J1"}


def test_meetings_tree_caps_tags_with_overflow(tmp_path, monkeypatch):
    from app import fs, store
    from server import create_app
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()

    stem = "2026-05-01 10-00-00"
    p = tmp_path / "data" / "big" / f"{stem}.mov"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00" * 16)

    persons = [store.Tag(name=f"Person{i}", type="person") for i in range(5)]
    topics = [store.Tag(name=f"Topic{i}", type="topic") for i in range(4)]
    store.set_meeting_tags(stem, persons + topics, source="manual")

    client = TestClient(create_app())
    r = client.get("/meetings")
    assert r.status_code == 200
    # First 2 persons visible
    for name in ["Person0", "Person1"]:
        assert f"\U0001f464 {name}" in r.text
    # First 1 topic visible
    assert f"\U0001f3f7 Topic0" in r.text
    # Overflow toggle with correct count: 5+4 - 3 visible = 6 hidden
    assert ">+6 more</button>" in r.text
    # Remaining tags present in the page (inside hidden overflow)
    for name in ["Person2", "Person3", "Person4", "Topic1", "Topic2", "Topic3"]:
        assert name in r.text
    # Overflow marker present + hidden
    assert 'class="row-tags-overflow" hidden' in r.text


def test_meetings_tree_wraps_subdir_in_folder_group(app_with_tree):
    r = app_with_tree.get("/meetings")
    assert r.status_code == 200
    assert '<details class="folder-group" open>' in r.text
    assert '<summary class="folder">📁 multiturbo</summary>' in r.text
    assert '<summary class="folder">📁 check-in</summary>' in r.text
