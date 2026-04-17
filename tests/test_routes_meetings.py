from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def app_with_tree(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
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
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert "David Fuller" in r.text
    assert "hola" in r.text


def test_meeting_detail_unknown_404(app_with_tree):
    r = app_with_tree.get("/meetings/does-not/exist")
    assert r.status_code == 404


def test_unknown_speaker_highlighted(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-16 17-01-16")
    assert 'class="unk">Unknown Speaker 1' in r.text


def test_knowledge_view_renders_markdown(app_with_tree):
    r = app_with_tree.get("/meetings/multiturbo/2026-04-14 17-00-43?view=knowledge")
    assert "<h1>" in r.text or "<h1 " in r.text


import sys
import time
from pathlib import Path

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


def test_post_reextract_starts_runner(app_with_tree, monkeypatch):
    from app import pipeline
    pipeline.get_runner().reset_for_tests()
    monkeypatch.setattr(
        "app.routes.meetings.build_reextract_argv",
        lambda m: [sys.executable, str(HELPER)],
    )
    r = app_with_tree.post(
        "/meetings/multiturbo/2026-04-14 17-00-43/reextract",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running(): break
        time.sleep(0.05)


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
