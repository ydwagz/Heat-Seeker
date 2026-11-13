"""Validate the "likely industrial heat" filter on one month of real NASA FIRMS data.

For every satellite detection inside Georgia in the study month, apply exactly the rule the
app uses (Application/core/nasa_firms.py):

    a hot spot is "likely industrial heat" if it lies within SITE_RADIUS_KM of a known
    heat-producing site AND was detected on at least MIN_DAYS_SEEN different days within
    SAME_SPOT_KM over the HISTORY_DAYS before it (that day included).

Outputs (in validation/results/):
    detections.csv      every detection in Georgia with its classification
    summary.json        the counts
    chart.png           detections per week (fires vs industrial) and per industrial site
    satellite/*.jpg     satellite image of every place classified as industrial, plus a few
                        places kept as fires, for checking by eye

Run from the project folder:   env\\Scripts\\python.exe validation\\validate_industrial_filter.py
Needs FIRMS_KEY in Application/.env and matplotlib (pip install matplotlib).
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Application"))

from core import nasa_firms as firms  # noqa: E402  (also loads the key and the SSL fix)

OUT = Path(__file__).resolve().parent / "results"
STUDY_END = date(2026, 11, 12)  # last day of the study month (inclusive)
STUDY_DAYS = 30
OUTLINE = json.loads((ROOT / "Application" / "data" / "georgia_outline.json").read_text(encoding="utf-8"))["outline"]


def in_georgia(lon: float, lat: float) -> bool:
    """Point-in-polygon test against Georgia's border (OpenStreetMap outline)."""
    hit, j = False, len(OUTLINE) - 1
    for i in range(len(OUTLINE)):
        xi, yi = OUTLINE[i]
        xj, yj = OUTLINE[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def download(first: date, last: date) -> list[dict]:
    """All detections in the Georgia box from `first` to `last`, in 5-day requests."""
    rows, start = [], first
    while start <= last:
        days = min(firms.DAYS, (last - start).days + 1)
        rows += firms.fetch_fires(firms.GEORGIA_BBOX, days, start)
        start += timedelta(days=days)
    return rows


def classify(det: dict, history: list[dict]) -> tuple[str, dict | None, int]:
    """("industrial" | "fire", nearby site, days seen) with the app's rule."""
    lat, lon = float(det["latitude"]), float(det["longitude"])
    site = firms.nearby_site(lat, lon)
    if site is None:
        return "fire", None, 0
    day = datetime.strptime(det["acq_date"], "%Y-%m-%d").date()
    window = [h for h in history if 0 <= (day - datetime.strptime(h["acq_date"], "%Y-%m-%d").date()).days < firms.HISTORY_DAYS]
    seen = firms.days_seen(lat, lon, window)
    return ("industrial" if seen >= firms.MIN_DAYS_SEEN else "fire"), site, seen


def satellite_image(lat: float, lon: float, path: Path, half_km: float = 1.2):
    """Esri World Imagery around a point (about 2.4 km across), saved as JPEG."""
    dlat = half_km / 111.2
    dlon = half_km / (111.2 * max(0.1, __import__("math").cos(__import__("math").radians(lat))))
    r = requests.get(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export",
        params={
            "bbox": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
            "bboxSR": 4326, "imageSR": 3857, "size": "500,500", "format": "jpg", "f": "image",
        },
        timeout=60,
    )
    r.raise_for_status()
    path.write_bytes(r.content)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "satellite").mkdir(exist_ok=True)
    study_start = STUDY_END - timedelta(days=STUDY_DAYS - 1)
    history_start = study_start - timedelta(days=firms.HISTORY_DAYS - 1)

    print(f"Downloading FIRMS {firms.SOURCE} {history_start} .. {STUDY_END} ...")
    raw = download(history_start, STUDY_END)
    georgia = [d for d in raw if in_georgia(float(d["longitude"]), float(d["latitude"]))]
    study = [d for d in georgia if datetime.strptime(d["acq_date"], "%Y-%m-%d").date() >= study_start]
    print(f"{len(raw)} detections in the box, {len(georgia)} inside Georgia, {len(study)} in the study month")

    rows = []
    for d in study:
        label, site, seen = classify(d, georgia)
        rows.append({**{k: d[k] for k in ("latitude", "longitude", "acq_date", "acq_time", "frp", "daynight", "confidence")},
                     "class": label, "site": site["en"] if site else "", "days_seen": seen})

    with open(OUT / "detections.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["class"])
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["class"] for r in rows)
    near_site = [r for r in rows if r["site"]]
    by_site = Counter(r["site"] for r in rows if r["class"] == "industrial")
    night_share = lambda group: round(100 * sum(r["daynight"] == "N" for r in group) / len(group)) if group else None  # noqa: E731
    summary = {
        "source": firms.SOURCE,
        "study_period": [str(study_start), str(STUDY_END)],
        "history_from": str(history_start),
        "detections_in_box": len(raw),
        "detections_in_georgia_study_month": len(rows),
        "kept_as_fires": counts["fire"],
        "reclassified_as_industrial": counts["industrial"],
        "near_a_site_but_kept_as_fire_seen_once": len([r for r in near_site if r["class"] == "fire"]),
        "industrial_by_site": dict(by_site),
        "night_detections_percent": {
            "industrial": night_share([r for r in rows if r["class"] == "industrial"]),
            "fires": night_share([r for r in rows if r["class"] == "fire"]),
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    # --- chart ---
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    weeks = defaultdict(Counter)
    for r in rows:
        d = datetime.strptime(r["acq_date"], "%Y-%m-%d").date()
        week_start = study_start + timedelta(days=7 * ((d - study_start).days // 7))
        weeks[week_start][r["class"]] += 1
    labels = [f"{w:%d %b}" for w in sorted(weeks)]
    fires = [weeks[w]["fire"] for w in sorted(weeks)]
    industrial = [weeks[w]["industrial"] for w in sorted(weeks)]

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.2, 1]})
    left.bar(labels, fires, color="#DC2626", label="Kept as fire")
    left.bar(labels, industrial, bottom=fires, color="#4B5563", label="Likely industrial heat")
    left.set_title(f"Satellite detections in Georgia, {study_start:%d %b} – {STUDY_END:%d %b %Y}")
    left.set_xlabel("Week starting")
    left.set_ylabel("Detections")
    left.legend(frameon=False)
    for side in ("top", "right"):
        left.spines[side].set_visible(False)
        right.spines[side].set_visible(False)
    if by_site:
        names = list(by_site)
        right.barh(names, [by_site[n] for n in names], color="#4B5563")
        right.invert_yaxis()
        right.set_title("Reclassified detections by site")
        right.set_xlabel("Detections")
    else:
        right.text(0.5, 0.5, "No detections reclassified", ha="center", va="center")
        right.set_axis_off()
    fig.tight_layout()
    fig.savefig(OUT / "chart.png", dpi=150)
    print("chart saved")

    # --- satellite images for checking by eye: one per industrial site, and a few kept fires ---
    picks = {}
    for r in rows:
        if r["class"] == "industrial" and r["site"] not in picks:
            picks[r["site"]] = r
    fire_rows = sorted((r for r in rows if r["class"] == "fire"), key=lambda r: -float(r["frp"]))[:4]
    for i, r in enumerate(fire_rows):
        picks[f"fire-{i + 1}"] = r
    for name, r in picks.items():
        file = OUT / "satellite" / (name.lower().replace(" ", "-").replace(",", "") + ".jpg")
        satellite_image(float(r["latitude"]), float(r["longitude"]), file)
        print("satellite image:", file.name, r["latitude"], r["longitude"], r["class"])


if __name__ == "__main__":
    main()
