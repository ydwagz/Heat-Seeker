"""Canadian Fire Weather Index, checked against the published test data."""

import pytest

from core import fwi

# Published test data for the FWI System (Van Wagner & Pickett 1985, "Equations and FORTRAN
# program for the Canadian Forest Fire Weather Index System"): four April days, chained from
# the standard start-up values FFMC 85, DMC 6, DC 15.
# (month, temp °C, RH %, wind km/h, rain mm) -> (FFMC, DMC, DC, ISI, BUI, FWI)
PUBLISHED = [
    ((4, 17.0, 42, 25, 0.0), (87.7, 8.5, 19.0, 10.9, 8.5, 10.1)),
    ((4, 20.0, 21, 25, 2.4), (86.2, 10.4, 23.6, 8.8, 10.4, 9.3)),
    ((4, 8.5, 40, 17, 0.0), (87.0, 11.8, 26.1, 6.5, 11.7, 7.6)),
    ((4, 6.5, 25, 6, 0.0), (88.8, 13.2, 28.2, 4.9, 13.1, 6.2)),
]


def published_run():
    return fwi.run([fwi.DayWeather(*weather) for weather, _ in PUBLISHED])


@pytest.mark.parametrize("day", range(len(PUBLISHED)))
def test_matches_published_values(day):
    result = published_run()[day]
    expected = PUBLISHED[day][1]
    got = (result.ffmc, result.dmc, result.dc, result.isi, result.bui, result.fwi)
    assert got == pytest.approx(expected, abs=0.1)  # the table is rounded to one decimal


@pytest.mark.parametrize(
    "value, danger",
    [
        (0.0, "Very low"),
        (5.1, "Very low"),
        (5.2, "Low"),
        (11.2, "Moderate"),
        (21.3, "High"),
        (37.9, "High"),
        (38.0, "Very high"),
        (50.0, "Extreme"),
        (120.0, "Extreme"),
    ],
)
def test_effis_danger_classes(value, danger):
    assert fwi.danger_class(value) == danger


def test_rain_makes_fine_fuels_wetter():
    dry = fwi.ffmc(25, 30, 15, rain=0.0, ffmc_yesterday=88)
    wet = fwi.ffmc(25, 30, 15, rain=10.0, ffmc_yesterday=88)
    assert wet < dry


def test_hot_dry_days_build_up_the_drought_code():
    days = [fwi.DayWeather(7, 35, 15, 20, 0.0)] * 30
    results = fwi.run(days)
    assert results[-1].dc > results[0].dc > fwi.START_DC
    assert results[-1].danger in ("Very high", "Extreme")


def test_heavy_rain_resets_the_drought_code_but_never_below_zero():
    assert fwi.dc(10, rain=500.0, month=7, dc_yesterday=300) >= 0
    assert fwi.dc(10, rain=50.0, month=7, dc_yesterday=300) < 300
