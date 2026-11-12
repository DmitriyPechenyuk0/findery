"""Database schema. Change it only together with a new migration:

uv run alembic revision --autogenerate -m "what changed"
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from findery.db.types import Money, UtcDateTime

# Explicit constraint names: SQLite migrations cannot alter unnamed constraints.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar = {datetime: UtcDateTime, Decimal: Money, dict[str, Any]: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str | None]
    created_at: Mapped[datetime]


class Profile(Base):
    """A saved search that is polled on a schedule."""

    __tablename__ = "profiles"
    __table_args__ = (Index("ix_profiles_due", "is_active", "next_run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    source: Mapped[str] = mapped_column(String(16))
    query: Mapped[str]
    # The price range is applied on our side: listings outside it are still stored
    # so that market statistics are not cut off by the range.
    price_from: Mapped[int | None]
    price_to: Mapped[int | None]
    region_id: Mapped[int | None]
    city_id: Mapped[int | None]
    category_id: Mapped[int | None]
    private_only: Mapped[bool] = mapped_column(default=False)
    stop_words: Mapped[list[str]] = mapped_column(JSON, default=list)
    interval_minutes: Mapped[int] = mapped_column(default=30)
    is_active: Mapped[bool] = mapped_column(default=True)
    next_run_at: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class ListingRow(Base):
    """Current state of a listing. Its price history is in `listing_snapshots`."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str]
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))

    price_amount: Mapped[Decimal | None]
    price_currency: Mapped[str | None] = mapped_column(String(3))
    price_uah: Mapped[Decimal | None] = mapped_column(index=True)
    price_negotiable: Mapped[bool] = mapped_column(default=False)
    price_free: Mapped[bool] = mapped_column(default=False)

    seller_id: Mapped[str | None] = mapped_column(String(64), index=True)
    seller_name: Mapped[str | None]
    seller_is_business: Mapped[bool] = mapped_column(default=False)
    seller_registered_at: Mapped[datetime | None]

    city_id: Mapped[int | None]
    city: Mapped[str | None]
    region_id: Mapped[int | None]
    region: Mapped[str | None]
    district_id: Mapped[int | None]
    district: Mapped[str | None]
    lat: Mapped[float | None]
    lon: Mapped[float | None]

    category_id: Mapped[int | None]
    category_type: Mapped[str | None]
    photos: Mapped[list[str]] = mapped_column(JSON)
    attributes: Mapped[dict[str, Any]]

    # Timestamps reported by the platform.
    created_at: Mapped[datetime | None]
    refreshed_at: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]
    # Timestamps of our own observations.
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]


class ListingSnapshot(Base):
    """One row per observed change of price or status, starting with the first sighting."""

    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    seen_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(32))
    price_amount: Mapped[Decimal | None]
    price_currency: Mapped[str | None] = mapped_column(String(3))
    price_uah: Mapped[Decimal | None]


class Match(Base):
    """How far a listing got through the pipeline of one profile."""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("profile_id", "listing_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    # Last pipeline stage reached, and why the listing stopped there if it did.
    stage: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None]
    created_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
