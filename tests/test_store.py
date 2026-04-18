import json
from pathlib import Path

import pytest

from app import store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    store.init_schema()
    yield


def test_init_schema_is_idempotent():
    store.init_schema()
    store.init_schema()


def test_save_and_get_proposal():
    tags = [store.Tag(name="Darwin Henao", type="person"),
            store.Tag(name="multiturbo", type="topic")]
    store.save_proposal(
        stem="2026-04-16 17-01-16",
        proposed_subdir="multiturbo",
        proposed_tags=tags,
        status="ready",
        error_message=None,
    )
    p = store.get_proposal("2026-04-16 17-01-16")
    assert p is not None
    assert p.stem == "2026-04-16 17-01-16"
    assert p.proposed_subdir == "multiturbo"
    assert p.proposed_tags == tags
    assert p.status == "ready"
    assert p.error_message is None


def test_save_proposal_upsert():
    store.save_proposal(stem="s", proposed_subdir="a", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.save_proposal(stem="s", proposed_subdir="b", proposed_tags=[],
                        status="ready", error_message=None)
    p = store.get_proposal("s")
    assert p.proposed_subdir == "b"
    assert p.status == "ready"


def test_update_proposal_status():
    store.save_proposal(stem="s", proposed_subdir="", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.update_proposal_status("s", "error", "transcribe failed")
    p = store.get_proposal("s")
    assert p.status == "error"
    assert p.error_message == "transcribe failed"


def test_list_pending_proposals_ordered_by_created_at():
    store.save_proposal(stem="a", proposed_subdir="", proposed_tags=[],
                        status="transcribing", error_message=None)
    store.save_proposal(stem="b", proposed_subdir="", proposed_tags=[],
                        status="ready", error_message=None)
    ps = store.list_pending_proposals()
    stems = [p.stem for p in ps]
    assert set(stems) == {"a", "b"}


def test_delete_proposal():
    store.save_proposal(stem="s", proposed_subdir="", proposed_tags=[],
                        status="ready", error_message=None)
    assert store.get_proposal("s") is not None
    store.delete_proposal("s")
    assert store.get_proposal("s") is None


def test_set_and_list_meeting_tags():
    tags = [store.Tag(name="Darwin Henao", type="person"),
            store.Tag(name="multiturbo", type="topic")]
    store.set_meeting_tags("stem-1", tags, source="manual")
    out = store.list_meeting_tags("stem-1")
    assert set(out) == set(tags)


def test_set_meeting_tags_replaces():
    store.set_meeting_tags("stem-1",
                           [store.Tag(name="A", type="topic")],
                           source="auto")
    store.set_meeting_tags("stem-1",
                           [store.Tag(name="B", type="topic")],
                           source="manual")
    out = store.list_meeting_tags("stem-1")
    assert out == [store.Tag(name="B", type="topic")]


def test_list_stems_with_tag():
    store.set_meeting_tags("m1", [store.Tag(name="Darwin Henao", type="person")],
                           source="manual")
    store.set_meeting_tags("m2", [store.Tag(name="Darwin Henao", type="person")],
                           source="manual")
    store.set_meeting_tags("m3", [store.Tag(name="Alice", type="person")],
                           source="manual")
    stems = store.list_stems_with_tag("Darwin Henao", "person")
    assert set(stems) == {"m1", "m2"}


def test_inbox_subdir_constant():
    assert store.INBOX_SUBDIR == "_inbox"
