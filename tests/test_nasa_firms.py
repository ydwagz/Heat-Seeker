"""NASA FIRMS helpers: the Georgia filter and the industrial heat check (no network used)."""

import pytest

from core import nasa_firms as firms


def detection(lat, lon, date="2026-11-10"):
    return {"latitude": str(lat), "longitude": str(lon), "acq_date": date, "acq_time": "2250", "frp": "1.0"}


def test_distance_tbilisi_to_kutaisi():
    # About 186 km in a straight line
    assert firms.distance_km(41.7151, 44.8271, 42.2679, 42.6946) == pytest.approx(186, abs=5)


def test_hot_spot_next_to_zestaponi_plant_is_near_an_industrial_site():
    site = firms.nearby_site(42.1242, 43.01351)
    assert site is not None and site["en"] == "Zestaponi Ferroalloy Factory"


def test_field_fire_in_abasha_is_not_near_any_industrial_site():
    assert firms.nearby_site(42.15375, 42.07586) is None


def test_days_seen_counts_different_days_at_the_same_spot_only():
    history = [
        detection(42.1242, 43.0135, "2026-10-26"),
        detection(42.1250, 43.0140, "2026-10-26"),  # same day: counts once
        detection(42.1239, 43.0121, "2026-10-29"),
        detection(42.1242, 43.0135, "2026-11-10"),
        detection(42.2000, 43.2000, "2026-11-01"),  # far away: ignored
    ]
    assert firms.days_seen(42.1242, 43.0135, history) == 3


def test_georgia_filter_keeps_only_detections_inside_georgia(monkeypatch):
    countries = {(41.7, 44.8): "ge", (41.2, 44.9): "am", (42.5, 45.9): "ru"}
    lookups = []

    def fake_look_up(lat, lon, lang="en"):
        lookups.append((lat, lon))
        return {"country_code": countries[(round(float(lat), 1), round(float(lon), 1))], "village": "X"}

    monkeypatch.setattr(firms, "look_up_address", fake_look_up)
    monkeypatch.setattr(firms.time, "sleep", lambda seconds: None)  # no 1-second Nominatim pauses in tests

    fires = [
        detection(41.70, 44.80),
        detection(41.701, 44.801),  # same ~1 km cell: no second look-up
        detection(41.20, 44.90),  # Armenia
        detection(42.50, 45.90),  # Russia
    ]
    kept = list(firms.iter_fires_in_georgia(fires))
    assert len(kept) == 2
    assert all(f["address"]["country_code"] == "ge" for f in kept)
    assert len(lookups) == 3


def test_place_name_prefers_the_settlement_and_region():
    assert firms.place_name({"village": "Sagarejo", "state": "Kakheti"}) == "Sagarejo, Kakheti"
    assert firms.place_name({}) == "Georgia"
