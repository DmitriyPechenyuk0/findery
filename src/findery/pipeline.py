"""One poll of one profile: fetch, store, filter by rules, record the outcome."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from findery import rules
from findery.db.listings import SaveResult, save_listings
from findery.db.tables import ListingRow, Match, Profile
from findery.models import Listing, SearchQuery
from findery.sources import Source

logger = logging.getLogger(__name__)

# Values of `Match.stage`.
REJECTED = "rejected"
# Passed the rules during the first poll of a profile: part of the market as it was
# when the profile was created, not news worth an alert.
BASELINE = "baseline"
# Passed the rules and waits for the next stage (the LLM check, then the alert).
PASSED = "passed"

_ID_BATCH = 500


@dataclass
class RunStats:
    initial: bool = False
    pages: int = 0
    fetched: int = 0
    new: int = 0
    changed: int = 0
    # Listings this profile had not judged yet, plus re-checks after a price change.
    candidates: int = 0
    rejected_price: int = 0
    rejected_stop_word: int = 0
    passed: int = 0

    def summary(self) -> str:
        return (
            f"{'initial collection, ' if self.initial else ''}"
            f"fetched {self.fetched} in {self.pages} page(s): "
            f"{self.new} new, {self.changed} with a changed price or status; "
            f"checked {self.candidates}: "
            f"{self.rejected_price} outside the price range, "
            f"{self.rejected_stop_word} with a stop word, {self.passed} passed"
        )


def search_query(profile: Profile) -> SearchQuery:
    """The platform is asked without the price range: listings outside it are stored too,
    so that market statistics are not cut off by the range."""
    return SearchQuery(
        text=profile.query,
        region_id=profile.region_id,
        city_id=profile.city_id,
        category_id=profile.category_id,
        private_only=profile.private_only,
    )


async def _fetch_and_store(
    session: AsyncSession,
    profile: Profile,
    source: Source,
    now: datetime,
    *,
    max_pages: int,
    stop_when_nothing_new: bool,
    page_delay: float,
    stats: RunStats,
) -> SaveResult:
    query = search_query(profile)
    seen: set[str] = set()
    total = SaveResult()
    for page_number in range(max_pages):
        if page_number:
            await asyncio.sleep(page_delay)
        page = await source.search_page(query, offset=page_number * source.page_size)
        # Pages overlap and promoted listings repeat on each of them.
        fresh: list[Listing] = []
        for listing in page.listings:
            if not listing.promoted and listing.external_id not in seen:
                seen.add(listing.external_id)
                fresh.append(listing)
        saved = await save_listings(session, fresh, now=now)
        total.new += saved.new
        total.changed += saved.changed
        total.rows += saved.rows
        stats.pages += 1
        if not page.has_next or (stop_when_nothing_new and not saved.new):
            break
    stats.fetched = len(total.rows)
    stats.new = len(total.new)
    stats.changed = len(total.changed)
    return total


async def _matches(session: AsyncSession, profile: Profile, rows: list[ListingRow]) -> dict:
    ids = [row.id for row in rows]
    found: dict[int, Match] = {}
    for start in range(0, len(ids), _ID_BATCH):
        matches = await session.scalars(
            select(Match).where(
                Match.profile_id == profile.id,
                Match.listing_id.in_(ids[start : start + _ID_BATCH]),
            )
        )
        found.update({match.listing_id: match for match in matches})
    return found


def _judge(row: ListingRow, profile: Profile, pattern) -> str | None:
    """`None` if the listing passes the rules, otherwise the reason it is rejected."""
    reason = rules.check_price(row.price_uah, profile.price_from, profile.price_to)
    if reason:
        return reason
    word = rules.find_stop_word(row.title, pattern)
    return f"{rules.STOP_WORD}:{word}" if word else None


async def run_profile(
    session: AsyncSession,
    profile: Profile,
    source: Source,
    now: datetime,
    *,
    poll_max_pages: int = 3,
    initial_max_pages: int = 20,
    page_delay: float = 1.0,
) -> RunStats:
    """Poll the profile once and schedule its next poll. Does not commit."""
    stats = RunStats(initial=profile.last_run_at is None)
    saved = await _fetch_and_store(
        session,
        profile,
        source,
        now,
        max_pages=initial_max_pages if stats.initial else poll_max_pages,
        stop_when_nothing_new=not stats.initial,
        page_delay=page_delay,
        stats=stats,
    )

    matches = await _matches(session, profile, saved.rows)
    repriced = {change.row.id for change in saved.changed}
    pattern = rules.stop_word_pattern([*rules.DEFAULT_STOP_WORDS, *profile.stop_words])

    for row in saved.rows:
        match = matches.get(row.id)
        if match is not None:
            # Already judged. Only a rejection by price can be overturned, by a new price.
            recheck = (
                match.stage == REJECTED
                and match.reason in rules.PRICE_REASONS
                and row.id in repriced
            )
            if not recheck:
                continue
        stats.candidates += 1
        reason = _judge(row, profile, pattern)
        if reason in rules.PRICE_REASONS:
            stats.rejected_price += 1
        elif reason:
            stats.rejected_stop_word += 1
        else:
            stats.passed += 1
        stage = REJECTED if reason else (BASELINE if stats.initial else PASSED)
        if match is None:
            session.add(
                Match(
                    profile_id=profile.id,
                    listing_id=row.id,
                    stage=stage,
                    reason=reason,
                    created_at=now,
                )
            )
        else:
            match.stage, match.reason = stage, reason

    profile.last_run_at = now
    profile.next_run_at = now + timedelta(minutes=profile.interval_minutes)
    await session.flush()
    return stats
