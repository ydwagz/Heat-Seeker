import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import flet as ft
import flet.canvas as cv

from fire_sim import (
    FLAMMABLE,
    GLASS,
    PREDICTION_RUNS,
    count_trees,
    has_fire,
    make_grid,
    predict_spread,
    spread,
)
from heat import fetch_current_weather, heat_risk_checker
from NASA_FIRMS_API import DAYS as FIRE_DAYS
from NASA_FIRMS_API import fetch_fires, iter_fires_in_georgia, place_name

APP_DIR = Path(__file__).parent
IMAGES = APP_DIR / "Images"
APP_ICON = IMAGES / "icon.ico"

WINDOW_WIDTH = 390
WINDOW_HEIGHT = 844
PAGE_PADDING = 20

GRID_SIZE = 10
STEP_SECONDS = 0.2
CELL = 32  # px per cell in the fire simulation grid
SAMPLE_CELL = 22  # px per cell in the prediction grids

# Palette
SMOKE = "#EEF0EC"  # page
PAPER = "#F8F9F6"  # input fields, tappable panels, bars
WHITE = "#FFFFFF"  # image tiles (flamable.jpg has a white background)
CHARCOAL = "#1F2622"  # text, primary buttons
LICHEN = "#67706A"  # secondary text
ASH = "#D3D8D2"  # lines
MOSS = "#DDE3DA"  # selected item in the navigation bar

FONT = "Bahnschrift"

# Heat risk bands, coolest to hottest: (level, colour, upper bound of heat index in °F)
RISK_BANDS = [
    ("Safe", "#3F7D5A", 80),
    ("Caution", "#C8A13A", 90),
    ("Extreme Caution", "#D9802E", 103),
    ("Danger", "#C2432A", 125),
    ("Extreme Danger", "#861E1E", 140),
]
RISK_COLORS = {level: color for level, color, _ in RISK_BANDS}
EMBER = RISK_COLORS["Danger"]
DANGER_COLORS = {
    "Low": RISK_COLORS["Safe"],
    "Moderate": RISK_COLORS["Caution"],
    "High": RISK_COLORS["Extreme Caution"],
    "Extreme": RISK_COLORS["Extreme Danger"],
}
SCALE_MIN_F = 40
SCALE_WIDTH = 300

# Prediction cases: key -> (image, short name, what it means)
SCENARIO_ZOOM = {"flammable": 1.7}  # flamable.jpg has wide white margins
SCENARIO_INFO = {
    "natural": (
        "sun.png",
        "Heat alone",
        "Trees catching fire from heat and dry air, with nothing else in the forest.",
    ),
    "glass": (
        "Glass.png",
        "Glass",
        f"Broken glass {GLASS} can focus sunlight onto dry leaves. It only starts fires in daylight.",
    ),
    "flammable": (
        "flamable.jpg",
        "Flammable litter",
        f"Fuel cans and rubbish {FLAMMABLE} catch fire far more easily than trees, then spread it.",
    ),
}

HEAT, FIRE_SPREAD, FIRES_HAPPENING = 0, 1, 2


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def text(value="", size=15, color=CHARCOAL, weight=None, text_align=ft.TextAlign.CENTER, **kwargs) -> ft.Text:
    return ft.Text(
        value, size=size, color=color, weight=weight, font_family=FONT, text_align=text_align, **kwargs
    )


def heading(value: str) -> ft.Text:
    return text(value, size=20, weight=ft.FontWeight.W_600)


def intro(value: str) -> ft.Text:
    """One line under a heading that tells a new user what the section is for."""
    return text(value, color=LICHEN)


def image(name: str, size: int) -> ft.Image:
    return ft.Image(src=str(IMAGES / name), width=size, height=size, fit=ft.BoxFit.CONTAIN)


def image_tile(name: str, size: int = 52, zoom: float = 1.0) -> ft.Container:
    """A picture on a white rounded tile. `zoom` > 1 crops away empty margins in the source image."""
    return ft.Container(
        image(name, int(size * 0.78 * zoom)),
        width=size,
        height=size,
        bgcolor=WHITE,
        border_radius=size * 0.25,
        alignment=ft.Alignment.CENTER,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def primary_button(label: str, on_click) -> ft.FilledButton:
    return ft.FilledButton(
        label,
        on_click=on_click,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DISABLED: ASH, ft.ControlState.DEFAULT: CHARCOAL},
            color={ft.ControlState.DISABLED: LICHEN, ft.ControlState.DEFAULT: PAPER},
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=20, vertical=14),
            text_style=ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600),
        ),
    )


