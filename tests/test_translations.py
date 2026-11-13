"""Every text exists in both languages and fills in the same values."""

import string

import pytest

import translations


def fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_english_and_georgian_have_the_same_texts():
    assert set(translations.STRINGS["en"]) == set(translations.STRINGS["ka"])


@pytest.mark.parametrize("key", sorted(translations.STRINGS["en"]))
def test_both_languages_fill_in_the_same_values(key):
    en, ka = translations.STRINGS["en"][key], translations.STRINGS["ka"][key]
    # Georgian may use the genitive form of a city name ("{city_of}") where English says "{city}"
    same_city = lambda names: {"city" if n == "city_of" else n for n in names}  # noqa: E731
    assert same_city(fields(en)) == same_city(fields(ka))
