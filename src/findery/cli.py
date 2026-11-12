"""Terminal commands for poking at the sources by hand."""

import argparse
from decimal import Decimal

from findery.config import Settings
from findery.models import Listing, Place, SearchQuery
from findery.sources.olx import OlxClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="findery", description="Search monitor for classifieds")
    commands = parser.add_subparsers(dest="command")

    search = commands.add_parser("search", help="search OLX and print the listings")
    search.add_argument("text", help='what to look for, e.g. "playstation 5"')
    search.add_argument("--price-from", type=int, metavar="UAH")
    search.add_argument("--price-to", type=int, metavar="UAH")
    search.add_argument("--region-id", type=int, help="see the `places` command")
    search.add_argument("--city-id", type=int, help="see the `places` command")
    search.add_argument("--category-id", type=int)
    search.add_argument("--private", action="store_true", help="private sellers only")
    search.add_argument("--pages", type=int, default=1, help="pages of 50 to fetch (default 1)")
    search.add_argument("--promoted", action="store_true", help="keep promoted listings")

    offer = commands.add_parser("offer", help="print one OLX listing by its ID")
    offer.add_argument("id")

    places = commands.add_parser("places", help="find OLX city and region IDs by name")
    places.add_argument("text")

    return parser


def _amount(value: Decimal) -> str:
    """18500 -> "18 500"."""
    return f"{value:,.0f}".replace(",", " ")


def format_price(listing: Listing) -> str:
    price = listing.price
    if price is None:
        return "без ціни"
    if price.free:
        return "безкоштовно"
    text = f"{_amount(price.amount)} {price.currency}"
    if price.currency != "UAH" and price.amount_uah is not None:
        text += f" (≈ {_amount(price.amount_uah)} UAH)"
    if price.previous_amount is not None:
        text += f", було {_amount(price.previous_amount)}"
    if price.negotiable:
        text += ", торг"
    return text


def format_listing(listing: Listing, *, full: bool = False) -> str:
    seller = listing.seller
    details = [
        listing.place.label(),
        "бізнес" if seller and seller.is_business else "приватна особа",
        f"{listing.refreshed_at:%d.%m %H:%M}" if listing.refreshed_at else "",
        "реклама" if listing.promoted else "",
    ]
    lines = [
        f"{format_price(listing)} | {listing.title}",
        "  " + " · ".join(part for part in details if part),
        f"  {listing.url}",
    ]
    if full:
        lines += [f"  {attr.name}: {attr.label}" for attr in listing.attributes.values()]
        lines += [f"  фото: {len(listing.photos)}", "", listing.description]
    return "\n".join(lines)


def format_place(place: Place) -> str:
    ids = [f"region_id={place.region_id}", f"city_id={place.city_id}"]
    if place.district_id is not None:
        ids.append(f"district_id={place.district_id}")
    name = ", ".join(part for part in (place.city, place.district, place.region) if part)
    return f"{name}  [{' '.join(ids)}]"


async def run_command(args: argparse.Namespace, settings: Settings) -> int:
    """Run a subcommand and return the process exit code."""
    async with OlxClient(user_agent=settings.user_agent) as olx:
        if args.command == "search":
            query = SearchQuery(
                text=args.text,
                price_from=args.price_from,
                price_to=args.price_to,
                region_id=args.region_id,
                city_id=args.city_id,
                category_id=args.category_id,
                private_only=args.private,
            )
            listings = await olx.search(query, max_pages=args.pages, include_promoted=args.promoted)
            print("\n\n".join(format_listing(listing) for listing in listings))
            print(f"\nЗнайдено: {len(listings)}")
        elif args.command == "offer":
            listing = await olx.get_listing(args.id)
            if listing is None:
                print(f"Оголошення {args.id} не знайдено")
                return 1
            print(format_listing(listing, full=True))
        elif args.command == "places":
            print("\n".join(format_place(place) for place in await olx.suggest_places(args.text)))
    return 0
