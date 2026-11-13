"""Heat Index (NOAA / Rothfusz regression) and the heat risk levels."""

import pytest

from core.heat import heat_index, heat_risk_checker, risk_level


def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


# Values read from the NOAA / National Weather Service heat index chart:
# (air temperature °F, relative humidity %, heat index °F on the chart)
NOAA_CHART = [
    (80, 40, 80),
    (80, 60, 82),
    (90, 40, 91),
    (90, 50, 95),
    (90, 60, 100),
    (90, 70, 106),
    (96, 40, 101),
    (100, 40, 109),
    (86, 90, 105),
]


@pytest.mark.parametrize("temp_f, rh, chart_f", NOAA_CHART)
def test_heat_index_matches_noaa_chart(temp_f, rh, chart_f):
    hi_f, _ = heat_index(f_to_c(temp_f), rh)
    assert hi_f == pytest.approx(chart_f, abs=1.0)  # the chart is rounded to whole degrees


def test_heat_index_celsius_is_the_same_value():
    hi_f, hi_c = heat_index(f_to_c(90), 50)
    assert hi_c == pytest.approx(f_to_c(hi_f))


def test_mild_weather_feels_like_the_air_temperature():
    # Below 80 °F the simple Steadman formula is used; at 20 °C and 50% it barely differs
    hi_f, _ = heat_index(20.0, 50)
    assert hi_f == pytest.approx(68, abs=2)


@pytest.mark.parametrize(
    "hi_f, level",
    [
        (79.9, "Safe"),
        (80.0, "Caution"),
        (89.9, "Caution"),
        (90.0, "Extreme Caution"),
        (103.0, "Danger"),
        (124.9, "Danger"),
        (125.0, "Extreme Danger"),
    ],
)
def test_risk_level_boundaries_follow_nws(hi_f, level):
    assert risk_level(hi_f) == level


def test_heat_risk_checker_combines_both():
    result = heat_risk_checker(f_to_c(100), 40)
    assert result["level"] == "Danger"
    assert result["hi_f"] == pytest.approx(109, abs=1)
