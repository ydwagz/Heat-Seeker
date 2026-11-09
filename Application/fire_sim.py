import random
import time

TREE = "🌲"
FIRE = "🔥"
ASH = "⚫"
GLASS = "🍾"
FLAMMABLE = "🛢️"
WINDS = ["north", "south", "east", "west"]
OPPOSITE = {"east": "west", "west": "east", "north": "south", "south": "north"}


PREDICTION_RUNS = 300
EXPOSURE_STEPS = 24
OBJECTS_PER_FOREST = 6
SCENARIOS = [
    ("natural", "Natural (heat only)", None),
    ("glass", "With glass objects", GLASS),
    ("flammable", "With easily flammable objects", FLAMMABLE),
]


def make_grid(size: int = 10, fire_at: tuple[int, int] | None = None) -> list[list[str]]:
    """A size x size forest with one burning tree (the centre by default)."""
    grid = [[TREE] * size for _ in range(size)]
    r, c = fire_at if fire_at else (size // 2, size // 2)
    grid[r][c] = FIRE
    return grid


def get_neighbors(grid, row, col):
    candidates = [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    return [(r, c) for r, c in candidates if 0 <= r < len(grid) and 0 <= c < len(grid[r])]


def spread(grid, wind, danger: float = 1.0, wind_strength: float = 1.0):
    downwind = 0.4 + 0.5 * wind_strength
    upwind = 0.4 - 0.3 * wind_strength
    crosswind = 0.4
    heat_scale = 0.3 + 0.7 * danger

    to_ignite = []
    to_burn_out = []

    for r in range(len(grid)):
        for c in range(len(grid[r])):
            if grid[r][c] != FIRE:
                continue
            to_burn_out.append((r, c))

            for nr, nc in get_neighbors(grid, r, c):
                cell = grid[nr][nc]
                if cell == FLAMMABLE:
                    chance = 0.95
                elif cell == TREE:
                    if nc > c:
                        direction = "east"
                    elif nc < c:
                        direction = "west"
                    elif nr < r:
                        direction = "north"
                    else:
                        direction = "south"

                    if direction == wind:
                        chance = downwind
                    elif direction == OPPOSITE[wind]:
                        chance = upwind
                    else:
                        chance = crosswind
                    chance *= heat_scale
                else:
                    continue

                if random.random() < chance:
                    to_ignite.append((nr, nc))

    for r, c in to_burn_out:
        grid[r][c] = ASH
    for r, c in to_ignite:
        grid[r][c] = FIRE


def has_fire(grid) -> bool:
    return any(cell == FIRE for row in grid for cell in row)


def count_trees(grid) -> int:
    return sum(cell == TREE for row in grid for cell in row)


def print_grid(grid):
    for row in grid:
        print("  ".join(row))
    print("------------------")

def _clamp(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def fire_danger(temp_c: float, rh: float) -> float:
    heat = _clamp((temp_c - 5) / 35)
    dryness = _clamp(1 - rh / 100)
    return heat * (0.3 + 0.7 * dryness)


def wind_toward(wind_from_deg: float) -> str:
    toward = (wind_from_deg + 180) % 360
    return ["north", "east", "south", "west"][round(toward / 90) % 4]


def wind_strength_from_speed(speed_kmh: float) -> float:
    return _clamp(speed_kmh / 30)


def sunlight(is_day: int, cloud_cover: float) -> float:
    return is_day * _clamp(1 - cloud_cover / 100)


def make_forest(size: int, obj: str | None, count: int) -> list[list[str]]:
    grid = [[TREE] * size for _ in range(size)]
    if obj:
        cells = random.sample([(r, c) for r in range(size) for c in range(size)], count)
        for r, c in cells:
            grid[r][c] = obj
    return grid


def ignite(grid, danger: float, sun: float):

    p_tree = 0.0005 * danger**4
    p_glass = 0.04 * sun * danger**2
    p_flammable = 0.03 * danger**2

    to_ignite = []
    for r in range(len(grid)):
        for c in range(len(grid[r])):
            cell = grid[r][c]
            if cell == TREE and random.random() < p_tree:
                to_ignite.append((r, c))
            elif cell == FLAMMABLE and random.random() < p_flammable:
                to_ignite.append((r, c))
            elif cell == GLASS and random.random() < p_glass:
                trees = [(nr, nc) for nr, nc in get_neighbors(grid, r, c) if grid[nr][nc] == TREE]
                if trees:
                    to_ignite.append(random.choice(trees))

    for r, c in to_ignite:
        grid[r][c] = FIRE


def start_fire(grid, obj: str | None):
    """Light one fire where this kind of forest would most likely catch:
    a flammable object, a tree next to a piece of glass, or the middle tree."""
    size = len(grid)
    if obj == FLAMMABLE:
        spots = [(r, c) for r in range(size) for c in range(size) if grid[r][c] == FLAMMABLE]
    elif obj == GLASS:
        spots = [
            (nr, nc)
            for r in range(size) for c in range(size) if grid[r][c] == GLASS
            for nr, nc in get_neighbors(grid, r, c) if grid[nr][nc] == TREE
        ]
    else:
        spots = []
    r, c = random.choice(spots) if spots else (size // 2, size // 2)
    grid[r][c] = FIRE


def simulate_forest(obj, danger, wind, wind_strength, sun, size=10):
    grid = make_forest(size, obj, OBJECTS_PER_FOREST)
    trees_before = count_trees(grid)
    for _ in range(EXPOSURE_STEPS):
        ignite(grid, danger, sun)
        spread(grid, wind, danger, wind_strength)
    while has_fire(grid):
        spread(grid, wind, danger, wind_strength)
    return grid, trees_before - count_trees(grid)


def predict_spread(
    temp_c: float,
    rh: float,
    wind_from_deg: float,
    wind_speed_kmh: float,
    is_day: int,
    cloud_cover: float,
    runs: int = PREDICTION_RUNS,
    size: int = 10,
) -> dict:
    danger = fire_danger(temp_c, rh)
    wind = wind_toward(wind_from_deg)
    strength = wind_strength_from_speed(wind_speed_kmh)
    sun = sunlight(is_day, cloud_cover)

    results = []
    for key, label, obj in SCENARIOS:
        outcomes = sorted(
            (simulate_forest(obj, danger, wind, strength, sun, size) for _ in range(runs)),
            key=lambda o: o[1],
        )
        burned = [b for _, b in outcomes]
        total_trees = count_trees(make_forest(size, obj, OBJECTS_PER_FOREST))
        avg = sum(burned) / runs
        results.append(
            {
                "key": key,
                "label": label,
                "avg_burned": avg,
                "avg_percent": 100 * avg / total_trees,
                "max_burned": burned[-1],
                "fire_chance": 100 * sum(b > 0 for b in burned) / runs,
                "total_trees": total_trees,
                "sample_grid": outcomes[runs // 2][0],
            }
        )

    return {
        "danger": danger,
        "wind": wind,
        "wind_strength": strength,
        "sun": sun,
        "results": results,
    }


if __name__ == "__main__":
    grid = make_grid(10, fire_at=(4, 4))
    while has_fire(grid):
        print_grid(grid)
        time.sleep(0.2)
        spread(grid, "south")
    print_grid(grid)
    print(f"{count_trees(grid)} Trees Survived")
