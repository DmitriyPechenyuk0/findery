"""Runs each active profile when its `next_run_at` comes.

The schedule lives in the database, so it survives restarts: a profile that became
due while the app was down is polled on the next start.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from findery.config import Settings
from findery.db.engine import SessionFactory
from findery.db.tables import Profile
from findery.pipeline import run_profile
from findery.sources import Source

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


async def due_profile_ids(sessions: SessionFactory, now: datetime) -> list[int]:
    async with sessions() as session:
        due = await session.scalars(
            select(Profile.id)
            .where(
                Profile.is_active, or_(Profile.next_run_at.is_(None), Profile.next_run_at <= now)
            )
            .order_by(Profile.next_run_at)
        )
        return list(due)


async def _postpone(sessions: SessionFactory, profile_id: int, now: datetime) -> None:
    """After a failed poll: try again after the usual interval instead of every tick."""
    async with sessions.begin() as session:
        profile = await session.get(Profile, profile_id)
        if profile is not None:
            profile.next_run_at = now + timedelta(minutes=profile.interval_minutes)


async def run_due_profiles(
    sessions: SessionFactory,
    sources: Mapping[str, Source],
    settings: Settings,
    now: datetime,
) -> int:
    """Poll every profile that is due, one after another. Returns how many succeeded.

    A failure of one profile is logged and does not stop the others.
    """
    succeeded = 0
    for profile_id in await due_profile_ids(sessions, now):
        name = f"#{profile_id}"
        try:
            async with sessions.begin() as session:
                profile = await session.get(Profile, profile_id)
                if profile is None or not profile.is_active:
                    continue
                name = repr(profile.name)
                source = sources.get(profile.source)
                if source is None:
                    raise LookupError(f"unknown source {profile.source!r}")
                stats = await run_profile(
                    session,
                    profile,
                    source,
                    now,
                    poll_max_pages=settings.poll_max_pages,
                    initial_max_pages=settings.initial_max_pages,
                    page_delay=settings.page_delay,
                )
        except Exception:
            logger.exception("profile %s: poll failed, nothing was saved", name)
            await _postpone(sessions, profile_id, now)
        else:
            succeeded += 1
            logger.info("profile %s: %s", name, stats.summary())
    return succeeded


async def run_forever(
    sessions: SessionFactory,
    sources: Mapping[str, Source],
    settings: Settings,
    *,
    clock: Clock = utc_now,
    after_tick: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Check for due profiles every `tick_seconds` until the task is cancelled.

    `after_tick` runs after each check; it is where alerts are sent.
    """
    while True:
        await run_due_profiles(sessions, sources, settings, clock())
        if after_tick is not None:
            try:
                await after_tick()
            except Exception:
                logger.exception("the step after the poll failed")
        await asyncio.sleep(settings.tick_seconds)
