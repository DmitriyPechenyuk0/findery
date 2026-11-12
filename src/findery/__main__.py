"""Entry point: `uv run findery` or `python -m findery`."""

import asyncio
import logging
import sys

from findery import __version__
from findery.cli import build_parser, run_command
from findery.config import Settings, load_settings
from findery.log import setup_logging

logger = logging.getLogger("findery")


async def run(settings: Settings) -> None:
    """Application lifecycle. The scheduler and the bot are started here in later steps."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("findery %s started, data dir: %s", __version__, settings.data_dir.resolve())
    logger.info("nothing to run yet, exiting")


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    setup_logging(settings.log_level)
    if args.command:
        sys.exit(asyncio.run(run_command(args, settings)))
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
