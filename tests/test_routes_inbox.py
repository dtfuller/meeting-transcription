import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs, ingest, pipeline, store
from server import create_app
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "INFORMATION_DIR", tmp_path / "information")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_USE", tmp_path / "known-names" / "to-use")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()
    yield TestClient(create_app())
    pipeline.get_runner().reset_for_tests()
    ingest.get_coordinator().reset_for_tests()


def _seed_proposal(stem: str, subdir: str, tags, status="ready"):
    store.save_proposal(
        stem=stem,
        proposed_subdir=subdir,
        proposed_tags=tags,
        status=status,
        error_message=None,
    )
    inbox_mov = fs.DATA_DIR / store.INBOX_SUBDIR / f"{stem}.mov"
    inbox_mov.parent.mkdir(parents=True, exist_ok=True)
    inbox_mov.write_bytes(b"\x00" * 16)
    (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt").parent.mkdir(parents=True, exist_ok=True)
    (fs.TRANSCRIPTS_DIR / store.INBOX_SUBDIR / f"{stem}.txt").write_text("[00:00:00 X] hi\n")
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md").parent.mkdir(parents=True, exist_ok=True)
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-knowledge.md").write_text("# K")
    (fs.INFORMATION_DIR / store.INBOX_SUBDIR / f"{stem}-commitments.md").write_text("# C")


def test_inbox_index_lists_proposals(client):
    _seed_proposal("stem-a", "multiturbo",
                   [store.Tag(name="Darwin Henao", type="person")])
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "stem-a" in r.text
    assert "multiturbo" in r.text
    assert "Darwin Henao" in r.text


def test_inbox_apply_moves_files_and_saves_tags(client):
    _seed_proposal("m-1", "multiturbo",
                   [store.Tag(name="Darwin Henao", type="person")])
    r = client.post(
        "/inbox/m-1/apply",
        data={
            "target_subdir": "multiturbo",
            "tag_name": ["Darwin Henao", "multiturbo"],
            "tag_type": ["person", "topic"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/meetings/multiturbo/m-1"
    assert (fs.DATA_DIR / "multiturbo" / "m-1.mov").exists()
    assert not (fs.DATA_DIR / "_inbox" / "m-1.mov").exists()
    assert (fs.TRANSCRIPTS_DIR / "multiturbo" / "m-1.txt").exists()
    assert (fs.INFORMATION_DIR / "multiturbo" / "m-1-knowledge.md").exists()
    assert (fs.INFORMATION_DIR / "multiturbo" / "m-1-commitments.md").exists()
    assert store.get_proposal("m-1") is None
    tags = store.list_meeting_tags("m-1")
    names = {t.name for t in tags}
    assert names == {"Darwin Henao", "multiturbo"}


def test_inbox_apply_creates_new_subdir_if_needed(client):
    _seed_proposal("m-2", "", [])
    r = client.post(
        "/inbox/m-2/apply",
        data={"target_subdir": "brand-new-category",
              "tag_name": [], "tag_type": []},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert (fs.DATA_DIR / "brand-new-category" / "m-2.mov").exists()


def test_inbox_apply_404_on_unknown_stem(client):
    r = client.post(
        "/inbox/ghost/apply",
        data={"target_subdir": "whatever", "tag_name": [], "tag_type": []},
    )
    assert r.status_code == 404


def test_inbox_dismiss_removes_proposal_without_moving_files(client):
    _seed_proposal("m-3", "multiturbo", [])
    r = client.post("/inbox/m-3/dismiss", follow_redirects=False)
    assert r.status_code == 303
    assert store.get_proposal("m-3") is None
    assert (fs.DATA_DIR / "_inbox" / "m-3.mov").exists()


def test_watcher_status_endpoints(client):
    r = client.get("/watcher/status")
    assert r.status_code == 200
    assert r.json()["is_running"] in (True, False)


def test_inbox_watcher_enabled_when_only_config_set(client, monkeypatch):
    from app import config_store
    monkeypatch.delenv("WATCH_DIR", raising=False)
    config_store.save({"watch_dir": "/some/path"})
    r = client.get("/inbox")
    assert r.status_code == 200
    # Watcher-disabled banner must NOT appear
    assert "Watcher disabled" not in r.text


def test_inbox_card_renders_knowledge_commitments_transcript_video(client):
    _seed_proposal("preview-stem", "multiturbo", [])
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "preview-stem" in r.text
    # _seed_proposal writes "# K" and "# C" — markdown-it wraps these in <h1>
    assert ">K</h1>" in r.text
    assert ">C</h1>" in r.text
    # Transcript content from _seed_proposal
    assert "[00:00:00 X] hi" in r.text
    # Video source points to the _inbox streaming URL
    assert 'src="/video/meeting/_inbox/preview-stem"' in r.text
    # Previews are collapsed by default (no open attr)
    assert '<details class="preview-section" open>' not in r.text


def test_inbox_card_preview_shows_waiting_when_not_ready(client):
    # Proposal with no on-disk files → all preview sections show the placeholder
    store.save_proposal(
        stem="still-cooking",
        proposed_subdir="",
        proposed_tags=[],
        status="transcribing",
        error_message=None,
    )
    r = client.get("/inbox")
    assert r.status_code == 200
    assert "still-cooking" in r.text
    assert "Waiting for pipeline to finish…" in r.text
