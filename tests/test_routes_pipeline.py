import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fs, pipeline
from server import create_app
from tests.helpers.sample_assets import build_sample_tree

HELPER = Path(__file__).parent / "helpers" / "fake_pipeline.py"


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_sample_tree(tmp_path)
    monkeypatch.setattr(fs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fs, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(fs, "KNOWN_NAMES_TO_CLASSIFY", tmp_path / "known-names" / "to-classify")
    pipeline.get_runner().reset_for_tests()
    yield TestClient(create_app())
    pipeline.get_runner().reset_for_tests()


def test_pipeline_page_renders_form(client):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Run" in r.text
    assert 'name="scope"' in r.text
    assert 'name="mode"' in r.text


def test_run_starts_subprocess_and_redirects(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, str(HELPER)],
    )
    r = client.post("/pipeline/run",
                    data={"scope": "all", "mode": "new"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/pipeline"
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)
    assert pipeline.get_runner().last_return_code == 0


def test_second_run_while_active_returns_409(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, "-c", "import time; time.sleep(1)"],
    )
    r1 = client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                     follow_redirects=False)
    assert r1.status_code == 303

    r2 = client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                     follow_redirects=False)
    assert r2.status_code == 409


def test_stream_emits_history_and_exit(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.pipeline_routes.resolve_argv",
        lambda scope, mode: [sys.executable, str(HELPER)],
    )
    client.post("/pipeline/run", data={"scope": "all", "mode": "new"},
                follow_redirects=False)
    for _ in range(200):
        if not pipeline.get_runner().is_running():
            break
        time.sleep(0.05)

    r = client.get("/pipeline/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "starting" in body
    assert "done" in body
    assert "EXIT 0" in body
