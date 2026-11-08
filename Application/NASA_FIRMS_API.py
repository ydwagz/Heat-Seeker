import csv
import os
import time

import requests
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

FIRMS_KEY = os.getenv("FIRMS_KEY")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "VIIRS_NOAA21_NRT"
DAYS = 5
GEORGIA_BBOX = "39.9,41.0,46.8,43.6"
COUNTRY_CODE = "ge"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "HeatSeeker-student-project"


def fetch_fires(bbox: str = GEORGIA_BBOX, days: int = DAYS) -> list[dict]:
    response = requests.get(f"{FIRMS_URL}/{FIRMS_KEY}/{SOURCE}/{bbox}/{days}", timeout=60)
    response.raise_for_status()
    if not response.text.startswith("latitude"):
        # FIRMS answers errors (bad key, bad area) with plain text and status 200
        raise RuntimeError(f"FIRMS refused the request: {response.text.strip()[:200]}")
    return list(csv.DictReader(response.text.splitlines()))


def look_up_address(lat: str, lon: str) -> dict:
    response = requests.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "json", "accept-language": "en"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("address", {})


def iter_fires_in_georgia(fires: list[dict]):
    """Yield each fire located in Georgia, with its address, as soon as it's confirmed."""
    addresses = {}
    for fire in fires:
        cell = (round(float(fire["latitude"]), 2), round(float(fire["longitude"]), 2))
        if cell not in addresses:
            addresses[cell] = look_up_address(fire["latitude"], fire["longitude"])
            time.sleep(1)  # Nominatim allows at most 1 request per second
        address = addresses[cell]
        if address.get("country_code") == COUNTRY_CODE:
            yield {**fire, "address": address}


def fires_in_georgia(fires: list[dict]) -> list[dict]:
    return list(iter_fires_in_georgia(fires))


def place_name(address: dict) -> str:
    settlement = next(
        (address[k] for k in ("village", "town", "city", "hamlet", "municipality", "county") if k in address),
        None,
    )
    region = address.get("state")
    return ", ".join(part for part in (settlement, region) if part) or "Georgia"


def detection_time(fire: dict) -> str:
    hhmm = fire["acq_time"].zfill(4)
    return f"{fire['acq_date']} {hhmm[:2]}:{hhmm[2:]} UTC"


def main():
    if not FIRMS_KEY:
        raise SystemExit("FIRMS_KEY is missing. Add it to Application/.env.")

    fires = fetch_fires()
    georgia = fires_in_georgia(fires)
    skipped = len(fires) - len(georgia)

    print(f"{len(georgia)} fires detected in Georgia in the last {DAYS} days.")
    if skipped:
        print(f"Skipped {skipped} detections just across the border.")

    for fire in sorted(georgia, key=detection_time, reverse=True):
        lat, lon = fire["latitude"], fire["longitude"]
        print()
        print(f"{detection_time(fire)}  {place_name(fire['address'])}")
        print(f"  https://www.google.com/maps?q={lat},{lon}")


if __name__ == "__main__":
    main()
