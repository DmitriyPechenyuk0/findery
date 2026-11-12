import asyncio
import logging

from findery.__main__ import run
from findery.config import Settings


def test_run_creates_data_dir_and_exits(tmp_path, caplog):
    data_dir = tmp_path / "nested" / "data"
    settings = Settings(_env_file=None, data_dir=data_dir)

    with caplog.at_level(logging.INFO, logger="findery"):
        asyncio.run(run(settings))

    assert data_dir.is_dir()
    assert "started" in caplog.text
