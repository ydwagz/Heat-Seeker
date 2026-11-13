"""The teaching forest simulation."""

import random

import pytest

from core.fire_sim import (
    ASH,
    FIRE,
    GLASS,
    TREE,
    count_trees,
    get_neighbors,
    has_fire,
    intensity_from_fwi,
    make_grid,
    predict_spread,
    spread,
    start_fire,
    wind_toward,
)


@pytest.mark.parametrize(
    "wind_from, pushes_toward",
    [(270, "east"), (90, "west"), (0, "south"), (180, "north"), (260, "east")],
)
def test_wind_pushes_fire_away_from_where_it_blows_from(wind_from, pushes_toward):
    assert wind_toward(wind_from) == pushes_toward


def test_intensity_follows_the_fwi_and_stays_between_0_and_1():
    assert intensity_from_fwi(0) == 0
    assert intensity_from_fwi(25) == pytest.approx(0.5)
    assert intensity_from_fwi(200) == 1


def test_fire_only_spreads_to_neighbouring_trees():
    random.seed(1)
    grid = make_grid(10, fire_at=(5, 5))
    spread(grid, "east", danger=1.0, wind_strength=1.0)
    assert grid[5][5] == ASH  # the first fire burned out
    burning = {(r, c) for r in range(10) for c in range(10) if grid[r][c] == FIRE}
    assert burning <= set(get_neighbors(grid, 5, 5))


def test_a_fire_always_burns_out():
    random.seed(2)
    grid = make_grid(10)
    steps = 0
    while has_fire(grid):
        spread(grid, "north", danger=1.0, wind_strength=1.0)
        steps += 1
        assert steps < 100
    assert count_trees(grid) < 100


def test_glass_fire_starts_on_a_tree_next_to_the_glass():
    grid = [[TREE] * 10 for _ in range(10)]
    grid[3][3] = GLASS
    start_fire(grid, GLASS)
    fires = [(r, c) for r in range(10) for c in range(10) if grid[r][c] == FIRE]
    assert len(fires) == 1 and fires[0] in get_neighbors(grid, 3, 3)


def test_higher_fire_weather_index_burns_more_of_the_forest():
    random.seed(3)
    calm = predict_spread(2, wind_from_deg=270, wind_speed_kmh=5, is_day=1, cloud_cover=0, runs=60)
    severe = predict_spread(60, wind_from_deg=270, wind_speed_kmh=25, is_day=1, cloud_cover=0, runs=60)
    calm_burned = {r["key"]: r["avg_burned"] for r in calm["results"]}
    severe_burned = {r["key"]: r["avg_burned"] for r in severe["results"]}
    for case in ("natural", "glass", "flammable"):
        assert severe_burned[case] > calm_burned[case]
