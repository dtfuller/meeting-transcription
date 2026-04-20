import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ui_state(tmp_path_factory, monkeypatch):
    """Redirect store.DB_PATH AND config_store.CONFIG_PATH to per-test tmp files.

    Prevents any test that calls TestClient(create_app()) or config_store.save()
    from writing to the repo-root ui.db / ui.json (which can otherwise be
    populated with sample-tree fixture content or accidentally mutated during
    test runs). Tests that need a specific location just monkeypatch again —
    their override wins.
    """
    from app import config_store, store
    tmp = tmp_path_factory.mktemp("default_ui_state")
    monkeypatch.setattr(store, "DB_PATH", tmp / "ui.db")
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp / "ui.json")
    yield


@pytest.fixture
def client():
    return TestClient(create_app())
