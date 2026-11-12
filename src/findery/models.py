"""Platform-independent models. Every source adapter converts its responses into these."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Price(Frozen):
    amount: Decimal
    currency: str
    # Amount in hryvnias: equal to `amount` for UAH, the platform's conversion otherwise,
    # `None` when the platform gave no conversion.
    amount_uah: Decimal | None = None
    # What the seller asked before the last price change, in `currency`.
    previous_amount: Decimal | None = None
    negotiable: bool = False
    free: bool = False


class Seller(Frozen):
    id: str
    name: str | None = None
    is_business: bool = False
    registered_at: datetime | None = None


class Place(Frozen):
    city_id: int | None = None
    city: str | None = None
    region_id: int | None = None
    region: str | None = None
    district_id: int | None = None
    district: str | None = None
    lat: float | None = None
    lon: float | None = None

    def label(self) -> str:
        """Human-readable place, e.g. "Львів, Сихівський"."""
        parts = [self.city or self.region, self.district]
        return ", ".join(part for part in parts if part)


class Attribute(Frozen):
    """A category-specific field such as condition or brand."""

    name: str
    # Machine value: one key, or several for multi-choice fields.
    value: str | list[str] | None = None
    label: str | None = None


class Listing(Frozen):
    source: str
    # ID on the platform. Unique only together with `source`.
    external_id: str
    url: str
    title: str
    description: str = ""
    status: str = "active"
    # `None` when the listing has no price at all (services, exchange).
    price: Price | None = None
    seller: Seller | None = None
    place: Place = Place()
    category_id: int | None = None
    category_type: str | None = None
    created_at: datetime | None = None
    # Last time the seller bumped the listing; search results are ordered by this.
    refreshed_at: datetime | None = None
    valid_to: datetime | None = None
    photos: list[str] = []
    attributes: dict[str, Attribute] = {}
    # Paid placement: shown regardless of how well it matches the query.
    promoted: bool = False


class SearchQuery(Frozen):
    """What to look for. Fields a platform does not support are ignored by its adapter."""

    text: str
    price_from: int | None = None
    price_to: int | None = None
    region_id: int | None = None
    city_id: int | None = None
    category_id: int | None = None
    private_only: bool = False
