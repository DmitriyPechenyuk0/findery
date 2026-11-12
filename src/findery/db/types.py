"""Column types that paper over what SQLite cannot store natively."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.types import TypeDecorator

_CENT = Decimal("0.01")


class Money(TypeDecorator):
    """A `Decimal` amount stored as an integer number of hundredths.

    SQLite has no decimal type; integers keep comparisons and aggregates in SQL exact.
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> int | None:
        if value is None:
            return None
        return int(Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP) * 100)

    def process_result_value(self, value: int | None, dialect) -> Decimal | None:
        return None if value is None else Decimal(value) / 100


class UtcDateTime(TypeDecorator):
    """A timezone-aware `datetime`, stored in UTC. SQLite drops the offset otherwise."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: every timestamp in the database must have a timezone")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)
