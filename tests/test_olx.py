"""OLX client against responses saved from the real API (seller data anonymised)."""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from findery.models import SearchQuery
from findery.sources.olx import OlxBlockedError, OlxClient, OlxError, OlxFormatError

FIXTURES = Path(__file__).parent / "fixtures" / "olx"

Handler = Callable[[httpx.Request], httpx.Response]


def fixture(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=(FIXTURES / name).read_bytes())


def call(handler: Handler, method: str, *args, **kwargs):
    """Run one client method against a fake server and return its result."""

    async def scenario():
        client = OlxClient(transport=httpx.MockTransport(handler), retry_delay=0, page_delay=0)
        async with client:
            return await getattr(client, method)(*args, **kwargs)

    return asyncio.run(scenario())


def paged(request: httpx.Request) -> httpx.Response:
    offset = int(request.url.params["offset"])
    return fixture("search_page1.json" if offset == 0 else "search_page2.json")


QUERY = SearchQuery(text="iphone")


def test_search_page_marks_promoted_and_reads_totals():
    page = call(paged, "search_page", QUERY)

    assert [item.promoted for item in page.listings] == [True, False, False, False, False]
    assert page.total == 1000
    assert page.matched > page.total
    assert page.has_next


def test_search_sends_filters():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["user-agent"] = request.headers["user-agent"]
        return fixture("search_empty.json")

    query = SearchQuery(
        text="playstation 5", price_from=10000, price_to=20000, city_id=176, private_only=True
    )
    assert call(handler, "search", query) == []
    assert seen["query"] == "playstation 5"
    assert seen["filter_float_price:from"] == "10000"
    assert seen["filter_float_price:to"] == "20000"
    assert seen["city_id"] == "176"
    assert seen["owner_type"] == "private"
    assert seen["limit"] == "50"
    assert "region_id" not in seen
    assert seen["user-agent"].startswith("findery/")


def test_search_follows_pages_drops_promoted_and_duplicates():
    listings = call(paged, "search", QUERY, max_pages=5)

    ids = [item.external_id for item in listings]
    # Page 1 has one promoted and four regular listings; page 2 repeats one and adds one.
    assert len(ids) == len(set(ids)) == 5
    assert not any(item.promoted for item in listings)


def test_search_stops_at_max_pages_and_can_keep_promoted():
    listings = call(paged, "search", QUERY, max_pages=1, include_promoted=True)

    assert len(listings) == 5
    assert listings[0].promoted


def test_listing_fields():
    listing = call(paged, "search", QUERY)[0]

    assert listing.source == "olx"
    assert listing.external_id == "940628139"
    assert listing.url.startswith("https://www.olx.ua/")
    assert listing.title == "Чохли на iPhone 17-18 pro max"
    assert listing.status == "active"
    assert listing.price.amount == Decimal("300")
    assert listing.price.amount_uah == Decimal("300")
    assert listing.price.previous_amount == Decimal("930")
    assert listing.price.currency == "UAH"
    assert not listing.price.free
    assert listing.place.city == "Луцьк"
    assert listing.place.region_id is not None
    assert listing.place.lat is not None
    assert listing.seller.id == "1000001"
    assert not listing.seller.is_business
    assert listing.seller.registered_at is not None
    assert listing.created_at.utcoffset() is not None
    assert listing.refreshed_at >= listing.created_at
    assert listing.category_type == "electronics"
    assert listing.attributes["state"].label
    assert "<br" not in listing.description
    assert all("{" not in url and url.startswith("https://") for url in listing.photos)
    assert len(listing.photos) == 2


def test_price_variants():
    by_id = {item.external_id: item for item in call(paged, "search", QUERY, max_pages=2)}

    free = by_id["940599366"].price
    assert free.free
    assert free.amount == 0

    # A service listing without any price field.
    assert by_id["593244585"].price is None

    usd = by_id["935474841"].price
    assert usd.currency == "USD"
    assert usd.amount == Decimal("9350")
    assert usd.amount_uah == Decimal("430140.205")
    assert usd.previous_amount == Decimal("9400")
    assert usd.negotiable


def test_multi_choice_attribute_keeps_every_value():
    by_id = {item.external_id: item for item in call(paged, "search", QUERY)}
    lists = [
        attr.value
        for attr in by_id["940611327"].attributes.values()
        if isinstance(attr.value, list)
    ]
    assert lists
    assert all(len(values) >= 1 for values in lists)


def test_get_listing():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return fixture("offer.json")

    listing = call(handler, "get_listing", 940638579)

    assert seen == ["/api/v1/offers/940638579/"]
    assert listing.external_id == "940638579"
    assert not listing.promoted
    assert listing.price is not None


def test_get_listing_returns_none_when_removed():
    assert call(lambda _: fixture("offer_not_found.json", 404), "get_listing", 700000001) is None


def test_suggest_places():
    places = call(lambda _: fixture("locations.json"), "suggest_places", "льв")

    assert places[0].city == "Львів"
    assert places[0].city_id == 176
    assert places[0].region_id == 5
    assert places[0].district is None
    assert places[0].lat is not None
    assert places[1].district_id == 127
    assert places[1].label() == "Львів, Галицький"


def test_blocked_request_raises():
    with pytest.raises(OlxBlockedError):
        call(lambda _: httpx.Response(403, text="Request blocked."), "search", QUERY)


def test_rejected_request_raises_with_details():
    with pytest.raises(OlxError, match="between 0 and 50"):
        call(lambda _: fixture("error_validation.json", 400), "search", QUERY)


def test_changed_response_format_raises():
    with pytest.raises(OlxFormatError):
        call(lambda _: httpx.Response(200, json={"data": [{"id": 1}]}), "search", QUERY)


def test_retries_temporary_failures():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("no route")
        if len(attempts) == 2:
            return httpx.Response(503)
        return fixture("search_empty.json")

    assert call(handler, "search", QUERY) == []
    assert len(attempts) == 3


def test_gives_up_after_all_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(OlxError, match="unreachable"):
        call(handler, "search", QUERY)
