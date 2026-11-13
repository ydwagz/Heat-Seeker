import csv
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import truststore
from dotenv import load_dotenv

# Windows certificate store for HTTPS behind antivirus scanning; not on Android (see heat.py)
if sys.platform == "win32":
    truststore.inject_into_ssl()
load_dotenv(Path(__file__).parent.parent / ".env")  # Application/.env, wherever the app is started from

FIRMS_KEY = os.getenv("FIRMS_KEY")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "VIIRS_NOAA21_NRT"
DAYS = 5
GEORGIA_BBOX = "39.9,41.0,46.8,43.6"
COUNTRY_CODE = "ge"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "HeatSeeker-student-project"


def fetch_fires(bbox: str = GEORGIA_BBOX, days: int = DAYS, start: date | None = None) -> list[dict]:
    """Detections in `bbox`: the last `days` days, or `days` days from `start` (FIRMS allows 1-5)."""
    url = f"{FIRMS_URL}/{FIRMS_KEY}/{SOURCE}/{bbox}/{days}"
    if start:
        url += f"/{start:%Y-%m-%d}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    if not response.text.startswith("latitude"):
        # FIRMS answers errors (bad key, bad area) with plain text and status 200
        raise RuntimeError(f"FIRMS refused the request: {response.text.strip()[:200]}")
    return list(csv.DictReader(response.text.splitlines()))


def look_up_address(lat: str, lon: str, lang: str = "en") -> dict:
    response = requests.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "json", "accept-language": lang},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("address", {})


def iter_fires_in_georgia(fires: list[dict], lang: str = "en"):
    """Yield each fire located in Georgia, with its address, as soon as it's confirmed."""
    addresses = {}
    for fire in fires:
        cell = (round(float(fire["latitude"]), 2), round(float(fire["longitude"]), 2))
        if cell not in addresses:
            addresses[cell] = look_up_address(fire["latitude"], fire["longitude"], lang)
            time.sleep(1)  # Nominatim allows at most 1 request per second
        address = addresses[cell]
        if address.get("country_code") == COUNTRY_CODE:
            yield {**fire, "address": address}


# --- Industrial heat ----------------------------------------------------------
# Satellites can't tell a smelter or a gas flare from a fire. A hot spot close to a
# known heat-producing site that keeps showing up on different days is labelled
# "likely industrial heat" instead of being counted as a fire.

INDUSTRIAL_SITES = json.loads(
    (Path(__file__).parent.parent / "data" / "industrial_sites.json").read_text(encoding="utf-8")
)["sites"]
SITE_RADIUS_KM = 2.0  # how close to a factory a hot spot must be
SAME_SPOT_KM = 1.0  # detections this close together count as the same spot
HISTORY_DAYS = 15  # how far back to look for earlier detections
MIN_DAYS_SEEN = 2  # seen on at least this many different days -> likely industrial


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance; accurate enough over a few kilometres."""
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, lat2 - lat1) * 111.2


def nearby_site(lat: float, lon: float) -> dict | None:
    """The closest known industrial site within SITE_RADIUS_KM, if any."""
    site = min(INDUSTRIAL_SITES, key=lambda s: distance_km(lat, lon, s["lat"], s["lon"]))
    return site if distance_km(lat, lon, site["lat"], site["lon"]) <= SITE_RADIUS_KM else None


def fetch_history(lat: float, lon: float, days: int = HISTORY_DAYS) -> list[dict]:
    """Every detection in a ~10 km box around a point over the last `days` days (in 5-day requests)."""
    bbox = f"{lon - 0.06:.3f},{lat - 0.05:.3f},{lon + 0.06:.3f},{lat + 0.05:.3f}"
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset in range(days - 1, -1, -DAYS):
        start = today - timedelta(days=offset)
        rows += fetch_fires(bbox, min(DAYS, offset + 1), start)
    return rows


def days_seen(lat: float, lon: float, detections: list[dict]) -> int:
    """On how many different days a hot spot was detected at (about) this spot."""
    return len(
        {
            d["acq_date"]
            for d in detections
            if distance_km(lat, lon, float(d["latitude"]), float(d["longitude"])) <= SAME_SPOT_KM
        }
    )


def place_name(address: dict) -> str:
    settlement = next(
        (address[k] for k in ("village", "town", "city", "hamlet", "municipality", "county") if k in address),
        None,
    )
    region = address.get("state")
    return ", ".join(part for part in (settlement, region) if part) or "Georgia"
