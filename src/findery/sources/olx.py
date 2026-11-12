"""Client for the JSON API behind olx.ua.

The API is unofficial and may change without notice, so everything that knows its
shape lives in this module. A response that no longer matches raises `OlxFormatError`.
"""

import asyncio
import html
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from findery import __version__
from findery.models import Attribute, Listing, Place, Price, SearchQuery, Seller

logger = logging.getLogger(__name__)

SOURCE = "olx"
BASE_URL = "https://www.olx.ua/api/v1"
DEFAULT_USER_AGENT = f"findery/{__version__}"
# The API rejects a larger page with HTTP 400.
MAX_PAGE_SIZE = 50
# The API never returns results past this offset, however many listings match.
MAX_RESULTS = 1000

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_BR = re.compile(r"<br\s*/?>[ \t]*\n?", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class OlxError(Exception):
    """The request failed and repeating it as is will not help."""


class OlxBlockedError(OlxError):
    """OLX refused the request (HTTP 403), usually because of the client or its IP."""


class OlxFormatError(OlxError):
    """The response does not look like what this client was written against."""


class SearchPage(BaseModel):
    listings: list[Listing]
    # How many results the API is willing to page through (capped at `MAX_RESULTS`).
    total: int
    # How many listings really match the query.
    matched: int
    has_next: bool


# --- Shape of the raw API responses. Unknown fields are ignored. ---


class _RawParam(BaseModel):
    key: str
    name: str = ""
    type: str = ""
    value: Any = None


class _RawUser(BaseModel):
    id: int
    name: str | None = None
    created: datetime | None = None


class _RawNamed(BaseModel):
    id: int | None = None
    name: str | None = None
    lat: float | None = None
    lon: float | None = None


class _RawLocation(BaseModel):
    city: _RawNamed | None = None
    region: _RawNamed | None = None
    district: _RawNamed | None = None


class _RawMap(BaseModel):
    lat: float | None = None
    lon: float | None = None


class _RawPhoto(BaseModel):
    link: str
    width: int = 0
    height: int = 0


class _RawCategory(BaseModel):
    id: int | None = None
    type: str | None = None


class _RawOffer(BaseModel):
    id: int
    url: str
    title: str
    description: str = ""
    status: str = "active"
    params: list[_RawParam] = []
    business: bool = False
    user: _RawUser | None = None
    location: _RawLocation | None = None
    map: _RawMap | None = None
    photos: list[_RawPhoto] = []
    category: _RawCategory | None = None
    created_time: datetime | None = None
    last_refresh_time: datetime | None = None
    valid_to_time: datetime | None = None


class _RawSource(BaseModel):
    promoted: list[int] = []


class _RawMetadata(BaseModel):
    total_elements: int = 0
    visible_total_count: int = 0
    source: _RawSource = _RawSource()


class _RawSearch(BaseModel):
    data: list[_RawOffer]
    metadata: _RawMetadata = _RawMetadata()
    links: dict[str, Any] = {}


class _RawOfferResponse(BaseModel):
    data: _RawOffer


class _RawLocations(BaseModel):
    data: list[_RawLocation]


# --- Conversion to the common models ---


def _clean_text(text: str) -> str:
    """Descriptions come as HTML fragments: `<br />` line breaks and escaped entities."""
    text = _BR.sub("\n", text)
    text = _TAG.sub("", text)
    return html.unescape(text).strip()


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _price(params: list[_RawParam]) -> Price | None:
    raw = next((p.value for p in params if p.type == "price"), None)
    if not isinstance(raw, dict) or raw.get("value") is None:
        return None
    amount = Decimal(str(raw["value"]))
    currency = raw.get("currency") or "UAH"
    if currency == "UAH":
        amount_uah = amount
    elif raw.get("converted_currency") == "UAH":
        amount_uah = _decimal(raw.get("converted_value"))
    else:
        amount_uah = None
    return Price(
        amount=amount,
        currency=currency,
        amount_uah=amount_uah,
        previous_amount=_decimal(raw.get("previous_value")),
        negotiable=bool(raw.get("negotiable")),
        free=raw.get("type") == "free",
    )


def _attributes(params: list[_RawParam]) -> dict[str, Attribute]:
    result = {}
    for param in params:
        if param.type == "price" or not isinstance(param.value, dict):
            continue
        key = param.value.get("key")
        if isinstance(key, list):
            value = [str(item) for item in key]
        else:
            value = None if key is None else str(key)
        result[param.key] = Attribute(name=param.name, value=value, label=param.value.get("label"))
    return result


def _place(location: _RawLocation | None, point: _RawMap | None = None) -> Place:
    location = location or _RawLocation()
    city, region, district = location.city, location.region, location.district
    # Search results carry coordinates in `map`, location suggestions in the city itself.
    lat = point.lat if point else (city.lat if city else None)
    lon = point.lon if point else (city.lon if city else None)
    return Place(
        city_id=city.id if city else None,
        city=city.name if city else None,
        region_id=region.id if region else None,
        region=region.name if region else None,
        district_id=district.id if district else None,
        district=district.name if district else None,
        lat=lat,
        lon=lon,
    )


def _photo_url(photo: _RawPhoto) -> str:
    # The link is a template: ".../image;s={width}x{height}".
    size = f"{photo.width}x{photo.height}"
    return photo.link.replace("{width}x{height}", size).replace(":443/", "/")


def _listing(offer: _RawOffer, *, promoted: bool = False) -> Listing:
    seller = None
    if offer.user:
        seller = Seller(
            id=str(offer.user.id),
            name=offer.user.name,
            is_business=offer.business,
            registered_at=offer.user.created,
        )
    category = offer.category or _RawCategory()
    return Listing(
        source=SOURCE,
        external_id=str(offer.id),
        url=offer.url,
        title=offer.title.strip(),
        description=_clean_text(offer.description),
        status=offer.status,
        price=_price(offer.params),
        seller=seller,
        place=_place(offer.location, offer.map),
        category_id=category.id,
        category_type=category.type,
        created_at=offer.created_time,
        refreshed_at=offer.last_refresh_time,
        valid_to=offer.valid_to_time,
        photos=[_photo_url(photo) for photo in offer.photos],
        attributes=_attributes(offer.params),
        promoted=promoted,
    )


def _search_params(query: SearchQuery, offset: int, limit: int) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "query": query.text,
        "offset": offset,
        "limit": limit,
        # Despite the name this orders by the last bump, not by creation time.
        "sort_by": "created_at:desc",
    }
    optional = {
        "filter_float_price:from": query.price_from,
        "filter_float_price:to": query.price_to,
        "region_id": query.region_id,
        "city_id": query.city_id,
        "category_id": query.category_id,
        "owner_type": "private" if query.private_only else None,
    }
    params.update({key: value for key, value in optional.items() if value is not None})
    return params


