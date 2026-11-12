import asyncio
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from findery.config import Settings
from findery.db.engine import create_engine, create_session_factory
from findery.db.tables import ListingRow, Profile
from findery.profiles import ProfileConfig, get_or_create_user, sync_profiles
from findery.scheduler import run_due_profiles, run_forever
from findery.sources.olx import OlxError
from support import T0, FakeSource, make_listing

SETTINGS = Settings(_env_file=None, page_delay=0, tick_seconds=0)


def with_database(db_path, scenario):
    """Run `scenario(sessions)` with a session factory on a fresh engine."""

    async def main():
        engine = create_engine(db_path)
        try:
            return await scenario(create_session_factory(engine))
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def add_profiles(sessions, *configs: ProfileConfig) -> None:
    async with sessions.begin() as session:
        user = await get_or_create_user(session, 1, T0)
        await sync_profiles(session, user, list(configs), T0)


async def schedule(sessions) -> dict[str, tuple]:
    async with sessions() as session:
        profiles = await session.scalars(select(Profile))
        return {p.name: (p.last_run_at, p.next_run_at) for p in profiles}


async def listing_count(sessions) -> int:
    async with sessions() as session:
        return len((await session.scalars(select(ListingRow))).all())


def config(name: str, **overrides) -> ProfileConfig:
    return ProfileConfig(**({"name": name, "query": name, "interval_minutes": 30} | overrides))


def test_runs_a_profile_only_when_it_is_due(db_path, caplog):
    source = FakeSource([make_listing("1")])

    async def scenario(sessions):
        await add_profiles(sessions, config("ps5"))
        counts = []
        for minutes in (0, 10, 29, 30, 31):
            now = T0 + timedelta(minutes=minutes)
            counts.append(await run_due_profiles(sessions, {"olx": source}, SETTINGS, now))
        return counts, await schedule(sessions)

    with caplog.at_level(logging.INFO, logger="findery.scheduler"):
        counts, result = with_database(db_path, scenario)

    assert counts == [1, 0, 0, 1, 0]
    assert result == {"ps5": (T0 + timedelta(minutes=30), T0 + timedelta(minutes=60))}
    assert "profile 'ps5': initial collection, fetched 1 in 1 page(s): 1 new" in caplog.text
    assert "1 passed" in caplog.text


def test_paused_profile_is_not_run(db_path):
    source = FakeSource([make_listing("1")])

    async def scenario(sessions):
        await add_profiles(sessions, config("ps5"))
        async with sessions.begin() as session:
            (await session.scalars(select(Profile))).one().is_active = False
        return await run_due_profiles(sessions, {"olx": source}, SETTINGS, T0)

    assert with_database(db_path, scenario) == 0
    assert source.requests == []


def test_failed_poll_saves_nothing_is_postponed_and_does_not_stop_others(db_path, caplog):
    broken = FakeSource([make_listing("1")], error=OlxError("OLX is unreachable"))
    working = FakeSource([make_listing("2", source="lun")])
    sources = {"olx": broken, "lun": working}

    async def scenario(sessions):
        await add_profiles(sessions, config("a"), config("b", source="lun"))
        first = await run_due_profiles(sessions, sources, SETTINGS, T0)
        retried_early = await run_due_profiles(sessions, sources, SETTINGS, T0)
        broken.error = None
        later = T0 + timedelta(minutes=30)
        second = await run_due_profiles(sessions, sources, SETTINGS, later)
        return first, retried_early, second, await schedule(sessions), await listing_count(sessions)

    with caplog.at_level(logging.ERROR, logger="findery.scheduler"):
        first, retried_early, second, result, listings = with_database(db_path, scenario)

    assert (first, retried_early, second) == (1, 0, 2)
    assert "profile 'a': poll failed" in caplog.text
    assert "OLX is unreachable" in caplog.text
    # The failed poll left no `last_run_at`, so the retry was still an initial collection.
    assert result["a"][0] == T0 + timedelta(minutes=30)
    assert listings == 2


def test_profile_with_unknown_source_fails_without_breaking_the_run(db_path, caplog):
    async def scenario(sessions):
        await add_profiles(sessions, config("a", source="ebay"))
        return await run_due_profiles(sessions, {"olx": FakeSource()}, SETTINGS, T0)

    with caplog.at_level(logging.ERROR, logger="findery.scheduler"):
        assert with_database(db_path, scenario) == 0
    assert "unknown source 'ebay'" in caplog.text


def test_run_forever_ticks_until_cancelled(db_path):
    source = FakeSource([make_listing("1")])
    times = iter(T0 + timedelta(minutes=30 * n) for n in range(1000))

    async def scenario(sessions):
        await add_profiles(sessions, config("ps5"))
        task = asyncio.create_task(
            run_forever(sessions, {"olx": source}, SETTINGS, clock=lambda: next(times))
        )
        while len(source.requests) < 3:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return await listing_count(sessions)

    assert with_database(db_path, scenario) == 1
    assert len(source.requests) >= 3
