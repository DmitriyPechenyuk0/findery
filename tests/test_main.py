import asyncio
import logging

from findery.__main__ import run
from findery.config import Settings


def test_run_starts_and_exits(tmp_path, caplog):
    settings = Settings(_env_file=None, data_dir=tmp_path)

    with caplog.at_level(logging.INFO, logger="findery"):
        asyncio.run(run(settings))

    assert "started" in caplog.text