class OlxClient:
    """Use as `async with OlxClient() as olx:` so the connection pool is closed."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20.0,
        attempts: int = 3,
        retry_delay: float = 2.0,
        page_delay: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self._attempts = attempts
        self._retry_delay = retry_delay
        self._page_delay = page_delay

    async def __aenter__(self) -> "OlxClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search_page(
        self, query: SearchQuery, *, offset: int = 0, limit: int = MAX_PAGE_SIZE
    ) -> SearchPage:
        """One page of results, newest bump first.

        Promoted listings come on top of `limit` and are marked with `promoted=True`.
        """
        response = await self._get("/offers/", _search_params(query, offset, limit))
        raw = _parse(_RawSearch, response)
        promoted = set(raw.metadata.source.promoted)
        return SearchPage(
            listings=[
                _listing(offer, promoted=index in promoted) for index, offer in enumerate(raw.data)
            ],
            total=raw.metadata.total_elements,
            matched=raw.metadata.visible_total_count,
            has_next="next" in raw.links,
        )

    async def search(
        self, query: SearchQuery, *, max_pages: int = 1, include_promoted: bool = False
    ) -> list[Listing]:
        """Up to `max_pages` pages of results without duplicates.

        Pages overlap when listings are bumped between requests, and the same promoted
        listing is repeated on every page, hence the deduplication.
        """
        seen: set[str] = set()
        result: list[Listing] = []
        for page_number in range(max_pages):
            if page_number:
                await asyncio.sleep(self._page_delay)
            page = await self.search_page(query, offset=page_number * MAX_PAGE_SIZE)
            for listing in page.listings:
                if listing.external_id in seen or (listing.promoted and not include_promoted):
                    continue
                seen.add(listing.external_id)
                result.append(listing)
            if not page.has_next:
                break
        return result

    async def get_listing(self, external_id: str | int) -> Listing | None:
        """A single listing, or `None` if it was removed or never existed."""
        response = await self._get(f"/offers/{external_id}/", allow_404=True)
        if response.status_code == 404:
            return None
        return _listing(_parse(_RawOfferResponse, response).data)

    async def suggest_places(self, text: str, *, limit: int = 10) -> list[Place]:
        """Cities and districts matching `text`, with the IDs that search filters accept."""
        response = await self._get(
            "/geo-encoder/location-autocomplete/", {"query": text, "limit": limit}
        )
        return [_place(item) for item in _parse(_RawLocations, response).data]

    async def _get(
        self, path: str, params: dict[str, str | int] | None = None, *, allow_404: bool = False
    ) -> httpx.Response:
        for attempt in range(1, self._attempts + 1):
            last_attempt = attempt == self._attempts
            try:
                response = await self._http.get(path, params=params)
            except httpx.TransportError as error:
                if last_attempt:
                    raise OlxError(f"OLX is unreachable: {error!r}") from error
                logger.warning("OLX request failed (%r), attempt %d", error, attempt)
            else:
                if response.status_code not in _RETRY_STATUSES or last_attempt:
                    return _checked(response, allow_404=allow_404)
                logger.warning("OLX answered %d, attempt %d", response.status_code, attempt)
            await asyncio.sleep(self._retry_delay * attempt)
        raise AssertionError("unreachable")


def _checked(response: httpx.Response, *, allow_404: bool) -> httpx.Response:
    status = response.status_code
    if status == 200 or (status == 404 and allow_404):
        return response
    if status == 403:
        raise OlxBlockedError(f"OLX blocked the request to {response.url}")
    raise OlxError(f"OLX answered {status} for {response.url}: {response.text[:300]}")


def _parse[T: BaseModel](model: type[T], response: httpx.Response) -> T:
    try:
        return model.model_validate_json(response.content)
    except ValidationError as error:
        raise OlxFormatError(f"Unexpected response from {response.url}: {error}") from error
