import pytest
from fastapi.testclient import TestClient

from app import fs, store
from server import create_app
from tests.helpers.sample_assets import build_sample_tree


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "ui.db")
    return TestClient(create_app())


def test_meeting_video_200(client):
    r = client.get("/video/meeting/multiturbo/2026-04-14 17-00-43")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/")
    assert r.headers.get("accept-ranges") == "bytes"


def test_meeting_video_range_206(client):
    r = client.get("/video/meeting/multiturbo/2026-04-14 17-00-43",
                   headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.headers["content-range"].startswith("bytes 0-3/")
    assert len(r.content) == 4


def test_meeting_video_404(client):
    r = client.get("/video/meeting/nope/missing")
    assert r.status_code == 404


def test_clip_video_200(client):
    r = client.get("/video/clip/Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov")
    assert r.status_code == 200


def test_clip_video_rejects_traversal(client):
    r = client.get("/video/clip/..%2Fsecrets.mov")
    assert r.status_code in (400, 404)
