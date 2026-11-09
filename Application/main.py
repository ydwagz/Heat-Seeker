import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import flet as ft
import flet.canvas as cv

from fire_sim import (
    ASH,
    FIRE,
    FLAMMABLE,
    GLASS,
    PREDICTION_RUNS,
    TREE,
    count_trees,
    has_fire,
    make_grid,
    predict_spread,
    spread,
)
from heat import fetch_current_weather, heat_risk_checker, search_places
from NASA_FIRMS_API import DAYS as FIRE_DAYS
from NASA_FIRMS_API import fetch_fires, iter_fires_in_georgia, place_name

APP_DIR = Path(__file__).parent
IMAGES = APP_DIR / "Images"
APP_ICON = IMAGES / "icon.ico"

WINDOW_WIDTH = 390
WINDOW_HEIGHT = 844
PAGE_PADDING = 16

GRID_SIZE = 10
STEP_SECONDS = 0.2
CELL = 32  # px per cell in the fire simulation grid
SAMPLE_CELL = 26  # px per cell in the prediction forest

# Palette (taken from the Heat-Seeker mockup)
CANVAS = "#F7F8F7"  # page
PANEL = "#F0F2F0"  # weather panel, status panels
CARD = "#FFFFFF"  # cards
LINE = "#E1E4E1"  # card borders, dividers
FOREST = "#1E6B42"  # brand green: logo, active navigation, icons
MINT = "#E6F0E8"  # green-tinted panels and buttons
INK = "#1C201D"  # text
MUTED = "#5E6661"  # secondary text
FLAME = "#E5482F"  # fires

FONT = "Segoe UI"

# Heat risk bands, coolest to hottest: (level, colour, upper bound of heat index in °F)
RISK_BANDS = [
    ("Safe", "#2F8A55", 80),
    ("Caution", "#E2B23A", 90),
    ("Extreme Caution", "#F08A2B", 103),
    ("Danger", "#E5482F", 125),
    ("Extreme Danger", "#B3261E", 140),
]
RISK_COLORS = {level: color for level, color, _ in RISK_BANDS}
SCALE_MIN_F = 40
SCALE_WIDTH = 300

# Fire danger levels from the prediction: colour, panel tint, advice
DANGER = {
    "Low": ("#2F8A55", MINT, "Take normal precautions."),
    "Moderate": ("#B98A12", "#FBF3DC", "Be careful with campfires and barbecues."),
    "High": ("#D9661E", "#FCE9DA", "Avoid open fires outdoors."),
    "Extreme": ("#B3261E", "#F9DEDB", "Don't light any fires outdoors."),
}

# Prediction cases: key -> (icon image, short name, what it means)
SCENARIO_INFO = {
    "natural": ("sun_icon.png", "Heat alone", "Trees catching fire from heat and dry air, with nothing else in the forest."),
    "glass": ("glass_icon.png", "Glass", "Broken glass can focus sunlight onto dry leaves. It only starts fires in daylight."),
    "flammable": (
        "flammable_litter_icon.png",
        "Flammable litter",
        "Fuel cans and rubbish catch fire far more easily than trees, then spread it.",
    ),
}

GEORGIAN_CITIES = [
    ("Tbilisi", 41.7151, 44.8271),
    ("Kutaisi", 42.2679, 42.6946),
    ("Batumi", 41.6168, 41.6367),
    ("Rustavi", 41.5495, 44.9932),
    ("Gori", 41.9842, 44.1158),
    ("Zugdidi", 42.5088, 41.8709),
    ("Telavi", 41.9198, 45.4731),
    ("Borjomi", 41.8383, 43.3790),
]
CITY_REGIONS = {
    "Tbilisi": "Tbilisi", "Kutaisi": "Imereti", "Batumi": "Adjara", "Rustavi": "Kvemo Kartli",
    "Gori": "Shida Kartli", "Zugdidi": "Samegrelo-Zemo Svaneti", "Telavi": "Kakheti", "Borjomi": "Samtskhe-Javakheti",
}

HOME, FIRE_SPREAD, FIRES_HAPPENING = 0, 1, 2


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def text(value="", size=14, color=INK, weight=None, text_align=ft.TextAlign.CENTER, **kwargs) -> ft.Text:
    return ft.Text(value, size=size, color=color, weight=weight, font_family=FONT, text_align=text_align, **kwargs)


def span(value: str, bold: bool = False, color: str | None = None) -> ft.TextSpan:
    return ft.TextSpan(value, ft.TextStyle(weight=ft.FontWeight.W_700 if bold else None, color=color))


def title(value: str) -> ft.Text:
    return text(value, size=28, weight=ft.FontWeight.W_600)


def intro(value: str) -> ft.Text:
    """The line under a screen title that tells a new user what the screen is for."""
    return text(value, color=MUTED)


def image(name: str, width: float, height: float | None = None) -> ft.Image:
    return ft.Image(src=str(IMAGES / name), width=width, height=height or width, fit=ft.BoxFit.CONTAIN)


