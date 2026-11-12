import os

import pytest

from findery.db.engine import migrate


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Tests must not depend on FINDERY_* variables set in the developer's shell."""
    for name in os.environ:
        if name.startswith("FINDERY_"):
            monkeypatch.delenv(name)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "findery.sqlite3"
    migrate(path)
    return path
