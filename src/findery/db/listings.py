"""Storing listings and their price history."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from findery.db.tables import ListingRow, ListingSnapshot
from findery.models import Listing

# SQLite limits the number of bound parameters per statement; two are used per listing.
_LOOKUP_BATCH = 400


@dataclass(frozen=True)
class PriceChange:
    row: ListingRow
    old_amount: Decimal | None
    old_currency: str | None
    old_status: str


@dataclass
class SaveResult:
    new: list[ListingRow] = field(default_factory=list)
    changed: list[PriceChange] = field(default_factory=list)
    unchanged: int = 0
    # Every stored row touched by the call, each once, in the order first met.
    rows: list[ListingRow] = field(default_factory=list)


def _money(value: Decimal | None) -> Decimal | None:
    """Round the way the database stores it, so that a stored value compares equal."""
    return None if value is None else value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fields(listing: Listing) -> dict:
    """Everything about a listing that is refreshed on each sighting."""
    price, seller, place = listing.price, listing.seller, listing.place
    return {
        "url": listing.url,
        "title": listing.title,
        "description": listing.description,
        "status": listing.status,
        "price_amount": _money(price.amount) if price else None,
        "price_currency": price.currency if price else None,
        "price_uah": _money(price.amount_uah) if price else None,
        "price_negotiable": bool(price and price.negotiable),
        "price_free": bool(price and price.free),
        "seller_id": seller.id if seller else None,
        "seller_name": seller.name if seller else None,
        "seller_is_business": bool(seller and seller.is_business),
        "seller_registered_at": seller.registered_at if seller else None,
        "city_id": place.city_id,
        "city": place.city,
        "region_id": place.region_id,
        "region": place.region,
        "district_id": place.district_id,
        "district": place.district,
        "lat": place.lat,
        "lon": place.lon,
        "category_id": listing.category_id,
        "category_type": listing.category_type,
        "photos": list(listing.photos),
        "attributes": {key: attr.model_dump() for key, attr in listing.attributes.items()},
        "created_at": listing.created_at,
        "refreshed_at": listing.refreshed_at,
        "valid_to": listing.valid_to,
    }


def _snapshot(row: ListingRow, seen_at: datetime) -> ListingSnapshot:
    return ListingSnapshot(
        seen_at=seen_at,
        status=row.status,
        price_amount=row.price_amount,
        price_currency=row.price_currency,
        price_uah=row.price_uah,
    )


async def _existing(
    session: AsyncSession, listings: list[Listing]
) -> dict[tuple[str, str], ListingRow]:
    keys = [(item.source, item.external_id) for item in listings]
    rows: dict[tuple[str, str], ListingRow] = {}
    for start in range(0, len(keys), _LOOKUP_BATCH):
        batch = keys[start : start + _LOOKUP_BATCH]
        found = await session.scalars(
            select(ListingRow).where(tuple_(ListingRow.source, ListingRow.external_id).in_(batch))
        )
        rows.update({(row.source, row.external_id): row for row in found})
    return rows


async def save_listings(
    session: AsyncSession, listings: list[Listing], *, now: datetime | None = None
) -> SaveResult:
    """Insert new listings and refresh known ones. Does not commit.

    A history row is written for every new listing and whenever the price or the
    status of a known one differs from what is stored.
    """
    now = now or datetime.now(UTC)
    result = SaveResult()
    rows = await _existing(session, listings)
    snapshots: list[tuple[ListingRow, ListingSnapshot]] = []

    for listing in listings:
        key = (listing.source, listing.external_id)
        fields = _fields(listing)
        row = rows.get(key)
        if row is None:
            row = ListingRow(
                source=listing.source,
                external_id=listing.external_id,
                first_seen_at=now,
                last_seen_at=now,
                **fields,
            )
            session.add(row)
            # Also guards against the same listing appearing twice in `listings`.
            rows[key] = row
            result.new.append(row)
            snapshots.append((row, _snapshot(row, now)))
            continue

        old = (row.price_amount, row.price_currency, row.status)
        for name, value in fields.items():
            setattr(row, name, value)
        row.last_seen_at = now
        if old == (row.price_amount, row.price_currency, row.status):
            result.unchanged += 1
        else:
            result.changed.append(PriceChange(row, *old))
            snapshots.append((row, _snapshot(row, now)))

    # New rows get their IDs here; snapshots need them.
    await session.flush()
    for row, snapshot in snapshots:
        snapshot.listing_id = row.id
        session.add(snapshot)
    await session.flush()
    result.rows = list(rows.values())
    return result
