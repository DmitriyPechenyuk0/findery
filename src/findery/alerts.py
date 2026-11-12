"""Listings that passed every check of a profile and have not been sent to its owner yet."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from findery.db.tables import ListingRow, Match, Profile, User
from findery.pipeline import PASSED


@dataclass(frozen=True)
class Alert:
    match_id: int
    listing: ListingRow
    profile_name: str
    telegram_id: int


async def pending_alerts(session: AsyncSession, limit: int) -> list[Alert]:
    """Oldest first. Alerts of paused profiles wait until the profile is resumed."""
    rows = await session.execute(
        select(Match.id, ListingRow, Profile.name, User.telegram_id)
        .join(ListingRow, ListingRow.id == Match.listing_id)
        .join(Profile, Profile.id == Match.profile_id)
        .join(User, User.id == Profile.user_id)
        .where(Match.stage == PASSED, Match.sent_at.is_(None), Profile.is_active)
        .order_by(Match.id)
        .limit(limit)
    )
    return [Alert(*row) for row in rows]


async def mark_sent(session: AsyncSession, match_id: int, now: datetime) -> None:
    match = await session.get(Match, match_id)
    if match is not None:
        match.sent_at = now
