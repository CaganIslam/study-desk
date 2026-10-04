import plistlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_agent_definition_is_a_valid_plist():
    out = subprocess.run([str(REPO / "scripts" / "install.sh"), "--print"], capture_output=True, check=True)
    agent = plistlib.loads(out.stdout)
    assert agent["Label"] == "com.studydesk.server"
    assert agent["ProgramArguments"] == [str(REPO / ".venv" / "bin" / "study-desk")]
    assert agent["RunAtLoad"] is True and agent["KeepAlive"] is True
    assert "/usr/bin" in agent["EnvironmentVariables"]["PATH"].split(":")
    assert agent["StandardOutPath"].endswith("Library/Logs/StudyDesk/server.log")


def test_print_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    subprocess.run([str(REPO / "scripts" / "install.sh"), "--print"], capture_output=True, check=True)
    assert not (tmp_path / "Library").exists()