def card(content: ft.Control, **kwargs) -> ft.Container:
    return ft.Container(
        content=content,
        bgcolor=CARD,
        border=ft.Border.all(1, LINE),
        border_radius=14,
        **kwargs,
    )


def primary_button(label: str, on_click) -> ft.FilledButton:
    return ft.FilledButton(
        label,
        on_click=on_click,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DISABLED: LINE, ft.ControlState.DEFAULT: FOREST},
            color={ft.ControlState.DISABLED: MUTED, ft.ControlState.DEFAULT: CARD},
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=20, vertical=14),
            text_style=ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600),
        ),
    )


def quiet_button(label: str, on_click) -> ft.TextButton:
    return ft.TextButton(
        label,
        on_click=on_click,
        style=ft.ButtonStyle(
            color=FOREST,
            shape=ft.RoundedRectangleBorder(radius=12),
            text_style=ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600),
        ),
    )


def input_field(label: str, value: str = "", suffix: str | None = None, width: float | None = None, **kwargs) -> ft.TextField:
    return ft.TextField(
        label=label,
        value=value,
        suffix=suffix,
        width=width,
        dense=True,
        bgcolor=CARD,
        filled=True,
        border={
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(side=ft.BorderSide(1.5, FOREST), border_radius=12),
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(side=ft.BorderSide(1, LINE), border_radius=12),
        },
        text_style=ft.TextStyle(font_family=FONT, size=16, color=INK),
        label_style=ft.TextStyle(font_family=FONT, color=MUTED),
        **kwargs,
    )


def compass(deg: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def to_unit(celsius: float, unit: str) -> float:
    return celsius * 9 / 5 + 32 if unit == "F" else celsius


# --- Forest grids drawn with icons ------------------------------------------


def forest_symbol(symbol: str, size: int) -> ft.Control | None:
    if symbol == TREE:
        return ft.Icon(ft.Icons.PARK, color=FOREST, size=size * 0.82)
    if symbol == FIRE:
        return ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=FLAME, size=size * 0.82)
    if symbol == ASH:
        return ft.Icon(ft.Icons.PARK, color="#C3C8C4", size=size * 0.82)  # burned tree
    if symbol == GLASS:
        return image("glass_icon.png", size * 0.5, size * 0.72)
    if symbol == FLAMMABLE:
        return image("flammable_litter_icon.png", size * 0.66, size * 0.74)
    return None


def forest_grid(rows: int, cols: int, size: int) -> tuple[ft.Control, list[list[ft.Container]]]:
    """Fixed-size cells so nothing shifts when a cell changes. Fill with `paint_forest`."""
    cells = [
        [ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER) for _ in range(cols)]
        for _ in range(rows)
    ]
    control = ft.Column([ft.Row(r, spacing=0, tight=True) for r in cells], spacing=0, tight=True)
    return control, cells


def paint_forest(cells: list[list[ft.Container]], grid: list[list[str]], size: int):
    for row_cells, row in zip(cells, grid):
        for cell, symbol in zip(row_cells, row):
            if cell.data != symbol:  # only rebuild cells that changed
                cell.data = symbol
                cell.content = forest_symbol(symbol, size)


