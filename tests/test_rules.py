from decimal import Decimal

import pytest

from findery.rules import NO_PRICE, PRICE, check_price, find_stop_word, stop_word_pattern


@pytest.mark.parametrize(
    ("price", "low", "high", "expected"),
    [
        (Decimal("15000"), 10000, 20000, None),
        (Decimal("10000"), 10000, 20000, None),
        (Decimal("20000"), 10000, 20000, None),
        (Decimal("9999.99"), 10000, 20000, PRICE),
        (Decimal("20000.01"), 10000, 20000, PRICE),
        (Decimal("5"), None, 20000, None),
        (Decimal("999999"), 10000, None, None),
        (Decimal("0"), 10000, None, PRICE),
        (None, 10000, 20000, NO_PRICE),
        (None, None, None, None),
        (Decimal("1"), None, None, None),
    ],
)
def test_check_price(price, low, high, expected):
    assert check_price(price, low, high) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Куплю PlayStation 5 дорого", "куплю"),
        ("Диски PS5, ігри", "диск"),
        ("PlayStation VR2", "vr"),
        ("PS5 на запчастини", "на запчастини"),
        ("PlayStation 5 Slim 1TB", None),
        # Only the start of a word counts: "vr" inside "cover", "куплю" inside "викуплю".
        ("PS5 cover plates", None),
        ("Продам, викуплю ваш PS4", None),
    ],
)
def test_find_stop_word(title, expected):
    pattern = stop_word_pattern(["куплю", "Диск", " VR ", "на запчастини", ""])
    assert find_stop_word(title, pattern) == expected


def test_no_stop_words_means_nothing_is_rejected():
    assert stop_word_pattern([]) is None
    assert find_stop_word("куплю все", None) is None


def test_stop_words_are_taken_literally():
    pattern = stop_word_pattern(["c++", "1.5"])
    assert find_stop_word("книга c++ для початківців", pattern) == "c++"
    assert find_stop_word("об'єм 125 мл", pattern) is None
