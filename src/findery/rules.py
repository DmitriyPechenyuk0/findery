"""Cheap checks a listing must pass before anything expensive looks at it."""

import re
from decimal import Decimal

# Reasons a listing is rejected. Price reasons are re-checked when the price changes.
NO_PRICE = "no_price"
PRICE = "price"
STOP_WORD = "stop_word"
PRICE_REASONS = frozenset({NO_PRICE, PRICE})

# Applied to every profile: wanted ads, swaps and broken items are never the thing itself.
DEFAULT_STOP_WORDS = (
    "куплю",
    "скупка",
    "скуповую",
    "скупаю",
    "обмін на",
    "обмен на",
    "на запчастини",
    "на запчасти",
    "під відновлення",
    "под восстановление",
)


def stop_word_pattern(words: list[str] | tuple[str, ...]) -> re.Pattern[str] | None:
    """One pattern for all words. A word matches only at the start of a word in the text,
    so "диск" catches "диски" but "vr" does not catch "cover"."""
    # Longest first, so that "на запчастини" is reported rather than its prefix "на запчасти".
    cleaned = sorted({word.strip().casefold() for word in words if word.strip()}, key=len)[::-1]
    if not cleaned:
        return None
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(word) for word in cleaned) + ")")


def find_stop_word(title: str, pattern: re.Pattern[str] | None) -> str | None:
    if pattern is None:
        return None
    found = pattern.search(title.casefold())
    return found.group(1) if found else None


def check_price(
    price_uah: Decimal | None, price_from: int | None, price_to: int | None
) -> str | None:
    """`None` if the price fits the range, otherwise the reason it does not."""
    if price_from is None and price_to is None:
        return None
    if price_uah is None:
        return NO_PRICE
    if price_from is not None and price_uah < price_from:
        return PRICE
    if price_to is not None and price_uah > price_to:
        return PRICE
    return None
