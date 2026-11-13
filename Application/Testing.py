from datetime import datetime, timedelta, timezone

TESTING = False


# --- Weather: Home and Fire Risk screens -------------------------------------
TEMPERATURE_C = 38  # air temperature, °C
HUMIDITY = 15  # relative humidity, % (0-100)
WIND_SPEED_KMH = 25  # wind speed, km/h (30 or more shows the wind icon)
WIND_FROM = "W"  # where the wind blows FROM: N, NE, E, SE, S, SW, W, NW (or degrees, e.g. 270)
CLOUD_COVER = 10  # % of the sky covered by cloud (0-100)
IS_DAY = True  # False = night: no sunshine, so glass can't start fires
SKY = "clear"  # weather icon: clear, cloudy, fog, rain, snow, storm
TIME = "14:30"  # shown as "Updated 14:30 local time"

# --- Fire Weather Index: the 7-day forecast on the Fire Risk screen -----------
DRY_DAYS_BEFORE = 40  # days without rain before today, with the weather above (dries the forest floor)
# Today and the next 6 days, as changes from the weather above: (temperature change in °C,
# humidity change in %, rain in mm). The first line is today.
FORECAST = [
    (0, 0, 0),
    (2, -3, 0),
    (3, -5, 0),
    (-2, 10, 0),
    (-8, 35, 12),  # a rainy day: the danger drops
    (-5, 20, 0),
    (0, 5, 0),
]


# --- Fires: Fires Happening screen -------------------------------------------
# One line per fire: (latitude, longitude, hours ago, fire power in MW, place, region)
# Leave the list empty, FIRES = [], to see the "no fires" screen.
FIRES = [
    (42.272, 42.625, 2, 14.0, "Kutaisi", "Imereti"),  # just west of Kutaisi
    (41.73, 45.33, 3, 12.4, "Sagarejo", "Kakheti"),
    (41.55, 43.25, 27, 3.2, "Aspindza", "Samtskhe-Javakheti"),
    (42.95, 41.25, 50, 21.7, "Gulripshi", "Autonomous Republic of Abkhazia"),
    (41.42, 46.25, 75, 5.6, "Lagodekhi", "Kakheti"),
    (42.1242, 43.0135, 20, 0.8, "Kveda Sakara", "Imereti"),  # next to the Zestaponi ferroalloy plant
]

# Earlier detections of the same spots: (latitude, longitude, days ago).
# A fire within 2 km of a factory or power plant (data/industrial_sites.json) that was also
# seen on another day is shown as "Likely industrial heat" instead of a fire.
# Leave the list empty, SEEN_BEFORE = [], and the Kveda Sakara fire above shows as a fire.
SEEN_BEFORE = [
    (42.1245, 43.0127, 3),
    (42.1239, 43.0141, 9),
]


# --- You don't need to change anything below this line ------------------------

COMPASS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
# Open-Meteo / WMO weather codes for each SKY choice
SKY_CODES = {"clear": 0, "cloudy": 3, "fog": 45, "rain": 61, "snow": 73, "storm": 95}


def test_weather() -> dict:
    """The values above, shaped like Open-Meteo's "current" weather."""
    if isinstance(WIND_FROM, str):
        wind_deg = COMPASS[WIND_FROM.strip().upper()]
    else:
        wind_deg = float(WIND_FROM) % 360
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "time": f"{today}T{TIME}",
        "temperature_2m": float(TEMPERATURE_C),
        "relative_humidity_2m": int(HUMIDITY),
        "wind_speed_10m": float(WIND_SPEED_KMH),
        "wind_direction_10m": wind_deg,
        "cloud_cover": int(CLOUD_COVER),
        "is_day": 1 if IS_DAY else 0,
        "weather_code": SKY_CODES[SKY.strip().lower()],
    }


def test_fires() -> list[dict]:
    """The fires above, shaped like NASA FIRMS detections that are already located in Georgia."""
    now = datetime.now(timezone.utc)
    fires = []
    for lat, lon, hours_ago, power_mw, place, region in FIRES:
        seen = now - timedelta(hours=hours_ago)
        fires.append(
            {
                "latitude": str(lat),
                "longitude": str(lon),
                "acq_date": seen.strftime("%Y-%m-%d"),
                "acq_time": seen.strftime("%H%M"),
                "frp": str(power_mw),
                "address": {"village": place, "state": region, "country_code": "ge"},
            }
        )
    return fires


def test_history() -> list[dict]:
    """The earlier detections above, shaped like NASA FIRMS rows."""
    today = datetime.now(timezone.utc)
    return [
        {
            "latitude": str(lat),
            "longitude": str(lon),
            "acq_date": (today - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
            "acq_time": "2300",
            "frp": "1.0",
        }
        for lat, lon, days_ago in SEEN_BEFORE
    ]


def test_fire_weather() -> list[dict]:
    """The settings above as a daily noon series for the Fire Weather Index, oldest day first."""
    today = datetime.now().date()
    wind = float(WIND_SPEED_KMH)
    days = []
    for back in range(DRY_DAYS_BEFORE, 0, -1):
        date = today - timedelta(days=back)
        days.append({"date": f"{date}", "month": date.month, "temp": float(TEMPERATURE_C), "rh": float(HUMIDITY),
                     "wind": wind, "rain": 0.0, "tmax": float(TEMPERATURE_C) + 2, "forecast": False,
                     "code": SKY_CODES[SKY.strip().lower()]})
    for ahead, (temp_change, rh_change, rain) in enumerate(FORECAST):
        date = today + timedelta(days=ahead)
        temp = float(TEMPERATURE_C + temp_change)
        rh = float(min(max(HUMIDITY + rh_change, 1), 100))
        days.append({"date": f"{date}", "month": date.month, "temp": temp, "rh": rh,
                     "wind": wind, "rain": float(rain), "tmax": temp + 2, "forecast": True,
                     "code": SKY_CODES["rain"] if rain else SKY_CODES[SKY.strip().lower()]})
    return days
