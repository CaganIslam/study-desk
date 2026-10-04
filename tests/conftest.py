import pytest
from fastapi.testclient import TestClient

from studydesk.config import Config
from studydesk.server import create_app


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated app directory, so tests never touch the real config or database."""
    path = tmp_path / "home"
    monkeypatch.setenv("STUDYDESK_HOME", str(path))
    return path


@pytest.fixture
def client(home):
    return TestClient(create_app(Config(home=home)))
