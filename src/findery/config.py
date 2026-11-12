"""Application settings, loaded from environment variables and the `.env` file."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
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

    # Search profiles are read from this file until they can be created in the bot.
    profiles_file: Path = Path("profiles.toml")
    # Token from @BotFather. Without it the app only polls and stores, with no alerts.
    telegram_bot_token: SecretStr | None = None
    # Your numeric Telegram ID (ask @userinfobot). The bot answers only this account
    # and sends it the alerts.
    telegram_user_id: int = 0
    # At most this many alerts are sent after one scheduler tick, this far apart.
    alerts_per_tick: int = 20
    alert_delay: float = 1.0

    # How often the scheduler looks for profiles whose time has come.
    tick_seconds: float = 60
    # A regular poll stops at the first page with nothing new, or after this many pages.
    poll_max_pages: int = 3
    # The first poll of a profile collects the market as it is: up to this many pages of 50.
    initial_max_pages: int = 20
    # Pause between pages of one poll, in seconds.
    page_delay: float = 1.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "findery.sqlite3"


def load_settings() -> Settings:
    return Settings()