# ---------------------------------------------------------------------------
# Home screen
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
    """Continuous safe-to-danger bar with a ring marker. Returns (control, set_value)."""
    bar = ft.Container(
        width=SCALE_WIDTH,
        height=8,
        top=5,
        border_radius=4,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=[color for _, color, _ in RISK_BANDS],
        ),
    )
    marker = ft.Container(
        width=18, height=18, border_radius=9, bgcolor=CARD, border=ft.Border.all(4, INK),
        left=0, top=0, visible=False,
    )
    ends = ft.Row(
        [text("Safe", size=13), text("Extreme danger", size=13)],
        width=SCALE_WIDTH,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    def set_value(hi_f: float):
        marker.left = min(max(scale_position(hi_f) * SCALE_WIDTH - 9, 0), SCALE_WIDTH - 18)
        marker.visible = True

    control = ft.Column(
        [ft.Stack([bar, marker], width=SCALE_WIDTH, height=18), ends],
        spacing=6,
        tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return control, set_value


def stat(icon: ft.IconData, label: str, value: ft.Text) -> ft.Control:
    return ft.Column(
        [ft.Icon(icon, color=MUTED, size=20), text(label, size=13, color=MUTED), value],
        spacing=2,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def weather_picture(w: dict) -> ft.Control:
    if not w["is_day"]:
        return ft.Icon(ft.Icons.BEDTIME_OUTLINED, color=MUTED, size=58)
    if w["cloud_cover"] < 25:
        return image("sun_icon.png", 70)
    return image("sun_and_cloud_clean.png", 96, 77)  # speckles below alpha 24 removed


class WeatherPanel:
    """Location, temperature, feels-like, heat scale and conditions on Home."""

    def __init__(self, on_pick_city):
        self.weather: dict | None = None
        self.unit = "C"
        self.city = text("Tbilisi", size=18, weight=ft.FontWeight.W_600)
        self.location = ft.PopupMenuButton(
            tooltip="Change location",
            content=ft.Row(
                [ft.Icon(ft.Icons.LOCATION_ON, color=INK, size=20), self.city, ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, color=INK, size=20)],
                spacing=6,
                tight=True,
            ),
            items=[
                ft.PopupMenuItem(content=text(name, text_align=ft.TextAlign.LEFT), on_click=lambda e, c=(name, lat, lon): on_pick_city(*c))
                for name, lat, lon in GEORGIAN_CITIES
            ],
        )
        self.degrees = text("–", size=88, weight=ft.FontWeight.W_700)
        self.unit_label = text("°C", size=34, weight=ft.FontWeight.W_600)
        self.picture = ft.Container(width=100, height=80, alignment=ft.Alignment.CENTER)
        self.feels = text("Getting live weather…", size=16, color=MUTED)
        self.scale, self.set_scale = heat_scale()
        self.humidity, self.wind, self.clouds = (text("–", size=16, weight=ft.FontWeight.W_600) for _ in range(3))
        self.updated = text("", size=12, color=MUTED)

        divider = lambda: ft.VerticalDivider(width=1, thickness=1, color=LINE)  # noqa: E731
        self.control = ft.Container(
            bgcolor=PANEL,
            border_radius=20,
            padding=ft.Padding.only(left=18, right=18, top=14, bottom=16),
            content=ft.Column(
                [
                    self.location,
                    ft.Row(
                        [
                            ft.Row(
                                [self.degrees, ft.Container(self.unit_label, margin=ft.Margin.only(top=18))],
                                spacing=2,
                                tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                            ),
                            self.picture,
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    self.feels,
                    ft.Container(self.scale, margin=ft.Margin.only(top=12, bottom=10)),
                    ft.Row(
                        [
                            stat(ft.Icons.WATER_DROP_OUTLINED, "Humidity", self.humidity),
                            divider(),
                            stat(ft.Icons.AIR, "Wind", self.wind),
                            divider(),
                            stat(ft.Icons.CLOUD_OUTLINED, "Clouds", self.clouds),
                        ],
                        height=72,
                        spacing=0,
                    ),
                    self.updated,
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def set_city(self, name: str):
        self.city.value = name

    def loading(self):
        self.updated.value = "Updating…"

    def show(self, w: dict):
        self.weather = w
        risk = heat_risk_checker(w["temperature_2m"], w["relative_humidity_2m"])
        self.degrees.value = f"{to_unit(w['temperature_2m'], self.unit):.0f}"
        self.unit_label.value = f"°{self.unit}"
        self.feels.spans = [
            span(f"Feels like {to_unit(risk['hi_c'], self.unit):.0f}° · "),
            span(risk["level"], bold=True, color=RISK_COLORS[risk["level"]]),
        ]
        self.feels.value = ""
        self.feels.color = INK
        self.set_scale(risk["hi_f"])
        self.picture.content = weather_picture(w)
        self.humidity.value = f"{w['relative_humidity_2m']}%"
        self.wind.value = f"{w['wind_speed_10m']:.0f} km/h {compass(w['wind_direction_10m'])}"
        self.clouds.value = f"{w['cloud_cover']}%"
        self.updated.value = f"Updated {w['time'][-5:]} local time"

    def set_unit(self, unit: str):
        self.unit = unit
        if self.weather:
            self.show(self.weather)

    def show_error(self):
        self.feels.spans = []
        self.feels.value = "Live weather is unavailable. Check your connection, then pick a location to retry."
        self.feels.color = MUTED
        self.updated.value = ""


def shortcut(leading: ft.Control, heading: ft.Text, detail: ft.Text, on_click) -> ft.Container:
    """A card that takes the user to another screen."""
    heading.text_align = detail.text_align = ft.TextAlign.LEFT
    return ft.Container(
        on_click=on_click,
        ink=True,
        bgcolor=CARD,
        border=ft.Border.all(1, LINE),
        border_radius=14,
        padding=ft.Padding.only(left=10, right=12, top=10, bottom=10),
        content=ft.Row(
            [
                ft.Container(leading, width=52, height=52, border_radius=12, bgcolor=MINT, alignment=ft.Alignment.CENTER),
                ft.Column([heading, detail], spacing=1, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color=INK, size=24),
            ],
            spacing=14,
        ),
    )


def danger_badge(color: str) -> tuple[ft.Control, ft.Icon]:
    """Shield with a flame on it. Returns (badge, shield) so the shield can be recoloured."""
    shield = ft.Icon(ft.Icons.SHIELD, color=color, size=36)
    badge = ft.Stack(
        [shield, ft.Container(ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=CARD, size=17), top=8, left=9.5)],
        width=36,
        height=36,
    )
    return badge, shield


def heat_calculator(page: ft.Page) -> ft.Control:
    temp_field = input_field("Temperature", "35", "°C", width=150, keyboard_type=ft.KeyboardType.NUMBER)
    rh_field = input_field("Humidity", "60", "%", width=150, keyboard_type=ft.KeyboardType.NUMBER)
    message = text("", color=MUTED)
    result = text("", size=26, weight=ft.FontWeight.W_300)
    level = text("", size=16)

    def on_check(e):
        try:
            risk = heat_risk_checker(float(temp_field.value), float(rh_field.value))
        except ValueError:
            message.value = "Enter a number for temperature and humidity."
            page.update()
            return
        message.value = ""
        result.value = f"{risk['hi_c']:.0f}°C  /  {risk['hi_f']:.0f}°F"
        level.spans = [span("Feels "), span(risk["level"].lower(), bold=True, color=RISK_COLORS[risk["level"]])]
        page.update()

    return ft.Column(
        [
            text("Check any temperature", size=20, weight=ft.FontWeight.W_600),
            intro("See how hot it feels and how risky that is."),
            ft.Container(height=4),
            ft.Row([temp_field, rh_field], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([primary_button("Check", on_check)], alignment=ft.MainAxisAlignment.CENTER),
            message,
            result,
            level,
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
    picture, name, _ = SCENARIO_INFO[result["key"]]
    return ft.Container(
        expand=True,
        on_click=on_click,
        ink=True,
        bgcolor=CARD,
        border_radius=14,
        border=ft.Border.all(2, FOREST) if selected else ft.Border.all(1, LINE),
        padding=ft.Padding.symmetric(horizontal=4, vertical=14),
        content=ft.Column(
            [
                ft.Container(image(picture, 44, 44), height=48, alignment=ft.Alignment.CENTER),
                text(f"{result['avg_percent']:.0f}%", size=26, weight=ft.FontWeight.W_600),
                ft.Container(text(name, size=14), height=40, alignment=ft.Alignment.TOP_CENTER),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


class Prediction:
    """Runs by itself whenever new weather arrives; there's nothing to press."""

    def __init__(self, page: ft.Page, on_danger):
        self.page = page
        self.on_danger = on_danger  # called with "Low" / "Moderate" / ... once a prediction is ready
        self.running = False
        self.queued: tuple | None = None
        self.results: list[dict] = []
        self.selected = "natural"
        self.unit = "C"
        self.last: tuple | None = None

        self.intro = intro("What would happen to a forest in Tbilisi's weather right now? Updates by itself.")
        self.flame = ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=FOREST, size=26)
        self.danger = text("Working out fire danger…", size=19, weight=ft.FontWeight.W_600)
        self.conditions = text("", size=13.5, color=MUTED)
        self.panel = ft.Container(
            bgcolor=MINT,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                [
                    ft.Row([self.flame, self.danger], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                    self.conditions,
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.cards = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
        self.detail = ft.Column(spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.control = ft.Column(
            [
                title("Fire Risk"),
                self.intro,
                ft.Container(height=8),
                self.panel,
                ft.Container(self.cards, margin=ft.Margin.only(top=6)),
                self.detail,
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def show_error(self, message: str):
        self.danger.value = "Fire danger unavailable"
        self.danger.color = MUTED
        self.conditions.value = message

    def set_unit(self, unit: str):
        self.unit = unit
        if self.last:
            self.describe(*self.last)

    async def run(self, w: dict, city: str):
        if self.running:
            self.queued = (w, city)
            return
        self.running = True
        self.intro.value = f"What would happen to a forest in {city}'s weather right now? Updates by itself."
        self.danger.value = "Working out fire danger…"
        self.danger.color = INK
        self.conditions.value = f"Simulating {PREDICTION_RUNS} forests for each case."
        self.page.update()

        p = await asyncio.to_thread(
            predict_spread,
            w["temperature_2m"], w["relative_humidity_2m"],
            w["wind_direction_10m"], w["wind_speed_10m"],
            w["is_day"], w["cloud_cover"],
        )
        self.results = p["results"]
        self.last = (w, p)
        self.describe(w, p)
        self.render()
        self.running = False
        self.on_danger(danger_label(p["danger"]))
        self.page.update()
        if self.queued:
            queued, self.queued = self.queued, None
            await self.run(*queued)

    def describe(self, w: dict, p: dict):
        level = danger_label(p["danger"])
        color, tint, _ = DANGER[level]
        if not w["is_day"]:
            light = "night, so glass can't focus sunlight"
        elif p["sun"] < 0.05:
            light = "overcast, so glass can't focus sunlight"
        else:
            light = f"{p['sun'] * 100:.0f}% sunshine"
        self.panel.bgcolor = tint
        self.flame.color = color
        self.danger.value = f"Fire danger: {level}"
        self.danger.color = color
        self.conditions.value = (
            f"{to_unit(w['temperature_2m'], self.unit):.0f}°{self.unit}, {w['relative_humidity_2m']}% humidity, "
            f"wind {w['wind_speed_10m']:.0f} km/h pushing fire {p['wind']}, {light}. Tap a case to see a typical forest."
        )

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
        grid, cells = forest_grid(GRID_SIZE, GRID_SIZE, SAMPLE_CELL)
        paint_forest(cells, result["sample_grid"], SAMPLE_CELL)
        self.detail.controls = [
            ft.Container(height=8),
            text(name, size=19, weight=ft.FontWeight.W_600),
            text(explanation, color=MUTED),
            ft.Text(
                spans=[
                    span("On average "),
                    span(f"{result['avg_burned']:.0f} of {result['total_trees']}", bold=True),
                    span(" trees burn. A fire starts in "),
                    span(f"{result['fire_chance']:.0f}% of forests", bold=True),
                    span(f"; the worst one lost {result['max_burned']} trees."),
                ],
                size=13.5,
                color=INK,
                font_family=FONT,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(grid, margin=ft.Margin.only(top=8)),
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
            bgcolor={ft.ControlState.SELECTED: FOREST, ft.ControlState.DEFAULT: CARD},
            color={ft.ControlState.SELECTED: CARD, ft.ControlState.DEFAULT: INK},
            side=ft.BorderSide(1, LINE),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=0),
            visual_density=ft.VisualDensity.COMPACT,
            text_style=ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600),
        ),
    )


def fire_simulation(page: ft.Page) -> ft.Control:
    wind = wind_picker()
    grid_control, cells = forest_grid(GRID_SIZE, GRID_SIZE, CELL)
    summary = text("")

    async def on_start(e):
        start_button.disabled = True
        wind.disabled = True
        summary.value = "Burning…"
        grid = make_grid(GRID_SIZE)
        direction = wind.selected[0]
        while has_fire(grid):
            paint_forest(cells, grid, CELL)
            page.update()
            await asyncio.sleep(STEP_SECONDS)
            spread(grid, direction)
        paint_forest(cells, grid, CELL)
        summary.value = f"{count_trees(grid)} of {GRID_SIZE * GRID_SIZE - 1} trees survived."
        start_button.disabled = False
        wind.disabled = False
        page.update()

    start_button = primary_button("Start fire", on_start)
    paint_forest(cells, make_grid(GRID_SIZE), CELL)

    return ft.Column(
        [
            text("Watch a fire spread", size=20, weight=ft.FontWeight.W_600),
            intro("Pick where the wind blows, then start a fire in the middle of the forest."),
            ft.Container(height=4),
            ft.Row([wind, start_button], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(grid_control, margin=ft.Margin.symmetric(vertical=8)),
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
CITY_LABEL_WIDTH = 64

# Equirectangular projection fitted to Georgia's outline; longitude is squeezed by
# cos(latitude) so the country keeps its real proportions.
MAP_WIDTH = 322
MAP_PAD = 10
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
    """Georgia's outline with three cities for orientation. Pins are added to the returned Stack."""
    points = [map_xy(lat, lon) for lon, lat in GEORGIA["outline"]]
    outline = [cv.Path.MoveTo(*points[0]), *[cv.Path.LineTo(x, y) for x, y in points[1:]], cv.Path.Close()]
    shapes = [
        cv.Path(outline, paint=ft.Paint(color="#F7F9F5", style=ft.PaintingStyle.FILL)),
        cv.Path(
            outline,
            paint=ft.Paint(color="#3E4441", style=ft.PaintingStyle.STROKE, stroke_width=1.6, stroke_join=ft.StrokeJoin.ROUND),
        ),
    ]
    labels = []
    for name, lat, lon, side in MAP_CITIES:
        x, y = map_xy(lat, lon)
        shapes.append(cv.Circle(x, y, 3.5, paint=ft.Paint(color=INK)))
        left = x + 6 if side == "right" else x - 6 - CITY_LABEL_WIDTH
        align = ft.TextAlign.LEFT if side == "right" else ft.TextAlign.RIGHT
        labels.append(
            ft.Text(
                name, size=13, color=INK, weight=ft.FontWeight.W_600, font_family=FONT,
                left=left, top=y - 10, width=CITY_LABEL_WIDTH, text_align=align,
            )
        )
    return ft.Stack(
        [cv.Canvas(shapes, width=MAP_WIDTH, height=MAP_HEIGHT), *labels],
        width=MAP_WIDTH,
        height=MAP_HEIGHT,
        clip_behavior=ft.ClipBehavior.NONE,
    )


def fire_pin(lat: float, lon: float, power_mw: float, tooltip: str) -> tuple[ft.Control, ft.Container]:
    """A glowing fire marker, bigger for more powerful fires. Returns (pin, ring); the ring pings."""
    x, y = map_xy(lat, lon)
    dot = round(9 + min(7, 2.5 * math.log2(1 + power_mw)))
    glow = dot * 2.2
    ring = ft.Container(width=dot, height=dot, border_radius=dot / 2, border=ft.Border.all(2, FLAME), opacity=0.7,
                        left=(glow - dot) / 2, top=(glow - dot) / 2)
    pin = ft.Stack(
        [
            ft.Container(width=glow, height=glow, border_radius=glow / 2, bgcolor=FLAME, opacity=0.22),
            ring,
            ft.Container(
                width=dot, height=dot, border_radius=dot / 2, bgcolor=FLAME, border=ft.Border.all(1.5, CARD),
                left=(glow - dot) / 2, top=(glow - dot) / 2, tooltip=tooltip,
            ),
        ],
        left=x - glow / 2, top=y - glow / 2, width=glow, height=glow, clip_behavior=ft.ClipBehavior.NONE,
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


def fire_card(fire: dict, detections: int) -> ft.Control:
    lat, lon = fire["latitude"], fire["longitude"]
    details = f"Fire power {float(fire['frp']):.1f} MW"
    if detections > 1:
        details += f", seen {detections} times"
    left = lambda value, **kw: text(value, text_align=ft.TextAlign.LEFT, **kw)  # noqa: E731
    return card(
        ft.Row(
            [
                ft.Container(
                    ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=FLAME, size=24),
                    width=44, height=44, border_radius=12, bgcolor="#FBE3DE", alignment=ft.Alignment.CENTER,
                ),
                ft.Column(
                    [
                        left(place_name(fire["address"]), size=15, weight=ft.FontWeight.W_600),
                        left(when_label(detected_at(fire)), size=13, color=MUTED),
                        left(details, size=12.5, color=MUTED),
                    ],
                    spacing=1,
                    expand=True,
                ),
                ft.IconButton(
                    ft.Icons.OPEN_IN_NEW, icon_color=FOREST, icon_size=20, tooltip="Open in Google Maps",
                    url=f"https://www.google.com/maps?q={lat},{lon}",
                ),
            ],
            spacing=12,
        ),
        padding=ft.Padding.only(left=10, right=4, top=10, bottom=10),
    )


def fires_panel(page: ft.Page, on_count):
    """Map + list of fires in Georgia.

    Returns (control, async loader, async ping loop, visibility setter). `on_count` is
    called with the number of fires, or None if the data couldn't be loaded.
    """
    fire_map = georgia_map()
    base_layers = list(fire_map.controls)
    status = text("Getting satellite data…", size=14, text_align=ft.TextAlign.LEFT, expand=True)
    fires_list = ft.Column(spacing=10)
    rings: list[ft.Container] = []
    state = {"loading": False, "visible": False}

    async def load(e=None):
        if state["loading"]:
            return
        state["loading"] = True
        refresh.disabled = True
        fire_map.controls = list(base_layers)
        rings.clear()
        fires_list.controls = []
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
                    tooltip = f"{place_name(fire['address'])}\n{when_label(detected_at(fire))}"
                    pin, ring = fire_pin(lat, lon, float(fire["frp"]), tooltip)
                    fire_map.controls.append(pin)
                    rings.append(ring)
                    groups[cell] = {"fire": fire, "count": 1}
                else:
                    group["count"] += 1
                    if detected_at(fire) > detected_at(group["fire"]):
                        group["fire"] = fire
                newest_first = sorted(groups.values(), key=lambda g: detected_at(g["fire"]), reverse=True)
                fires_list.controls = [fire_card(g["fire"], g["count"]) for g in newest_first]
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

    refresh = ft.IconButton(ft.Icons.REFRESH, icon_color=INK, icon_size=24, tooltip="Check again", on_click=load)

    control = ft.Column(
        [
            ft.Row([title("Fires Happening"), refresh], alignment=ft.MainAxisAlignment.CENTER, spacing=4),
            intro(f"Fires spotted by NASA satellites in Georgia over the last {FIRE_DAYS} days."),
            ft.Container(
                fire_map,
                bgcolor="#E3EAE2",
                border_radius=16,
                padding=ft.Padding.symmetric(horizontal=(342 - MAP_WIDTH) / 2, vertical=36),
                margin=ft.Margin.only(top=10, bottom=6),
                alignment=ft.Alignment.CENTER,
            ),
            ft.Container(
                ft.Row([ft.Icon(ft.Icons.SATELLITE_ALT, color=MUTED, size=26), status], spacing=14),
                bgcolor=PANEL,
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=16, vertical=16),
            ),
            fires_list,
            ft.Container(
                text("Fire data: NASA FIRMS. Map: © OpenStreetMap contributors.", size=11.5, color=MUTED),
                margin=ft.Margin.only(top=14),
            ),
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return control, load, ping_forever, set_visible


# ---------------------------------------------------------------------------
# App chrome: top bar, bottom navigation, sheets
# ---------------------------------------------------------------------------


def screen(*sections: ft.Control) -> ft.Container:
    """Pad sections, separate them with space and a hairline, and let the screen scroll on its own."""
    controls = []
    for section in sections:
        if controls:
            controls.append(ft.Divider(height=44, color=LINE))
        controls.append(section)
    return ft.Container(
        expand=True,
        content=ft.Column(controls, scroll=ft.ScrollMode.AUTO, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.Padding.only(left=PAGE_PADDING, right=PAGE_PADDING, top=8, bottom=28),
    )


def top_bar(on_settings) -> ft.Control:
    return ft.Container(
        padding=ft.Padding.only(left=20, right=10, top=10, bottom=8),
        content=ft.Row(
            [
                image("heat_seeker_logo.png", 163, 34),
                ft.IconButton(ft.Icons.SETTINGS_OUTLINED, icon_color=INK, icon_size=26, tooltip="Settings", on_click=on_settings),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
    )


class BottomNav:
    """Icon + label per screen; the active one turns green with a line under it."""

    ITEMS = [
        (ft.Icons.HOME_OUTLINED, ft.Icons.HOME, "Home"),
        (ft.Icons.LOCAL_FIRE_DEPARTMENT_OUTLINED, ft.Icons.LOCAL_FIRE_DEPARTMENT, "Fire Spread"),
        (ft.Icons.MAP_OUTLINED, ft.Icons.MAP, "Fires Happening"),
    ]

    def __init__(self, on_select):
        self.icons, self.labels, self.lines = [], [], []
        items = []
        for index, (outlined, _, label) in enumerate(self.ITEMS):
            icon = ft.Icon(outlined, size=26)
            name = text(label, size=12.5)
            line = ft.Container(width=80, height=3, border_radius=2)
            self.icons.append(icon)
            self.labels.append(name)
            self.lines.append(line)
            items.append(
                ft.Container(
                    expand=True,
                    on_click=lambda e, i=index: on_select(i),
                    padding=ft.Padding.only(top=10),
                    content=ft.Column(
                        [icon, name, ft.Container(height=4), line],
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        self.control = ft.Container(
            bgcolor=CARD,
            border=ft.Border.only(top=ft.BorderSide(1, LINE)),
            content=ft.Row(items, spacing=0),
        )
        self.select(HOME)

    def select(self, index: int):
        for i, (outlined, filled, _) in enumerate(self.ITEMS):
            active = i == index
            self.icons[i].icon = filled if active else outlined
            self.icons[i].color = FOREST if active else INK
            self.labels[i].color = FOREST if active else INK
            self.labels[i].weight = ft.FontWeight.W_600 if active else None
            self.lines[i].bgcolor = FOREST if active else None


def location_sheet(page: ft.Page, on_pick) -> ft.BottomSheet:
    """Search any place by name, or tap a Georgian city."""
    results = ft.Column(spacing=0)
    message = text("", color=MUTED, visible=False)

    def say(value: str):
        message.value = value
        message.visible = bool(value)

    def place_row(name: str, where: str, lat: float, lon: float) -> ft.Control:
        return ft.Container(
            on_click=lambda e: pick(name, lat, lon),
            ink=True,
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=8, vertical=10),
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LOCATION_ON_OUTLINED, color=FOREST, size=22),
                    ft.Column(
                        [
                            text(name, size=15, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.LEFT),
                            text(where, size=12.5, color=MUTED, text_align=ft.TextAlign.LEFT),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=12,
            ),
        )

    def show_cities():
        results.controls = [place_row(name, CITY_REGIONS[name], lat, lon) for name, lat, lon in GEORGIAN_CITIES]

    async def on_search(e):
        query = (search.value or "").strip()
        if not query:
            say("")
            show_cities()
            page.update()
            return
        say("Searching…")
        page.update()
        try:
            places = await asyncio.to_thread(search_places, query)
        except Exception:
            say("Search is unavailable. Check your connection and try again.")
            page.update()
            return
        if places:
            say("")
            results.controls = [
                place_row(p["name"], p["region"] or "Georgia", p["latitude"], p["longitude"])
                for p in places
            ]
        else:
            say(f"No place in Georgia called \"{query}\". Check the spelling or try a nearby town.")
            results.controls = []
        page.update()

    def pick(name: str, lat: float, lon: float):
        page.pop_dialog()
        on_pick(name, lat, lon)

    search = input_field(
        "Search for a town or village", prefix_icon=ft.Icons.SEARCH, on_submit=on_search, autofocus=True
    )
    show_cities()
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        scrollable=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=24),
            content=ft.Column(
                [
                    text("Check any location", size=20, weight=ft.FontWeight.W_600),
                    intro("See the weather and fire risk anywhere in Georgia. Press Enter to search."),
                    search,
                    message,
                    results,
                ],
                spacing=10,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ),
    )


def settings_sheet(current_unit: str, on_unit) -> ft.BottomSheet:
    units = ft.SegmentedButton(
        selected=[current_unit],
        show_selected_icon=False,
        segments=[ft.Segment(value="C", label="Celsius (°C)"), ft.Segment(value="F", label="Fahrenheit (°F)")],
        on_change=lambda e: on_unit(e.control.selected[0]),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.SELECTED: FOREST, ft.ControlState.DEFAULT: CARD},
            color={ft.ControlState.SELECTED: CARD, ft.ControlState.DEFAULT: INK},
            side=ft.BorderSide(1, LINE),
            text_style=ft.TextStyle(font_family=FONT, size=14, weight=ft.FontWeight.W_600),
        ),
    )
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=28),
            content=ft.Column(
                [
                    text("Settings", size=20, weight=ft.FontWeight.W_600),
                    ft.Container(height=4),
                    text("Temperature unit", size=15, weight=ft.FontWeight.W_600),
                    ft.Row([units], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Container(height=8),
                    text("Data sources", size=15, weight=ft.FontWeight.W_600),
                    text(
                        "Weather: Open-Meteo. Fires: NASA FIRMS (VIIRS NOAA-21). "
                        "Places and map: © OpenStreetMap contributors.",
                        size=13,
                        color=MUTED,
                    ),
                ],
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def main(page: ft.Page):
    page.title = "Heat Seeker"
    page.padding = 0
    page.spacing = 0
    page.bgcolor = CANVAS
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        font_family=FONT,
        scaffold_bgcolor=CANVAS,
        color_scheme=ft.ColorScheme(
            primary=FOREST,
            on_primary=CARD,
            surface=CANVAS,
            on_surface=INK,
            on_surface_variant=MUTED,
            outline=LINE,
            outline_variant=LINE,
        ),
    )
    page.window.width = WINDOW_WIDTH
    page.window.height = WINDOW_HEIGHT
    page.window.resizable = False
    page.window.maximizable = False
    page.window.icon = str(APP_ICON)

    location = {"name": "Tbilisi", "lat": GEORGIAN_CITIES[0][1], "lon": GEORGIAN_CITIES[0][2]}
    settings = {"unit": "C"}
    screens: list[ft.Container] = []

    def go_to(index: int):
        nav.select(index)
        for i, s in enumerate(screens):
            s.visible = i == index
        show_fires(index == FIRES_HAPPENING)
        page.update()

    # --- Weather + prediction, refreshed together for the chosen location ----
    async def refresh_weather():
        weather.loading()
        page.update()
        try:
            w = await asyncio.to_thread(fetch_current_weather, location["lat"], location["lon"])
        except Exception:
            weather.show_error()
            prediction.show_error("Live weather is unavailable, so there's no prediction yet.")
            danger_title.value = "Fire danger unavailable right now"
            danger_detail.value = "Check your connection, then pick a location to retry."
            page.update()
            return
        weather.show(w)
        page.update()
        await prediction.run(w, location["name"])

    def pick_location(name: str, lat: float, lon: float):
        location.update(name=name, lat=lat, lon=lon)
        weather.set_city(name)
        danger_title.value = f"Working out fire danger in {name}…"
        go_to(HOME)
        page.run_task(refresh_weather)

    def set_unit(unit: str):
        settings["unit"] = unit
        weather.set_unit(unit)
        prediction.set_unit(unit)
        page.update()

    # --- Home shortcuts, updated as data arrives ------------------------------
    badge, shield = danger_badge(FOREST)
    danger_title = text("Working out today's fire danger…", size=15.5, weight=ft.FontWeight.W_600)
    danger_detail = text("See how a fire would spread", size=13, color=MUTED)
    fires_title = text("Checking for fires in Georgia…", size=15.5, weight=ft.FontWeight.W_600)
    fires_icon = ft.Icon(ft.Icons.MENU_BOOK_OUTLINED, color=FOREST, size=30)

    def show_danger(level: str):
        color, _, advice = DANGER[level]
        danger_title.value = f"Fire danger today: {level}"
        danger_detail.value = advice
        shield.color = color

    def show_fire_count(count):
        if count is None:
            fires_title.value = "Fire data unavailable right now"
        elif count == 0:
            fires_title.value = "No fires in Georgia now"
        else:
            fires_title.value = f"{count} {'fire' if count == 1 else 'fires'} in Georgia"
        fires_icon.color = FLAME if count else FOREST

    check_location = ft.Container(
        on_click=lambda e: page.show_dialog(location_sheet(page, pick_location)),
        ink=True,
        bgcolor=MINT,
        border_radius=14,
        height=58,
        content=ft.Row(
            [ft.Icon(ft.Icons.PARK, color=FOREST, size=26), text("Check any location", size=17, color=FOREST, weight=ft.FontWeight.W_500)],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
        ),
    )

    # --- Screens --------------------------------------------------------------
    weather = WeatherPanel(on_pick_city=pick_location)
    prediction = Prediction(page, on_danger=show_danger)
    fires, load_fires, ping_fires, show_fires = fires_panel(page, on_count=show_fire_count)

    home = ft.Column(
        [
            weather.control,
            ft.Container(height=6),
            shortcut(badge, danger_title, danger_detail, lambda e: go_to(FIRE_SPREAD)),
            shortcut(
                fires_icon, fires_title,
                text(f"Satellite data from the last {FIRE_DAYS} days.", size=13, color=MUTED),
                lambda e: go_to(FIRES_HAPPENING),
            ),
            check_location,
        ],
        spacing=12,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    screens.extend(
        [
            screen(home, heat_calculator(page)),
            screen(prediction.control, fire_simulation(page)),
            screen(fires),
        ]
    )
    for s in screens[1:]:
        s.visible = False

    nav = BottomNav(on_select=go_to)
    page.add(
        ft.Column(
            [top_bar(lambda e: page.show_dialog(settings_sheet(settings["unit"], set_unit))), *screens, nav.control],
            expand=True,
            spacing=0,
        )
    )

    page.run_task(page.window.center)
    page.run_task(refresh_weather)
    page.run_task(load_fires)
    page.run_task(ping_fires)


if __name__ == "__main__":
    ft.run(main)
