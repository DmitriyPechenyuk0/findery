"""Logging setup shared by every part of the application."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str) -> None:
    """Configure the root logger. Safe to call more than once."""
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT, force=True)
    # httpx logs every request at INFO; the sources log what matters themselves.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, logging.getLogger().level))
