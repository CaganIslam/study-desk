"""Configuration and the machine-local app directory.

The config file and the database live in the app directory, outside the data
root, because the data root may be synced by iCloud (ADR 0003).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "StudyDesk"
DEFAULT_PORT = 4620


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


def app_dir() -> Path:
    """Machine-local directory for config and database. STUDYDESK_HOME overrides it."""
    override = os.environ.get("STUDYDESK_HOME")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / APP_NAME


@dataclass(frozen=True)
class Config:
    data_root: Path | None = None
    language: str = "tr"
    port: int = DEFAULT_PORT
    moodle_url: str | None = None
    model_default: str | None = None
    model_live: str | None = None
    home: Path | None = None

    @property
    def app_home(self) -> Path:
        return self.home or app_dir()

    @property
    def database_path(self) -> Path:
        return self.app_home / "study.db"


def _get(table: dict, key: str, kind: type, where: str):
    value = table.get(key)
    if value is not None and not isinstance(value, kind):
        raise ConfigError(f"{where}{key} must be {kind.__name__}, got {type(value).__name__}")
    return value


def load_config(path: Path | None = None) -> Config:
    """Read config.toml from the app directory. A missing file means first run: defaults."""
    home = app_dir()
    path = path or home / "config.toml"
    if not path.exists():
        return Config(home=home)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    data_root = _get(raw, "data_root", str, "")
    moodle = _get(raw, "moodle", dict, "") or {}
    models = _get(raw, "models", dict, "") or {}
    port = _get(raw, "port", int, "")
    return Config(
        data_root=Path(data_root).expanduser() if data_root else None,
        language=_get(raw, "language", str, "") or "tr",
        port=port or DEFAULT_PORT,
        moodle_url=_get(moodle, "url", str, "moodle.") or None,
        model_default=_get(models, "default", str, "models.") or None,
        model_live=_get(models, "live", str, "models.") or None,
        home=home,
    )
