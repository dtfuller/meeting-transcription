import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ui_db(tmp_path_factory, monkeypatch):
    """Redirect store.DB_PATH to a throwaway per-test tmp file.

    Prevents any test that calls TestClient(create_app()) from writing to the
    repo-root ui.db (which can otherwise be populated with sample-tree fixture
    content or accidentally mutated during test runs). Tests that need a
    specific DB location just monkeypatch again — their override wins.
    """
    from app import store
    tmp = tmp_path_factory.mktemp("default_ui_db")
    monkeypatch.setattr(store, "DB_PATH", tmp / "ui.db")
    yield


@pytest.fixture
def client():
    return TestClient(create_app())
