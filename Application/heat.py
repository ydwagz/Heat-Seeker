import requests
import truststore

truststore.inject_into_ssl()

TBILISI = (41.72, 44.79)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


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
    """Current weather from Open-Meteo.

    Keys: time, temperature_2m (°C), relative_humidity_2m (%), wind_speed_10m (km/h),
    wind_direction_10m (degrees the wind blows FROM), cloud_cover (%), is_day (0/1).
    """
    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "wind_speed_10m,wind_direction_10m,cloud_cover,is_day"
            ),
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["current"]


if __name__ == "__main__":
    current = fetch_current_weather()
    print(f'time: {current["time"]}')
    print(f'Temperature: {current["temperature_2m"]} C')
    print(f'Humidity: {current["relative_humidity_2m"]} %')
    print(heat_risk_checker(current["temperature_2m"], current["relative_humidity_2m"]))
