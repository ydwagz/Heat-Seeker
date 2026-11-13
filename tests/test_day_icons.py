"""Which weather picture each day of the 7-day forecast gets."""

import pytest

from main import day_icon_name


@pytest.mark.parametrize(
    "code, wind, picture",
    [
        (0, 5, "weather_sun.png"),  # clear
        (2, 5, "weather_sun.png"),  # partly cloudy still reads as a sunny day
        (3, 5, "weather_cloud.png"),  # overcast
        (45, 5, "weather_cloud.png"),  # fog
        (61, 5, "weather_rain.png"),
        (95, 40, "weather_rain.png"),  # thunderstorm: rain beats wind
        (73, 5, "weather_snow.png"),
        (0, 35, "weather_wind.png"),  # dry but windy
        (None, 5, "weather_sun.png"),  # no weather type from the service
    ],
)
def test_day_picture(code, wind, picture):
    assert day_icon_name({"code": code, "wind": wind}) == picture
