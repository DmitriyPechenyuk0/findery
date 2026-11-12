import asyncio
import logging

from sqlalchemy import select

from findery.__main__ import load_profiles, run
from findery.config import Settings
from findery.db.engine import create_engine, create_session_factory, migrate
from findery.db.tables import Profile, User

PROFILES = """
[[profiles]]
name = "PS5"
query = "playstation 5"
price_to = 20000
"""


def make_settings(tmp_path, **overrides) -> Settings:
    settings = Settings(
        _env_file=None, data_dir=tmp_path, profiles_file=tmp_path / "profiles.toml", **overrides
    )
    migrate(settings.db_path)
    return settings


def test_run_once_without_profiles_file_starts_and_exits(tmp_path, caplog):
    settings = make_settings(tmp_path)

    with caplog.at_level(logging.INFO, logger="findery"):
        asyncio.run(run(settings, once=True))

    assert "started" in caplog.text
    assert "no profiles file" in caplog.text


def test_load_profiles_mirrors_the_file_for_the_configured_user(tmp_path):
    settings = make_settings(tmp_path, telegram_user_id=42)
    settings.profiles_file.write_text(PROFILES, encoding="utf-8")

    async def scenario():
        engine = create_engine(settings.db_path)
        sessions = create_session_factory(engine)
        try:
            await load_profiles(settings, sessions)
            await load_profiles(settings, sessions)
            async with sessions() as session:
                users = (await session.scalars(select(User))).all()
                profiles = (await session.scalars(select(Profile))).all()
                return users, profiles
        finally:
            await engine.dispose()

    users, profiles = asyncio.run(scenario())
    assert [user.telegram_id for user in users] == [42]
    assert [(profile.name, profile.price_to) for profile in profiles] == [("PS5", 20000)]
