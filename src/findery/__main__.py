"""Entry point: `uv run findery` or `python -m findery`."""

import asyncio
import logging

from findery import __version__
from findery.config import Settings, load_settings
from findery.log import setup_logging

logger = logging.getLogger("findery")


async def run(settings: Settings) -> None:
    """Application lifecycle. The scheduler and the bot are started here in later steps."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("findery %s started, data dir: %s", __version__, settings.data_dir.resolve())
    logger.info("nothing to run yet, exiting")


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
