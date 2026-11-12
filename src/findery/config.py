"""Application settings, loaded from environment variables and the `.env` file."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from findery import __version__

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Every setting is read from a `FINDERY_`-prefixed variable, e.g. `FINDERY_LOG_LEVEL`."""

    model_config = SettingsConfigDict(
        env_prefix="FINDERY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: LogLevel = "INFO"
    data_dir: Path = Path("data")
    # How the app introduces itself to the platforms it queries.
    user_agent: str = f"findery/{__version__}"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "findery.sqlite3"


def load_settings() -> Settings:
    return Settings()
