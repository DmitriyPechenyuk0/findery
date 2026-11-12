import os

import pytest


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Tests must not depend on FINDERY_* variables set in the developer's shell."""
    for name in os.environ:
        if name.startswith("FINDERY_"):
            monkeypatch.delenv(name)
