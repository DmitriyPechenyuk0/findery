from pathlib import Path

import pytest

from findery.profiles import ProfilesFileError, load_profiles_file


def write(tmp_path, text: str):
    path = tmp_path / "profiles.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_profiles_with_defaults(tmp_path):
    path = write(
        tmp_path,
        """
        [[profiles]]
        name = "PS5 Львів"
        query = "playstation 5"
        price_from = 10000
        price_to = 20000
        city_id = 176
        private_only = true
        stop_words = ["vr", "диск"]

        [[profiles]]
        name = "iPhone"
        query = "iphone 13"
        """,
    )
    first, second = load_profiles_file(path)

    assert (first.name, first.query, first.city_id) == ("PS5 Львів", "playstation 5", 176)
    assert (first.price_from, first.price_to, first.private_only) == (10000, 20000, True)
    assert first.stop_words == ["vr", "диск"]
    assert (second.source, second.interval_minutes, second.price_to) == ("olx", 30, None)
    assert second.stop_words == []


def test_example_file_is_valid():
    assert load_profiles_file(Path(__file__).parent.parent / "profiles.example.toml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[profiles]]\nname = "a"\n', "query"),
        ('[[profiles]]\nname = "a"\nquery = "x"\nprise_to = 5\n', "prise_to"),
        ('[[profiles]]\nname = "a"\nquery = "x"\nprice_from = 9\nprice_to = 5\n', "price_from"),
        ('[[profiles]]\nname = "a"\nquery = "x"\ninterval_minutes = 0\n', "interval_minutes"),
        (
            '[[profiles]]\nname = "a"\nquery = "x"\n[[profiles]]\nname = "a"\nquery = "y"\n',
            "repeat",
        ),
        ("[[profiles]\n", "profiles.toml"),
    ],
)
def test_invalid_file_is_rejected_with_a_pointer_to_the_problem(tmp_path, text, message):
    with pytest.raises(ProfilesFileError, match=message):
        load_profiles_file(write(tmp_path, text))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ProfilesFileError):
        load_profiles_file(tmp_path / "nope.toml")
