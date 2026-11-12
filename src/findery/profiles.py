"""Search profiles defined in a TOML file, mirrored into the database on start."""

import logging
import tomllib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from findery.db.tables import Profile, User

logger = logging.getLogger(__name__)


class ProfilesFileError(Exception):
    """The profiles file cannot be read or does not describe valid profiles."""


class ProfileConfig(BaseModel):
    # A typo in a key must be an error, not a silently ignored setting.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    query: str = Field(min_length=1)
    source: str = "olx"
    price_from: int | None = Field(default=None, ge=0)
    price_to: int | None = Field(default=None, ge=0)
    region_id: int | None = None
    city_id: int | None = None
    category_id: int | None = None
    private_only: bool = False
    stop_words: list[str] = []
    interval_minutes: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def price_range_is_ordered(self) -> "ProfileConfig":
        if None not in (self.price_from, self.price_to) and self.price_from > self.price_to:
            raise ValueError("price_from is greater than price_to")
        return self


class _ProfilesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[ProfileConfig] = []


def load_profiles_file(path: Path) -> list[ProfileConfig]:
    try:
        with path.open("rb") as file:
            configs = _ProfilesFile.model_validate(tomllib.load(file)).profiles
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ProfilesFileError(f"{path}: {error}") from error
    names = [config.name for config in configs]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ProfilesFileError(f"{path}: profile names repeat: {', '.join(sorted(duplicates))}")
    return configs


async def get_or_create_user(session: AsyncSession, telegram_id: int, now: datetime) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, created_at=now)
        session.add(user)
        await session.flush()
    return user


async def sync_profiles(
    session: AsyncSession, user: User, configs: list[ProfileConfig], now: datetime
) -> None:
    """Make the user's profiles match the file. Does not commit.

    Profiles are matched by name. A new one is due immediately; one that is no longer
    in the file is paused rather than deleted, so its history survives.
    """
    existing = {
        profile.name: profile
        for profile in await session.scalars(select(Profile).where(Profile.user_id == user.id))
    }
    for config in configs:
        fields = config.model_dump(exclude={"name"})
        profile = existing.pop(config.name, None)
        if profile is None:
            session.add(
                Profile(
                    user_id=user.id, name=config.name, created_at=now, next_run_at=now, **fields
                )
            )
            logger.info("profile %r: created", config.name)
            continue
        for key, value in fields.items():
            setattr(profile, key, value)
        if not profile.is_active:
            profile.is_active = True
            profile.next_run_at = now
            logger.info("profile %r: resumed", config.name)
    for profile in existing.values():
        if profile.is_active:
            profile.is_active = False
            logger.info("profile %r: paused, it is no longer in the profiles file", profile.name)
    await session.flush()
