import pytest

from studydesk.config import DEFAULT_PORT, ConfigError, load_config


def test_missing_file_means_first_run_defaults(home):
    config = load_config()
    assert config.data_root is None
    assert config.port == DEFAULT_PORT
    assert config.database_path == home / "study.db"


def test_values_are_read_and_paths_expanded(home):
    home.mkdir(parents=True)
    (home / "config.toml").write_text(
        'data_root = "~/Courses"\n'
        'language = "en"\n'
        "port = 5000\n"
        "[moodle]\n"
        'url = "https://moodle.example.edu"\n'
        "[models]\n"
        'live = "fast-model"\n'
    )
    config = load_config()
    assert config.data_root is not None and not str(config.data_root).startswith("~")
    assert config.data_root.name == "Courses"
    assert (config.language, config.port) == ("en", 5000)
    assert config.moodle_url == "https://moodle.example.edu"
    assert (config.model_default, config.model_live) == (None, "fast-model")


def test_wrong_type_is_reported(home):
    home.mkdir(parents=True)
    (home / "config.toml").write_text('port = "4620"\n')
    with pytest.raises(ConfigError, match="port"):
        load_config()


def test_broken_toml_is_reported(home):
    home.mkdir(parents=True)
    (home / "config.toml").write_text("data_root = \n")
    with pytest.raises(ConfigError):
        load_config()
