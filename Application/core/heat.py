import sys

import requests
import truststore

# Use the Windows certificate store, so HTTPS works behind antivirus web scanning.
# Only on Windows: on Android it would hide the certificates requests needs.
if sys.platform == "win32":
    truststore.inject_into_ssl()

TBILISI = (41.72, 44.79)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


def heat_index(temp_c: float, rh: float) -> tuple[float, float]:
    temp_f = temp_c * 9 / 5 + 32

    c_1 = -42.379
    c_2 = 2.04901523
    c_3 = 10.14333127
    c_4 = -0.22475541
    c_5 = -0.00683783
    c_6 = -0.05481717
    c_7 = 0.00122874
    c_8 = 0.00085282
    c_9 = -0.00000199

    hi = 0.5 * (temp_f + 61 + (temp_f - 68) * 1.2 + rh * 0.094)

    if hi >= 80:
        hi = (
            c_1
            + c_2 * temp_f
            + c_3 * rh
            + c_4 * temp_f * rh
            + c_5 * temp_f**2
            + c_6 * rh**2
            + c_7 * temp_f**2 * rh
            + c_8 * temp_f * rh**2
            + c_9 * temp_f**2 * rh**2
        )

    hi_c = (hi - 32) * 5 / 9
    return hi, hi_c


def risk_level(hi_f: float) -> str:
    if hi_f < 80:
        return "Safe"
    if hi_f < 90:
        return "Caution"
    if hi_f < 103:
        return "Extreme Caution"
    if hi_f < 125:
        return "Danger"
    return "Extreme Danger"


def heat_risk_checker(temp_c: float, rh: float) -> dict:
    hi_f, hi_c = heat_index(temp_c, rh)
    return {"hi_f": hi_f, "hi_c": hi_c, "level": risk_level(hi_f)}


def fetch_current_weather(lat: float = TBILISI[0], lon: float = TBILISI[1]) -> dict:
    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "wind_speed_10m,wind_direction_10m,cloud_cover,is_day,weather_code"
            ),
            "timezone": "auto",  # "time" comes back in the place's local time
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["current"]


FIRE_WEATHER_PAST_DAYS = 92  # Open-Meteo's maximum; the Drought Code needs months to settle
FORECAST_DAYS = 7


def fetch_fire_weather(lat: float = TBILISI[0], lon: float = TBILISI[1]) -> list[dict]:
    """Daily noon weather for the Fire Weather Index: the last 92 days and the next 7.

    Each day has its date, month, noon temperature (deg C), relative humidity (%), wind
    speed (km/h), the rain of the 24 hours up to noon (mm), the day's highest temperature,
    and whether it is a forecast (today counts as a forecast: its noon may still be ahead).
    """
    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
            "daily": "temperature_2m_max,weather_code",
            "past_days": FIRE_WEATHER_PAST_DAYS,
            "forecast_days": FORECAST_DAYS,
            "timezone": "auto",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    hourly, daily = data["hourly"], data["daily"]
    today = data["daily"]["time"][FIRE_WEATHER_PAST_DAYS]  # first forecast day = today, local time
    tmax = dict(zip(daily["time"], daily["temperature_2m_max"]))
    codes = dict(zip(daily["time"], daily["weather_code"]))

    days = []
    times = hourly["time"]
    for i, stamp in enumerate(times):
        if not stamp.endswith("T12:00") or i < 23:
            continue  # noon only, and only once a full 24 hours of rain is available
        temp = hourly["temperature_2m"][i]
        rh = hourly["relative_humidity_2m"][i]
        wind = hourly["wind_speed_10m"][i]
        rain_hours = hourly["precipitation"][i - 23 : i + 1]  # 13:00 yesterday .. 12:00 today
        if None in (temp, rh, wind) or None in rain_hours:
            continue
        date = stamp[:10]
        days.append(
            {
                "date": date,
                "month": int(date[5:7]),
                "temp": temp,
                "rh": rh,
                "wind": wind,
                "rain": sum(rain_hours),
                "tmax": tmax.get(date),
                "code": codes.get(date),  # the day's main weather (WMO code), for its picture
                "forecast": date >= today,
            }
        )
    return days


def search_places(name: str, count: int = 8, language: str = "en") -> list[dict]:
    """Places in Georgia matching a name, best match first: name, region, latitude, longitude.

    `language` ("en" or "ka") picks the language of the returned names.
    """
    response = requests.get(
        GEOCODING_URL,
        params={"name": name, "count": count, "language": language, "format": "json", "countryCode": "GE"},
        timeout=10,
    )
    response.raise_for_status()
    places, seen = [], set()
    for place in response.json().get("results", []):
        key = (place["name"], place.get("admin1", ""))
        if key in seen:  # the database often lists the same town twice
            continue
        seen.add(key)
        places.append(
            {
                "name": place["name"],
                "region": place.get("admin1", ""),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
            }
        )
    return places
