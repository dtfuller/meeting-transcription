import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())
