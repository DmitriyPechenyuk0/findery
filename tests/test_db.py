import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError

from findery.db.engine import create_engine, create_session_factory, migrate
from findery.db.listings import save_listings
from findery.db.tables import Base, ListingRow, ListingSnapshot, Profile, User
from findery.models import Attribute, Listing, Place, Price, Seller

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
KYIV = timezone(timedelta(hours=2))


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "findery.sqlite3"
    migrate(path)
    return path


def run(db_path, scenario):
    """Run `scenario(session)` in one committed transaction on a fresh engine."""

    async def main():
        engine = create_engine(db_path)
        try:
            async with create_session_factory(engine).begin() as session:
                return await scenario(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def make_listing(external_id="1", amount="18500", **overrides) -> Listing:
    fields = {
        "source": "olx",
        "external_id": external_id,
        "url": f"https://www.olx.ua/d/uk/obyavlenie/x-ID{external_id}.html",
        "title": "PlayStation 5",
        "description": "Стан ідеальний",
        "price": Price(amount=Decimal(amount), currency="UAH", amount_uah=Decimal(amount)),
        "seller": Seller(id="7", name="Продавець", registered_at=T0 - timedelta(days=900)),
        "place": Place(city="Львів", city_id=176, region="Львівська область", region_id=5),
        "created_at": datetime(2026, 11, 11, 20, 0, tzinfo=KYIV),
        "photos": ["https://example.com/1.jpg"],
        "attributes": {"state": Attribute(name="Стан", value="used", label="Вживане")},
    }
    return Listing(**(fields | overrides))


def counts(db_path) -> tuple[int, int]:
    async def scenario(session):
        listings = await session.scalar(select(func.count()).select_from(ListingRow))
        snapshots = await session.scalar(select(func.count()).select_from(ListingSnapshot))
        return listings, snapshots

    return run(db_path, scenario)


def save(db_path, listings, now=T0):
    return run(db_path, lambda session: save_listings(session, listings, now=now))


def test_migration_creates_schema_that_matches_the_models(db_path):
    engine = create_sync_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_migrate_is_repeatable(db_path):
    migrate(db_path)
    assert counts(db_path) == (0, 0)


def test_database_uses_wal_and_enforces_foreign_keys(db_path):
    async def orphan_profile(session):
        session.add(
            Profile(user_id=999, name="x", source="olx", query="x", stop_words=[], created_at=T0)
        )

    with pytest.raises(IntegrityError):
        run(db_path, orphan_profile)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_new_listing_is_stored_with_first_snapshot(db_path):
    result = save(db_path, [make_listing()])

    assert len(result.new) == 1
    assert (len(result.changed), result.unchanged) == (0, 0)
    assert counts(db_path) == (1, 1)

    async def load(session):
        return (await session.scalars(select(ListingRow))).one()

    row = run(db_path, load)
    assert row.external_id == "1"
    assert row.price_amount == Decimal("18500")
    assert row.price_uah == Decimal("18500")
    assert row.city == "Львів"
    assert row.seller_id == "7"
    assert row.photos == ["https://example.com/1.jpg"]
    assert row.attributes["state"]["label"] == "Вживане"
    assert row.first_seen_at == row.last_seen_at == T0
    # Stored in UTC, read back as the same moment with a timezone.
    assert row.created_at == datetime(2026, 11, 11, 18, 0, tzinfo=UTC)
    assert row.created_at.tzinfo is not None


def test_second_run_creates_no_duplicates(db_path):
    listings = [make_listing("1"), make_listing("2", "9000")]
    save(db_path, listings)

    later = T0 + timedelta(minutes=30)
    result = save(db_path, listings, now=later)

    assert (len(result.new), len(result.changed), result.unchanged) == (0, 0, 2)
    assert counts(db_path) == (2, 2)

    async def seen(session):
        rows = await session.execute(select(ListingRow.first_seen_at, ListingRow.last_seen_at))
        return {tuple(row) for row in rows}

    assert run(db_path, seen) == {(T0, later)}


def test_price_change_adds_a_history_row(db_path):
    save(db_path, [make_listing(amount="18500")])
    later = T0 + timedelta(hours=1)

    result = save(db_path, [make_listing(amount="17000")], now=later)

    assert len(result.changed) == 1
    change = result.changed[0]
    assert change.old_amount == Decimal("18500")
    assert change.row.price_amount == Decimal("17000")
    assert counts(db_path) == (1, 2)

    async def history(session):
        rows = await session.execute(
            select(ListingSnapshot.seen_at, ListingSnapshot.price_amount).order_by(
                ListingSnapshot.id
            )
        )
        return [tuple(row) for row in rows]

    assert run(db_path, history) == [(T0, Decimal("18500")), (later, Decimal("17000"))]


def test_status_change_adds_a_history_row(db_path):
    save(db_path, [make_listing()])
    result = save(db_path, [make_listing(status="removed_by_user")])

    assert result.changed[0].old_status == "active"
    assert counts(db_path) == (1, 2)


def test_other_edits_update_the_row_without_history(db_path):
    save(db_path, [make_listing()])
    result = save(db_path, [make_listing(title="PlayStation 5 Slim")])

    assert result.unchanged == 1
    assert counts(db_path) == (1, 1)

    async def title(session):
        return await session.scalar(select(ListingRow.title))

    assert run(db_path, title) == "PlayStation 5 Slim"


def test_fractional_and_missing_prices(db_path):
    usd = Price(amount=Decimal("9350"), currency="USD", amount_uah=Decimal("430140.205"))
    listings = [make_listing("1", price=usd), make_listing("2", price=None)]
    save(db_path, listings)

    # The converted amount is rounded on storage; that alone must not look like a change.
    result = save(db_path, listings)
    assert result.unchanged == 2

    async def prices(session):
        rows = await session.execute(
            select(ListingRow.price_amount, ListingRow.price_uah).order_by(ListingRow.external_id)
        )
        return [tuple(row) for row in rows]

    assert run(db_path, prices) == [(Decimal("9350"), Decimal("430140.21")), (None, None)]


def test_same_listing_twice_in_one_batch_is_stored_once(db_path):
    result = save(db_path, [make_listing("1"), make_listing("1")])

    assert len(result.new) == 1
    assert counts(db_path) == (1, 1)


def test_same_external_id_on_another_source_is_a_different_listing(db_path):
    save(db_path, [make_listing("1"), make_listing("1", source="lun")])
    assert counts(db_path) == (2, 2)


def test_many_listings_in_one_call(db_path):
    listings = [make_listing(str(number)) for number in range(1200)]
    save(db_path, listings)
    result = save(db_path, listings)

    assert result.unchanged == 1200
    assert counts(db_path) == (1200, 1200)


def test_naive_datetime_is_rejected(db_path):
    async def scenario(session):
        session.add(User(telegram_id=1, created_at=datetime(2026, 1, 1)))

    with pytest.raises(StatementError, match="naive datetime"):
        run(db_path, scenario)
