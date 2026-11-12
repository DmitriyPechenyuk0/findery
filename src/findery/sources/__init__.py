"""Source adapters: one module per classifieds platform."""

from typing import Protocol

from findery.models import Listing, SearchQuery


class Page(Protocol):
    listings: list[Listing]
    has_next: bool


class Source(Protocol):
    """What the pipeline needs from a platform."""

    # Listings per page; the offset of page N is N * page_size.
    page_size: int

    async def search_page(self, query: SearchQuery, *, offset: int = 0) -> Page: ...
