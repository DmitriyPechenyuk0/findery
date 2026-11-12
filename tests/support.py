"""Helpers shared by the tests."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from findery.db.engine import create_engine, create_session_factory
from findery.models import Attribute, Listing, Place, Price, SearchQuery, Seller

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
KYIV = timezone(timedelta(hours=2))


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


@dataclass
class FakePage:
    listings: list[Listing]
    has_next: bool


@dataclass
class FakeSource:
    """A platform that serves `listings` in pages of `page_size` and records the requests."""

    listings: list[Listing] = field(default_factory=list)
    page_size: int = 50
    error: Exception | None = None
    requests: list[tuple[SearchQuery, int]] = field(default_factory=list)

    async def search_page(self, query: SearchQuery, *, offset: int = 0) -> FakePage:
        self.requests.append((query, offset))
        if self.error:
            raise self.error
        end = offset + self.page_size
        return FakePage(self.listings[offset:end], has_next=end < len(self.listings))
