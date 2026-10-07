import pytest
from fastapi.testclient import TestClient

from studydesk.ai import runner as runner_module
from studydesk.config import Config
from studydesk.server import create_app


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """Tests must never start the real Claude Code (ARCHITECTURE: Tests)."""
    real_run = runner_module.ClaudeCLI.run

    def guarded(self, call):
        if self.executable == "claude":
            raise AssertionError("a test tried to call the real claude; pass a FakeRunner")
        return real_run(self, call)

    monkeypatch.setattr(runner_module.ClaudeCLI, "run", guarded)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated app directory, so tests never touch the real config or database."""
    path = tmp_path / "home"
    monkeypatch.setenv("STUDYDESK_HOME", str(path))
    return path


@pytest.fixture
def client(home):
    return TestClient(create_app(Config(home=home)))