def quiet_button(label: str, on_click) -> ft.TextButton:
    return ft.TextButton(
        label,
        on_click=on_click,
        style=ft.ButtonStyle(
            color=CHARCOAL,
            shape=ft.RoundedRectangleBorder(radius=10),
            text_style=ft.TextStyle(font_family=FONT, size=15),
        ),
    )


def number_field(label: str, value: str, suffix: str) -> ft.TextField:
    return ft.TextField(
        label=label,
        value=value,
        suffix=suffix,
        width=150,
        dense=True,
        bgcolor=PAPER,
        filled=True,
        border={
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(side=ft.BorderSide(1.5, CHARCOAL), border_radius=10),
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(side=ft.BorderSide(1, ASH), border_radius=10),
        },
        text_style=ft.TextStyle(font_family=FONT, size=17, color=CHARCOAL),
        label_style=ft.TextStyle(font_family=FONT, color=LICHEN),
        keyboard_type=ft.KeyboardType.NUMBER,
    )


def stat(label: str, value: ft.Text) -> ft.Control:
    return ft.Column(
        [text(label, size=12.5, color=LICHEN), value],
        spacing=0,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def spinner() -> ft.ProgressRing:
    return ft.ProgressRing(width=14, height=14, stroke_width=2, color=LICHEN)


def shortcut(icon: ft.IconData, title: ft.Text, detail: ft.Text, on_click) -> tuple[ft.Container, ft.Icon]:
    """A tappable row that takes the user to another screen. Returns (row, icon) so the icon can be recoloured."""
    glyph = ft.Icon(icon, color=LICHEN, size=22)
    title.text_align = detail.text_align = ft.TextAlign.LEFT
    row = ft.Container(
        on_click=on_click,
        ink=True,
        bgcolor=PAPER,
        border=ft.Border.all(1, ASH),
        border_radius=12,
        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
        content=ft.Row(
            [
                ft.Container(glyph, width=40, height=40, border_radius=20, bgcolor=SMOKE, alignment=ft.Alignment.CENTER),
                ft.Column([title, detail], spacing=1, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color=LICHEN, size=22),
            ],
            spacing=12,
        ),
    )
    return row, glyph


def compass(deg: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def emoji_cell(emoji: str, size: int) -> ft.Text:
    return ft.Text(emoji, size=size * 0.6, text_align=ft.TextAlign.CENTER)


def emoji_grid(cells: list[list[ft.Text]], size: int) -> ft.Control:
    """Lay emoji out in fixed-size boxes so they never shift when one changes."""
    rows = [
        ft.Row(
            [ft.Container(cell, width=size, height=size, alignment=ft.Alignment.CENTER) for cell in row],
            spacing=0,
            tight=True,
        )
        for row in cells
    ]
    return ft.Column(rows, spacing=0, tight=True)


# ---------------------------------------------------------------------------
# Heat screen
# ---------------------------------------------------------------------------


def scale_position(hi_f: float) -> float:
    """Where a heat index sits on the 5-band scale, 0 (coolest) to 1 (hottest)."""
    lower = SCALE_MIN_F
    for i, (_, _, upper) in enumerate(RISK_BANDS):
        if hi_f < upper or i == len(RISK_BANDS) - 1:
            fraction = min(max((hi_f - lower) / (upper - lower), 0), 1)
            return (i + fraction) / len(RISK_BANDS)
        lower = upper
    return 1.0


def heat_scale():
    """The five risk bands as one bar with a marker. Returns (control, set_value)."""
    segment = SCALE_WIDTH / len(RISK_BANDS)
    bands = ft.Row(
        [ft.Container(width=segment - 2, height=6, bgcolor=color, border_radius=3) for _, color, _ in RISK_BANDS],
        spacing=2,
        tight=True,
    )
    marker = ft.Container(
        width=14, height=14, border_radius=7, bgcolor=PAPER, border=ft.Border.all(3, CHARCOAL),
        left=0, top=0, visible=False,
    )
    bar = ft.Stack([ft.Container(bands, top=4), marker], width=SCALE_WIDTH, height=14)
    ends = ft.Row(
        [text("Safe", size=12.5, color=LICHEN), text("Extreme danger", size=12.5, color=LICHEN)],
        width=SCALE_WIDTH,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    def set_value(hi_f: float):
        marker.left = min(max(scale_position(hi_f) * SCALE_WIDTH - 7, 0), SCALE_WIDTH - 14)
        marker.visible = True

    return ft.Column([bar, ends], spacing=6, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER), set_value


class WeatherHeader:
    """Live Tbilisi weather at the top of the Heat screen."""

    def __init__(self, on_refresh):
        self.temp = text("–°", size=112, weight=ft.FontWeight.W_200)
        self.feels = text("Getting live weather…", size=17, color=LICHEN)
        self.scale, self.set_scale = heat_scale()
        self.humidity, self.wind, self.clouds, self.sky = text("–"), text("–"), text("–"), text("–")
        self.updated = text("", size=12.5, color=LICHEN)
        self.control = ft.Column(
            [
                ft.Row(
                    [
                        text("Tbilisi", size=20, weight=ft.FontWeight.W_600),
                        ft.IconButton(
                            ft.Icons.REFRESH, icon_color=LICHEN, icon_size=18,
                            tooltip="Refresh weather and prediction", on_click=on_refresh,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=0,
                ),
                ft.Container(self.temp, margin=ft.Margin.only(top=-18, bottom=-26)),
                self.feels,
                ft.Container(self.scale, margin=ft.Margin.only(top=14, bottom=20)),
                ft.Row([stat("Humidity", self.humidity), stat("Wind", self.wind)], spacing=24),
                ft.Row([stat("Clouds", self.clouds), stat("Sky", self.sky)], spacing=24),
                ft.Container(self.updated, margin=ft.Margin.only(top=6)),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        )

    def loading(self):
        self.updated.value = "Updating…"

    def show(self, w: dict):
        risk = heat_risk_checker(w["temperature_2m"], w["relative_humidity_2m"])
        self.temp.value = f"{w['temperature_2m']:.0f}°"
        self.feels.value = f"Feels like {risk['hi_c']:.0f}°, {risk['level'].lower()}"
        self.feels.color = RISK_COLORS[risk["level"]]
        self.set_scale(risk["hi_f"])
        self.humidity.value = f"{w['relative_humidity_2m']}%"
        self.wind.value = f"{w['wind_speed_10m']:.0f} km/h {compass(w['wind_direction_10m'])}"
        self.clouds.value = f"{w['cloud_cover']}%"
        self.sky.value = "Day" if w["is_day"] else "Night"
        # Open-Meteo reports UTC; show Georgian time
        local = datetime.fromisoformat(w["time"]).replace(tzinfo=timezone.utc).astimezone(GEORGIA_TZ)
        self.updated.value = f"Updated {local:%H:%M}"

    def show_error(self):
        self.feels.value = "Live weather is unavailable. Check your connection and refresh."
        self.feels.color = LICHEN
        self.updated.value = ""


def heat_panel(page: ft.Page) -> ft.Control:
    temp_field = number_field("Temperature", "35", "°C")
    rh_field = number_field("Humidity", "60", "%")
    message = text("", color=LICHEN)
    result = text("", size=28, weight=ft.FontWeight.W_300)
    level_dot = ft.Container(width=10, height=10, border_radius=5, visible=False)
    level = text("", size=17, weight=ft.FontWeight.W_600)

    def show_risk():
        try:
            temp_c = float(temp_field.value)
            rh = float(rh_field.value)
        except ValueError:
            message.value = "Enter a number for temperature and humidity."
            page.update()
            return
        risk = heat_risk_checker(temp_c, rh)
        result.value = f"{risk['hi_c']:.0f}°C  /  {risk['hi_f']:.0f}°F"
        level.value = risk["level"]
        level.color = level_dot.bgcolor = RISK_COLORS[risk["level"]]
        level_dot.visible = True
        page.update()

    def on_check(e):
        message.value = ""
        show_risk()

    async def on_fetch(e):
        message.value = "Getting live weather…"
        page.update()
        try:
            current = await asyncio.to_thread(fetch_current_weather)
        except Exception:
            message.value = "Live weather is unavailable. Enter the values yourself."
            page.update()
            return
        temp_field.value = str(current["temperature_2m"])
        rh_field.value = str(current["relative_humidity_2m"])
        message.value = "Filled in from live weather."
        show_risk()

    return ft.Column(
        [
            heading("Check any temperature"),
            intro("See how hot it feels and how risky that is."),
            ft.Container(height=6),
            ft.Row([temp_field, rh_field], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row(
                [primary_button("Check", on_check), quiet_button("Use live weather", on_fetch)],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            message,
            result,
            ft.Row(
                [level_dot, level], spacing=8,
                alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Fire spread screen
# ---------------------------------------------------------------------------


def danger_label(danger: float) -> str:
    if danger < 0.15:
        return "Low"
    if danger < 0.4:
        return "Moderate"
    if danger < 0.7:
        return "High"
    return "Extreme"


def scenario_card(result: dict, selected: bool, on_click) -> ft.Control:
    """One case in the side-by-side comparison: picture, share of forest burned, name."""
    picture, name, _ = SCENARIO_INFO[result["key"]]
    return ft.Container(
        expand=True,
        on_click=on_click,
        ink=True,
        bgcolor=PAPER,
        border_radius=12,
        border=ft.Border.all(2, CHARCOAL) if selected else ft.Border.all(1, ASH),
        padding=ft.Padding.symmetric(horizontal=6, vertical=12),
        content=ft.Column(
            [
                image_tile(picture, 52, SCENARIO_ZOOM.get(result["key"], 1.0)),
                text(f"{result['avg_percent']:.0f}%", size=26, weight=ft.FontWeight.W_300),
                # Fixed height so a two-line name doesn't make one card taller than the others
                ft.Container(
                    text(name, size=13, weight=ft.FontWeight.W_600 if selected else None),
                    height=34,
                    alignment=ft.Alignment.TOP_CENTER,
                ),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


class Prediction:
    """Runs by itself whenever new weather arrives; nothing to press."""

    def __init__(self, page: ft.Page, on_danger):
        self.page = page
        self.on_danger = on_danger  # called with "Low" / "Moderate" / ... once a prediction is ready
        self.running = False
        self.results: list[dict] = []
        self.selected = "natural"

        self.status = text("Waiting for live weather…", color=LICHEN)
        self.status_row = ft.Row([spinner(), self.status], spacing=8, alignment=ft.MainAxisAlignment.CENTER)
        self.danger = text("", size=17, weight=ft.FontWeight.W_600)
        self.conditions = text("", size=13.5, color=LICHEN)
        self.cards = ft.Row(spacing=8)
        self.detail = ft.Column(spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.control = ft.Column(
            [
                heading("Fire spread"),
                intro("What would happen to a forest in Tbilisi's weather right now. Updates by itself."),
                ft.Container(height=4),
                self.status_row,
                self.danger,
                self.conditions,
                ft.Container(self.cards, margin=ft.Margin.only(top=8)),
                self.detail,
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def show_error(self, message: str):
        self.status_row.visible = True
        self.status_row.controls[0].visible = False
        self.status.value = message

    async def run(self, w: dict):
        if self.running:
            return
        self.running = True
        self.status_row.visible = True
        self.status_row.controls[0].visible = True
        self.status.value = f"Simulating {PREDICTION_RUNS} forests for each case…"
        self.page.update()

        p = await asyncio.to_thread(
            predict_spread,
            w["temperature_2m"], w["relative_humidity_2m"],
            w["wind_direction_10m"], w["wind_speed_10m"],
            w["is_day"], w["cloud_cover"],
        )
        level = danger_label(p["danger"])
        if not w["is_day"]:
            light = "night, so glass can't focus sunlight"
        elif p["sun"] < 0.05:
            light = "overcast, so glass can't focus sunlight"
        else:
            light = f"{p['sun'] * 100:.0f}% sunshine"
        self.status_row.visible = False
        self.danger.value = f"Fire danger: {level.lower()}"
        self.danger.color = DANGER_COLORS[level]
        self.conditions.value = (
            f"{w['temperature_2m']:.0f}°C, {w['relative_humidity_2m']}% humidity, wind "
            f"{w['wind_speed_10m']:.0f} km/h pushing fire {p['wind']}, {light}. Tap a case to see a typical forest."
        )
        self.results = p["results"]
        self.render()
        self.running = False
        self.on_danger(level)
        self.page.update()

    def select(self, key: str):
        self.selected = key
        self.render()
        self.page.update()

    def render(self):
        self.cards.controls = [
            scenario_card(r, r["key"] == self.selected, lambda e, k=r["key"]: self.select(k)) for r in self.results
        ]
        result = next(r for r in self.results if r["key"] == self.selected)
        _, name, explanation = SCENARIO_INFO[result["key"]]
        cells = [[emoji_cell(emoji, SAMPLE_CELL) for emoji in row] for row in result["sample_grid"]]
        self.detail.controls = [
            ft.Container(height=6),
            text(name, size=17, weight=ft.FontWeight.W_600),
            text(explanation, color=LICHEN),
            text(
                f"On average {result['avg_burned']:.0f} of {result['total_trees']} trees burn. "
                f"A fire starts in {result['fire_chance']:.0f}% of forests; "
                f"the worst one lost {result['max_burned']} trees.",
                size=13.5,
            ),
            ft.Container(emoji_grid(cells, SAMPLE_CELL), margin=ft.Margin.only(top=6)),
        ]


def wind_picker() -> ft.SegmentedButton:
    return ft.SegmentedButton(
        width=188,
        selected=["south"],
        show_selected_icon=False,
        segments=[
            ft.Segment(value=value, label=label)
            for value, label in [("north", "N"), ("east", "E"), ("south", "S"), ("west", "W")]
        ],
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.SELECTED: CHARCOAL, ft.ControlState.DEFAULT: PAPER},
            color={ft.ControlState.SELECTED: PAPER, ft.ControlState.DEFAULT: CHARCOAL},
            side=ft.BorderSide(1, ASH),
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=0),
            visual_density=ft.VisualDensity.COMPACT,
            text_style=ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600),
        ),
    )


def fire_panel(page: ft.Page) -> ft.Control:
    wind = wind_picker()
    cells = [[emoji_cell("", CELL) for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    summary = text("")

    def render(grid):
        for row_cells, row in zip(cells, grid):
            for cell, emoji in zip(row_cells, row):
                cell.value = emoji

    async def on_start(e):
        start_button.disabled = True
        wind.disabled = True
        summary.value = "Burning…"
        grid = make_grid(GRID_SIZE)
        direction = wind.selected[0]
        while has_fire(grid):
            render(grid)
            page.update()
            await asyncio.sleep(STEP_SECONDS)
            spread(grid, direction)
        render(grid)
        summary.value = f"{count_trees(grid)} of {GRID_SIZE * GRID_SIZE - 1} trees survived."
        start_button.disabled = False
        wind.disabled = False
        page.update()

    start_button = primary_button("Start fire", on_start)
    render(make_grid(GRID_SIZE))

    return ft.Column(
        [
            heading("Watch a fire spread"),
            intro("Pick where the wind blows, then start a fire in the middle of the forest."),
            ft.Container(height=6),
            ft.Row([wind, start_button], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(emoji_grid(cells, CELL), margin=ft.Margin.symmetric(vertical=8)),
            summary,
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Fires happening screen
# ---------------------------------------------------------------------------

GEORGIA_TZ = timezone(timedelta(hours=4))  # Georgia is UTC+4 all year
GEORGIA = json.loads((APP_DIR / "Data" / "georgia_outline.json").read_text(encoding="utf-8"))
# (name, lat, lon, label side). Tbilisi's label sits left, clear of the fire-prone east.
MAP_CITIES = [
    ("Tbilisi", 41.7151, 44.8271, "left"),
    ("Kutaisi", 42.2679, 42.6946, "right"),
    ("Batumi", 41.6168, 41.6367, "right"),
]
CITY_LABEL_WIDTH = 60
PIN = 12

# Equirectangular projection fitted to Georgia's outline; longitude is squeezed by
# cos(latitude) so the country keeps its real proportions.
MAP_WIDTH = 330
MAP_PAD = 8
_LONS = [lon for lon, _ in GEORGIA["outline"]]
_LATS = [lat for _, lat in GEORGIA["outline"]]
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = min(_LONS), max(_LONS), min(_LATS), max(_LATS)
LON_SQUEEZE = math.cos(math.radians((LAT_MIN + LAT_MAX) / 2))
MAP_SCALE = (MAP_WIDTH - 2 * MAP_PAD) / ((LON_MAX - LON_MIN) * LON_SQUEEZE)
MAP_HEIGHT = round((LAT_MAX - LAT_MIN) * MAP_SCALE + 2 * MAP_PAD)


def map_xy(lat: float, lon: float) -> tuple[float, float]:
    x = MAP_PAD + (lon - LON_MIN) * LON_SQUEEZE * MAP_SCALE
    y = MAP_PAD + (LAT_MAX - lat) * MAP_SCALE
    return x, y


def georgia_map() -> ft.Stack:
    """Georgia's outline with a few cities for orientation. Pins are added to the returned Stack."""
    points = [map_xy(lat, lon) for lon, lat in GEORGIA["outline"]]
    outline = [cv.Path.MoveTo(*points[0]), *[cv.Path.LineTo(x, y) for x, y in points[1:]], cv.Path.Close()]
    shapes = [
        cv.Path(outline, paint=ft.Paint(color=PAPER, style=ft.PaintingStyle.FILL)),
        cv.Path(
            outline,
            paint=ft.Paint(color=LICHEN, style=ft.PaintingStyle.STROKE, stroke_width=1.2, stroke_join=ft.StrokeJoin.ROUND),
        ),
    ]
    labels = []
    for name, lat, lon, side in MAP_CITIES:
        x, y = map_xy(lat, lon)
        shapes.append(cv.Circle(x, y, 2.5, paint=ft.Paint(color=LICHEN)))
        left = x + 5 if side == "right" else x - 5 - CITY_LABEL_WIDTH
        align = ft.TextAlign.LEFT if side == "right" else ft.TextAlign.RIGHT
        labels.append(
            ft.Text(
                name, size=11, color=LICHEN, font_family=FONT, left=left, top=y - 8,
                width=CITY_LABEL_WIDTH, text_align=align,
            )
        )
    return ft.Stack(
        [cv.Canvas(shapes, width=MAP_WIDTH, height=MAP_HEIGHT), *labels],
        width=MAP_WIDTH,
        height=MAP_HEIGHT,
        clip_behavior=ft.ClipBehavior.NONE,
    )


def fire_pin(lat: float, lon: float, tooltip: str) -> tuple[ft.Control, ft.Container]:
    """A fire marker. Returns (pin, ring); the ring is what pings."""
    x, y = map_xy(lat, lon)
    ring = ft.Container(width=PIN, height=PIN, border_radius=PIN / 2, border=ft.Border.all(2, EMBER), opacity=0.7)
    dot = ft.Container(
        width=PIN, height=PIN, border_radius=PIN / 2, bgcolor=EMBER, border=ft.Border.all(2, PAPER), tooltip=tooltip
    )
    pin = ft.Stack(
        [ring, dot], left=x - PIN / 2, top=y - PIN / 2, width=PIN, height=PIN, clip_behavior=ft.ClipBehavior.NONE
    )
    return pin, ring


def detected_at(fire: dict) -> datetime:
    """FIRMS reports UTC date + HHMM; convert to Georgian time."""
    hhmm = fire["acq_time"].zfill(4)
    utc = datetime.strptime(f"{fire['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    return utc.astimezone(GEORGIA_TZ)


def when_label(moment: datetime) -> str:
    today = datetime.now(GEORGIA_TZ).date()
    if moment.date() == today:
        day = "Today"
    elif moment.date() == today - timedelta(days=1):
        day = "Yesterday"
    else:
        day = f"{moment.day} {moment:%b}"
    return f"{day}, {moment:%H:%M}"


def fire_log_entry(fire: dict, detections: int) -> ft.Control:
    lat, lon = fire["latitude"], fire["longitude"]
    details = f"Fire power {float(fire['frp']):.1f} MW"
    if detections > 1:
        details += f", seen {detections} times"
    return ft.Container(
        padding=ft.Padding.symmetric(vertical=12),
        border=ft.Border.only(bottom=ft.BorderSide(1, ASH)),
        content=ft.Column(
            [
                text(when_label(detected_at(fire)), weight=ft.FontWeight.W_600),
                text(place_name(fire["address"])),
                text(details, size=12.5, color=LICHEN),
                ft.TextButton(
                    "Open in Google Maps",
                    url=f"https://www.google.com/maps?q={lat},{lon}",
                    style=ft.ButtonStyle(color=EMBER, text_style=ft.TextStyle(font_family=FONT, size=13.5)),
                ),
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def fires_panel(page: ft.Page, on_count):
    """Map + log of fires in Georgia.

    Returns (control, async loader, async ping loop, visibility setter). `on_count` is
    called with the number of fires (or None if the data couldn't be loaded).
    """
    fire_map = georgia_map()
    base_layers = list(fire_map.controls)
    status = text("Getting satellite data…", color=LICHEN)
    log = ft.Column(spacing=0, width=MAP_WIDTH, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    rings: list[ft.Container] = []
    state = {"loading": False, "visible": False}

    async def load(e=None):
        if state["loading"]:
            return
        state["loading"] = True
        refresh.disabled = True
        fire_map.controls = list(base_layers)
        rings.clear()
        log.controls = []
        status.value = "Getting satellite data from NASA…"
        page.update()

        failed = False
        try:
            fires = await asyncio.to_thread(fetch_fires)
        except Exception:
            fires, failed = [], True
            status.value = "Couldn't reach NASA FIRMS. Check your connection, then refresh."

        # One fire usually shows up as several detections a few hundred metres apart:
        # group them by ~1 km cell, keep the newest, and count the rest.
        groups: dict[tuple, dict] = {}
        if fires:
            status.value = f"Checking where {len(fires)} satellite detections are…"
            page.update()
            located = iter_fires_in_georgia(fires)
            while True:
                try:
                    fire = await asyncio.to_thread(next, located, None)
                except Exception:
                    failed = True
                    status.value = "Couldn't look up fire locations. Refresh to try again."
                    break
                if fire is None:
                    break
                lat, lon = float(fire["latitude"]), float(fire["longitude"])
                cell = (round(lat, 2), round(lon, 2))
                group = groups.get(cell)
                if group is None:
                    pin, ring = fire_pin(lat, lon, f"{place_name(fire['address'])}\n{when_label(detected_at(fire))}")
                    fire_map.controls.append(pin)
                    rings.append(ring)
                    groups[cell] = {"fire": fire, "count": 1}
                else:
                    group["count"] += 1
                    if detected_at(fire) > detected_at(group["fire"]):
                        group["fire"] = fire
                newest_first = sorted(groups.values(), key=lambda g: detected_at(g["fire"]), reverse=True)
                log.controls = [fire_log_entry(g["fire"], g["count"]) for g in newest_first]
                status.value = f"{len(groups)} found so far…"
                page.update()

        if not failed:
            if groups:
                noun = "fire" if len(groups) == 1 else "fires"
                status.value = f"{len(groups)} {noun} detected in Georgia in the last {FIRE_DAYS} days."
            else:
                status.value = f"No fires detected in Georgia in the last {FIRE_DAYS} days."
        state["loading"] = False
        refresh.disabled = False
        on_count(None if failed else len(groups))
        page.update()

    async def ping_forever():
        """Expanding, fading ring around every pin while this screen is open."""
        grow = ft.Animation(duration=1200, curve=ft.AnimationCurve.EASE_OUT)
        reset = ft.Animation(duration=0)
        while True:
            if not (state["visible"] and rings):
                await asyncio.sleep(0.5)
                continue
            for ring in rings:
                ring.animate_scale = ring.animate_opacity = grow
                ring.scale, ring.opacity = 3, 0
            page.update()
            await asyncio.sleep(1.3)
            for ring in rings:
                ring.animate_scale = ring.animate_opacity = reset
                ring.scale, ring.opacity = 1, 0.7
            page.update()
            await asyncio.sleep(0.4)

    def set_visible(visible: bool):
        state["visible"] = visible

    refresh = ft.IconButton(ft.Icons.REFRESH, icon_color=LICHEN, icon_size=18, tooltip="Check again", on_click=load)

    control = ft.Column(
        [
            ft.Row([heading("Fires happening"), refresh], alignment=ft.MainAxisAlignment.CENTER, spacing=0),
            intro(f"Fires spotted by NASA satellites in Georgia over the last {FIRE_DAYS} days."),
            ft.Container(fire_map, margin=ft.Margin.symmetric(vertical=12)),
            status,
            log,
            ft.Container(
                text("Fire data: NASA FIRMS. Map: © OpenStreetMap contributors.", size=11, color=LICHEN),
                margin=ft.Margin.only(top=16),
            ),
        ],
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return control, load, ping_forever, set_visible


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def screen(*panels: ft.Control) -> ft.Container:
    """Pad panels, separate them with a hairline, and let the screen scroll on its own."""
    controls = []
    for panel in panels:
        if controls:
            controls.append(ft.Divider(height=48, color=ASH))
        controls.append(panel)
    return ft.Container(
        expand=True,
        content=ft.Column(
            controls, scroll=ft.ScrollMode.AUTO, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER
        ),
        padding=ft.Padding.only(left=PAGE_PADDING, right=PAGE_PADDING, top=20, bottom=32),
    )


def top_bar() -> ft.Control:
    return ft.Container(
        bgcolor=PAPER,
        border=ft.Border.only(bottom=ft.BorderSide(1, ASH)),
        padding=ft.Padding.symmetric(vertical=10),
        content=ft.Row(
            [image("Sun_Cloud.png", 30), text("Heat Seeker", size=18, weight=ft.FontWeight.W_600)],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        ),
    )


def main(page: ft.Page):
    page.title = "Heat Seeker"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = SMOKE
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        font_family=FONT,
        scaffold_bgcolor=SMOKE,
        color_scheme=ft.ColorScheme(
            primary=CHARCOAL,
            on_primary=PAPER,
            surface=SMOKE,
            on_surface=CHARCOAL,
            on_surface_variant=LICHEN,
            outline=ASH,
            outline_variant=ASH,
        ),
        navigation_bar_theme=ft.NavigationBarTheme(
            label_text_style=ft.TextStyle(font_family=FONT, size=12.5, weight=ft.FontWeight.W_600, color=CHARCOAL),
        ),
    )
    page.window.width = WINDOW_WIDTH
    page.window.height = WINDOW_HEIGHT
    page.window.resizable = False
    page.window.maximizable = False
    page.window.icon = str(APP_ICON)

    # --- Navigation -------------------------------------------------------
    screens: list[ft.Container] = []

    def go_to(index: int):
        nav.selected_index = index
        for i, s in enumerate(screens):
            s.visible = i == index
        show_fires(index == FIRES_HAPPENING)
        page.update()

    # --- Heat screen shortcuts (they update as data arrives) --------------
    danger_title = text("Working out today's fire danger…", weight=ft.FontWeight.W_600)
    danger_row, danger_icon = shortcut(
        ft.Icons.LOCAL_FIRE_DEPARTMENT, danger_title,
        text("See how a fire would spread", size=13, color=LICHEN), lambda e: go_to(FIRE_SPREAD),
    )
    fires_title = text("Checking for fires in Georgia…", weight=ft.FontWeight.W_600)
    fires_row, fires_icon = shortcut(
        ft.Icons.MAP_OUTLINED, fires_title,
        text(f"Satellite data from the last {FIRE_DAYS} days", size=13, color=LICHEN),
        lambda e: go_to(FIRES_HAPPENING),
    )

    def show_danger(level: str):
        danger_title.value = f"Fire danger today: {level.lower()}"
        danger_icon.color = DANGER_COLORS[level]

    def show_fire_count(count):
        if count is None:
            fires_title.value = "Fire data unavailable right now"
        elif count == 0:
            fires_title.value = "No fires in Georgia right now"
        else:
            fires_title.value = f"{count} {'fire' if count == 1 else 'fires'} in Georgia"
        fires_icon.color = EMBER if count else LICHEN

    # --- Screens ------------------------------------------------------------
    prediction = Prediction(page, on_danger=show_danger)
    fires, load_fires, ping_fires, show_fires = fires_panel(page, on_count=show_fire_count)

    async def refresh_weather(e=None):
        header.loading()
        page.update()
        try:
            w = await asyncio.to_thread(fetch_current_weather)
        except Exception:
            header.show_error()
            prediction.show_error("Live weather is unavailable, so there's no prediction yet. Refresh on the Heat screen.")
            danger_title.value = "Fire danger unavailable right now"
            page.update()
            return
        header.show(w)
        page.update()
        await prediction.run(w)

    header = WeatherHeader(on_refresh=refresh_weather)
    shortcuts = ft.Column([danger_row, fires_row], spacing=10)

    screens.extend(
        [
            screen(ft.Column([header.control, ft.Container(height=20), shortcuts], spacing=0), heat_panel(page)),
            screen(prediction.control, fire_panel(page)),
            screen(fires),
        ]
    )
    for s in screens[1:]:
        s.visible = False

    nav = ft.NavigationBar(
        selected_index=HEAT,
        bgcolor=PAPER,
        indicator_color=MOSS,
        label_behavior=ft.NavigationBarLabelBehavior.ALWAYS_SHOW,
        border=ft.Border.only(top=ft.BorderSide(1, ASH)),
        on_change=lambda e: go_to(e.control.selected_index),
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.THERMOSTAT_OUTLINED, selected_icon=ft.Icons.THERMOSTAT, label="Heat"),
            ft.NavigationBarDestination(icon=ft.Icons.FOREST_OUTLINED, selected_icon=ft.Icons.FOREST, label="Fire spread"),
            ft.NavigationBarDestination(icon=ft.Icons.MAP_OUTLINED, selected_icon=ft.Icons.MAP, label="Fires Happening"),
        ],
    )
    page.navigation_bar = nav
    page.add(ft.Column([top_bar(), *screens], expand=True, spacing=0))

    page.run_task(page.window.center)
    page.run_task(refresh_weather)
    page.run_task(load_fires)
    page.run_task(ping_fires)


if __name__ == "__main__":
    ft.run(main)
