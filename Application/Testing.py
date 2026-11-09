from datetime import datetime, timedelta, timezone

TESTING = True


# --- Weather: Home and Fire Risk screens -------------------------------------
TEMPERATURE_C = 38  # air temperature, °C
HUMIDITY = 15  # relative humidity, % (0-100)
WIND_SPEED_KMH = 25  # wind speed, km/h (30 or more shows the wind icon)
WIND_FROM = "W"  # where the wind blows FROM: N, NE, E, SE, S, SW, W, NW (or degrees, e.g. 270)
CLOUD_COVER = 10  # % of the sky covered by cloud (0-100)
IS_DAY = True  # False = night: no sunshine, so glass can't start fires
SKY = "clear"  # weather icon: clear, cloudy, fog, rain, snow, storm
TIME = "14:30"  # shown as "Updated 14:30 local time"


# --- Fires: Fires Happening screen -------------------------------------------
# One line per fire: (latitude, longitude, hours ago, fire power in MW, place, region)
# Leave the list empty, FIRES = [], to see the "no fires" screen.
FIRES = [
    (41.73, 45.33, 3, 12.4, "Sagarejo", "Kakheti"),
    (41.55, 43.25, 27, 3.2, "Aspindza", "Samtskhe-Javakheti"),
    (42.95, 41.25, 50, 21.7, "Gulripshi", "Autonomous Republic of Abkhazia"),
    (41.42, 46.25, 75, 5.6, "Lagodekhi", "Kakheti"),
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
