from datetime import UTC, datetime
from decimal import Decimal

from findery.cli import build_parser, format_listing, format_place, format_price
from findery.models import Listing, Place, Price, Seller


def make_listing(**overrides) -> Listing:
    fields = {
        "source": "olx",
        "external_id": "1",
        "url": "https://www.olx.ua/d/uk/obyavlenie/x-ID1.html",
        "title": "PlayStation 5",
        "price": Price(amount=Decimal("18500"), currency="UAH", amount_uah=Decimal("18500")),
        "seller": Seller(id="7", is_business=False),
        "place": Place(city="Львів", district="Сихівський"),
        "refreshed_at": datetime(2026, 11, 11, 13, 44, tzinfo=UTC),
    }
    return Listing(**(fields | overrides))


def test_format_price_variants():
    assert format_price(make_listing()) == "18 500 UAH"
    assert format_price(make_listing(price=None)) == "без ціни"

    free = Price(amount=Decimal(0), currency="UAH", free=True)
    assert format_price(make_listing(price=free)) == "безкоштовно"

    usd = Price(
        amount=Decimal("9350"),
        currency="USD",
        amount_uah=Decimal("430140.205"),
        previous_amount=Decimal("9400"),
        negotiable=True,
    )
    assert format_price(make_listing(price=usd)) == "9 350 USD (≈ 430 140 UAH), було 9 400, торг"


def test_format_listing_has_price_title_place_and_link():
    text = format_listing(make_listing(promoted=True))

    assert text.splitlines()[0] == "18 500 UAH | PlayStation 5"
    assert "Львів, Сихівський · приватна особа · 11.11 13:44 · реклама" in text
    assert text.splitlines()[-1].strip() == "https://www.olx.ua/d/uk/obyavlenie/x-ID1.html"


def test_format_place_shows_ids():
    place = Place(city="Львів", city_id=176, region="Львівська область", region_id=5)
    assert format_place(place) == "Львів, Львівська область  [region_id=5 city_id=176]"


def test_parser_reads_search_options():
    args = build_parser().parse_args(
        ["search", "playstation 5", "--price-from", "10000", "--city-id", "176", "--private"]
    )
    assert args.command == "search"
    assert (args.text, args.price_from, args.price_to, args.city_id) == (
        "playstation 5",
        10000,
        None,
        176,
    )
    assert args.private
    assert args.pages == 1


def test_parser_without_command_runs_the_app():
    assert build_parser().parse_args([]).command is None
