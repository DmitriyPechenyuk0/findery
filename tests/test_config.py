from pathlib import Path

import pytest
from pydantic import ValidationError

from findery.config import Settings


def make_settings(**overrides) -> Settings:
    """Build settings without reading the developer's real `.env` file."""
    return Settings(_env_file=None, **overrides)


def test_defaults():
    settings = make_settings()
    assert settings.log_level == "INFO"
    assert settings.db_path == Path("data") / "findery.sqlite3"


def test_reads_prefixed_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("FINDERY_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FINDERY_DATA_DIR", str(tmp_path))
    settings = make_settings()
    assert settings.log_level == "DEBUG"
    assert settings.db_path == tmp_path / "findery.sqlite3"


def test_rejects_unknown_log_level(monkeypatch):
    monkeypatch.setenv("FINDERY_LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        make_settings()
