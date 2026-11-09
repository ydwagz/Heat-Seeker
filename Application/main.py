import asyncio
import json
import math
import re
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
from translations import CITY_NAMES, COMPASS, LANGUAGES, MONTHS, REGION_NAMES, georgian_genitive, translate

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

# Fire danger levels from the prediction: (text colour, panel tint)
DANGER_COLORS = {
    "Low": ("#2F8A55", MINT),
    "Moderate": ("#B98A12", "#FBF3DC"),
    "High": ("#D9661E", "#FCE9DA"),
    "Extreme": ("#B3261E", "#F9DEDB"),
}

# Prediction case icons
CASE_ICONS = {"natural": "sun_icon.png", "glass": "glass_icon.png", "flammable": "flammable_litter_icon.png"}

# Built-in Georgian cities: (English name, lat, lon, English region)
GEORGIAN_CITIES = [
    ("Tbilisi", 41.7151, 44.8271, "Tbilisi"),
    ("Kutaisi", 42.2679, 42.6946, "Imereti"),
    ("Batumi", 41.6168, 41.6367, "Adjara"),
    ("Rustavi", 41.5495, 44.9932, "Kvemo Kartli"),
    ("Gori", 41.9842, 44.1158, "Shida Kartli"),
    ("Zugdidi", 42.5088, 41.8709, "Samegrelo-Zemo Svaneti"),
    ("Telavi", 41.9198, 45.4731, "Kakheti"),
    ("Borjomi", 41.8383, 43.3790, "Samtskhe-Javakheti"),
]

HOME, FIRE_SPREAD, FIRES_HAPPENING = 0, 1, 2


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def text(value="", size=14, color=INK, weight=None, text_align=ft.TextAlign.CENTER, **kwargs) -> ft.Text:
    return ft.Text(value, size=size, color=color, weight=weight, font_family=FONT, text_align=text_align, **kwargs)


def rich(template_text: str, bold_color: str | None = None) -> list[ft.TextSpan]:
    """Turn 'plain **bold** plain' into spans; bold parts can take a colour."""
    spans = []
    for i, part in enumerate(re.split(r"\*\*", template_text)):
        if part:
            bold = i % 2 == 1
            spans.append(
                ft.TextSpan(part, ft.TextStyle(weight=ft.FontWeight.W_700 if bold else None, color=bold_color if bold else None))
            )
    return spans


def title(value: str, lang: str = "en") -> ft.Text:
    # Georgian words are longer and its letters wider, so screen titles step down a size
    return text(value, size=28 if lang == "en" else 24, weight=ft.FontWeight.W_600)


def intro(value: str) -> ft.Text:
    """The line under a screen title that tells a new user what the screen is for."""
    return text(value, color=MUTED)


def image(name: str, width: float, height: float | None = None) -> ft.Image:
    return ft.Image(src=str(IMAGES / name), width=width, height=height or width, fit=ft.BoxFit.CONTAIN)


def card(content: ft.Control, **kwargs) -> ft.Container:
    return ft.Container(content=content, bgcolor=CARD, border=ft.Border.all(1, LINE), border_radius=14, **kwargs)


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


def choice(options: list[tuple[str, str]], selected: str, on_change, width: float | None = None) -> ft.SegmentedButton:
    """Two-or-more option switch, used for settings and the wind direction."""
    return ft.SegmentedButton(
        width=width,
        selected=[selected],
        show_selected_icon=False,
        segments=[ft.Segment(value=value, label=label) for value, label in options],
        on_change=on_change,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.SELECTED: FOREST, ft.ControlState.DEFAULT: CARD},
            color={ft.ControlState.SELECTED: CARD, ft.ControlState.DEFAULT: INK},
            side=ft.BorderSide(1, LINE),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=0),
            visual_density=ft.VisualDensity.COMPACT,
            text_style=ft.TextStyle(font_family=FONT, size=14, weight=ft.FontWeight.W_600),
        ),
    )


def to_unit(celsius: float, unit: str) -> float:
    return celsius * 9 / 5 + 32 if unit == "F" else celsius


def danger_label(danger: float) -> str:
    if danger < 0.15:
        return "Low"
    if danger < 0.4:
        return "Moderate"
    if danger < 0.7:
        return "High"
    return "Extreme"


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
# App state: data lives here, screens draw themselves from it
# ---------------------------------------------------------------------------


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.lang = "en"
        self.unit = "C"
        name, lat, lon, _ = GEORGIAN_CITIES[0]
        # Built-in cities are stored by English key so their name can be translated;
        # searched places keep the name they were found under.
        self.place = {"key": name, "name": None, "lat": lat, "lon": lon}
        self.screen = HOME

        self.weather: dict | None = None
        self.weather_status = "loading"  # loading | ready | error
        self.prediction: dict | None = None
        self.prediction_status = "waiting"  # waiting | running | ready | error
        self.selected_case = "natural"
        self.fires = {"status": "loading", "total": 0, "groups": {}}
        # fires status: loading | checking | done | nasa_error | lookup_error

        self._predicting = False
        self._queued = False
        self._loading_fires = False
        self.views: "Views | None" = None

    # --- Language helpers ----------------------------------------------------
    def t(self, key: str, **fields) -> str:
        return translate(self.lang, key, **fields)

    def city_name(self, key: str | None = None) -> str:
        key = key or self.place["key"]
        if key is None:
            return self.place["name"]
        return CITY_NAMES[key] if self.lang == "ka" else key

    def region_name(self, region: str) -> str:
        return REGION_NAMES.get(region, region) if self.lang == "ka" else region

    def compass(self, deg: float) -> str:
        return COMPASS[self.lang][round(deg / 45) % 8]

    def when(self, moment: datetime) -> str:
        today = datetime.now(GEORGIA_TZ).date()
        if moment.date() == today:
            day = self.t("when.today")
        elif moment.date() == today - timedelta(days=1):
            day = self.t("when.yesterday")
        else:
            day = f"{moment.day} {MONTHS[self.lang][moment.month - 1]}"
        return f"{day}, {moment:%H:%M}"

    # --- Building the interface -----------------------------------------------
    def build(self):
        """(Re)create every screen in the current language and draw the saved data."""
        self.views = Views(self)
        self.page.controls.clear()
        self.page.add(self.views.root)
        self.views.show_screen(self.screen)
        self.views.render_all()
        self.page.update()

    def go_to(self, index: int):
        self.screen = index
        self.views.show_screen(index)
        self.page.update()

    # --- Settings -----------------------------------------------------------
    def set_language(self, lang: str):
        if lang == self.lang:
            return
        self.lang = lang
        self.page.pop_dialog()
        self.build()
        self.page.show_dialog(settings_sheet(self))  # reopen so the switch is visible in the new language

    def set_unit(self, unit: str):
        self.unit = unit
        self.views.weather.render()
        self.views.prediction.render()
        self.page.update()

    # --- Location -------------------------------------------------------------
    def pick_place(self, key: str | None, name: str | None, lat: float, lon: float):
        self.place = {"key": key, "name": name, "lat": lat, "lon": lon}
        self.go_to(HOME)
        self.page.run_task(self.refresh_weather)

    # --- Data -------------------------------------------------------------------
    async def refresh_weather(self):
        self.weather_status = "loading"
        self.prediction_status = "running" if self.weather else "waiting"
        self.views.render_all()
        self.page.update()
        try:
            w = await asyncio.to_thread(fetch_current_weather, self.place["lat"], self.place["lon"])
        except Exception:
            self.weather_status = "error"
            self.prediction_status = "error"
            self.views.render_all()
            self.page.update()
            return
        self.weather, self.weather_status = w, "ready"
        self.views.weather.render()
        self.page.update()
        await self.run_prediction()

    async def run_prediction(self):
        if self._predicting:
            self._queued = True
            return
        self._predicting = True
        self.prediction_status = "running"
        self.views.prediction.render()
        self.views.shortcuts.render()
        self.page.update()
        w = self.weather
        p = await asyncio.to_thread(
            predict_spread,
            w["temperature_2m"], w["relative_humidity_2m"],
            w["wind_direction_10m"], w["wind_speed_10m"],
            w["is_day"], w["cloud_cover"],
        )
        self.prediction = {"weather": w, "result": p}
        self.prediction_status = "ready"
        self._predicting = False
        self.views.prediction.render()
        self.views.shortcuts.render()
        self.page.update()
        if self._queued:
            self._queued = False
            await self.run_prediction()

    async def load_fires(self, e=None):
        if self._loading_fires:
            return
        self._loading_fires = True
        try:
            await self._load_fires()
        finally:
            self._loading_fires = False

    async def _load_fires(self):
        self.fires = {"status": "loading", "total": 0, "groups": {}}
        self._render_fires()
        try:
            detections = await asyncio.to_thread(fetch_fires)
        except Exception:
            self.fires["status"] = "nasa_error"
            self._render_fires()
            return

        self.fires.update(status="checking", total=len(detections))
        self._render_fires()
        # One fire usually shows up as several detections a few hundred metres apart:
        # group them by ~1 km cell, keep the newest, and count the rest.
        groups = self.fires["groups"]
        located = iter_fires_in_georgia(detections)
        while True:
            try:
                fire = await asyncio.to_thread(next, located, None)
            except Exception:
                self.fires["status"] = "lookup_error"
                self._render_fires()
                return
            if fire is None:
                break
            cell = (round(float(fire["latitude"]), 2), round(float(fire["longitude"]), 2))
            group = groups.get(cell)
            if group is None:
                groups[cell] = {"fire": fire, "count": 1}
            else:
                group["count"] += 1
                if detected_at(fire) > detected_at(group["fire"]):
                    group["fire"] = fire
            self._render_fires()
        self.fires["status"] = "done"
        self._render_fires()

    def _render_fires(self):
        self.views.fires.render()
        self.views.shortcuts.render()
        self.page.update()

    async def ping_forever(self):
        """Expanding, fading ring around every fire pin while Fires Happening is open."""
        grow = ft.Animation(duration=1200, curve=ft.AnimationCurve.EASE_OUT)
        reset = ft.Animation(duration=0)
        while True:
            rings = self.views.fires.rings if self.views else []
            if self.screen != FIRES_HAPPENING or not rings:
                await asyncio.sleep(0.5)
                continue
            for ring in rings:
                ring.animate_scale = ring.animate_opacity = grow
                ring.scale, ring.opacity = 3, 0
            self.page.update()
            await asyncio.sleep(1.3)
            for ring in rings:
                ring.animate_scale = ring.animate_opacity = reset
                ring.scale, ring.opacity = 1, 0.7
            self.page.update()
            await asyncio.sleep(0.4)


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

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.city = text("", size=18, weight=ft.FontWeight.W_600)
        location = ft.PopupMenuButton(
            tooltip=t("weather.change_location"),
            content=ft.Row(
                [ft.Icon(ft.Icons.LOCATION_ON, color=INK, size=20), self.city, ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, color=INK, size=20)],
                spacing=6,
                tight=True,
            ),
            items=[
                ft.PopupMenuItem(
                    content=text(app.city_name(name), text_align=ft.TextAlign.LEFT),
                    on_click=lambda e, c=(name, lat, lon): app.pick_place(c[0], None, c[1], c[2]),
                )
                for name, lat, lon, _ in GEORGIAN_CITIES
            ],
        )
        self.degrees = text("–", size=88, weight=ft.FontWeight.W_700)
        self.unit_label = text("°C", size=34, weight=ft.FontWeight.W_600)
        self.picture = ft.Container(width=100, height=80, alignment=ft.Alignment.CENTER)
        self.feels = text("", size=16)
        self.marker = ft.Container(
            width=18, height=18, border_radius=9, bgcolor=CARD, border=ft.Border.all(4, INK), left=0, top=0, visible=False
        )
        bar = ft.Container(
            width=SCALE_WIDTH, height=8, top=5, border_radius=4,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT, colors=[c for _, c, _ in RISK_BANDS]
            ),
        )
        scale = ft.Column(
            [
                ft.Stack([bar, self.marker], width=SCALE_WIDTH, height=18),
                ft.Row(
                    [text(t("scale.safe"), size=13), text(t("scale.extreme"), size=13)],
                    width=SCALE_WIDTH,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=6,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.humidity, self.wind, self.clouds = (text("–", size=16, weight=ft.FontWeight.W_600) for _ in range(3))
        self.updated = text("", size=12, color=MUTED)

        # Fixed-height dividers so the row can grow when a value wraps (Georgian runs longer)
        divider = lambda: ft.Container(width=1, height=60, bgcolor=LINE, margin=ft.Margin.only(top=6))  # noqa: E731
        self.control = ft.Container(
            bgcolor=PANEL,
            border_radius=20,
            padding=ft.Padding.only(left=18, right=18, top=14, bottom=16),
            content=ft.Column(
                [
                    location,
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
                    ft.Container(scale, margin=ft.Margin.only(top=12, bottom=10)),
                    ft.Row(
                        [
                            stat(ft.Icons.WATER_DROP_OUTLINED, t("weather.humidity"), self.humidity),
                            divider(),
                            stat(ft.Icons.AIR, t("weather.wind"), self.wind),
                            divider(),
                            stat(ft.Icons.CLOUD_OUTLINED, t("weather.clouds"), self.clouds),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    self.updated,
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def render(self):
        app, t, w = self.app, self.app.t, self.app.weather
        self.city.value = app.city_name()
        self.feels.spans = []
        if app.weather_status == "error":
            self.feels.value, self.feels.color = t("weather.error"), MUTED
            self.updated.value = ""
            return
        if w is None:
            self.feels.value, self.feels.color = t("weather.loading"), MUTED
            return
        risk = heat_risk_checker(w["temperature_2m"], w["relative_humidity_2m"])
        self.degrees.value = f"{to_unit(w['temperature_2m'], app.unit):.0f}"
        self.unit_label.value = f"°{app.unit}"
        self.feels.value, self.feels.color = "", INK
        self.feels.spans = rich(
            t("weather.feels", temp=f"{to_unit(risk['hi_c'], app.unit):.0f}", level=t(f"risk.{risk['level']}")),
            bold_color=RISK_COLORS[risk["level"]],
        )
        self.marker.left = min(max(scale_position(risk["hi_f"]) * SCALE_WIDTH - 9, 0), SCALE_WIDTH - 18)
        self.marker.visible = True
        self.picture.content = weather_picture(w)
        self.humidity.value = f"{w['relative_humidity_2m']}%"
        self.wind.value = t("weather.wind_value", speed=f"{w['wind_speed_10m']:.0f}", dir=app.compass(w["wind_direction_10m"]))
        self.clouds.value = f"{w['cloud_cover']}%"
        if app.weather_status == "loading":
            self.updated.value = t("weather.updating")
        else:
            self.updated.value = t("weather.updated", time=w["time"][-5:])


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


class Shortcuts:
    """The two cards under the weather that lead to the other screens."""

    def __init__(self, app: App):
        self.app = app
        self.shield = ft.Icon(ft.Icons.SHIELD, color=FOREST, size=36)
        badge = ft.Stack(
            [self.shield, ft.Container(ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=CARD, size=17), top=8, left=9.5)],
            width=36,
            height=36,
        )
        self.danger_title = text("", size=15.5, weight=ft.FontWeight.W_600)
        self.danger_detail = text("", size=13, color=MUTED)
        self.fires_icon = ft.Icon(ft.Icons.MENU_BOOK_OUTLINED, color=FOREST, size=30)
        self.fires_title = text("", size=15.5, weight=ft.FontWeight.W_600)
        self.control = ft.Column(
            [
                shortcut(badge, self.danger_title, self.danger_detail, lambda e: app.go_to(FIRE_SPREAD)),
                shortcut(
                    self.fires_icon, self.fires_title,
                    text(app.t("home.fires_detail", days=FIRE_DAYS), size=13, color=MUTED),
                    lambda e: app.go_to(FIRES_HAPPENING),
                ),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def render(self):
        app, t = self.app, self.app.t
        status = app.prediction_status
        if status == "error":
            self.danger_title.value = t("home.danger_unavailable")
            self.danger_detail.value = t("home.danger_retry")
            self.shield.color = MUTED
        elif status == "ready" and app.prediction:
            level = danger_label(app.prediction["result"]["danger"])
            self.danger_title.value = t("home.danger_today", level=t(f"danger.{level}"))
            self.danger_detail.value = t(f"advice.{level}")
            self.shield.color = DANGER_COLORS[level][0]
        else:
            self.danger_title.value = (
                t("home.danger_loading_in", city=app.city_name()) if app.prediction else t("home.danger_loading")
            )
            self.danger_detail.value = t("home.danger_hint")

        fires = app.fires
        if fires["status"] in ("nasa_error", "lookup_error"):
            self.fires_title.value = t("home.fires_unavailable")
        elif fires["status"] != "done":
            self.fires_title.value = t("home.fires_loading")
        elif not fires["groups"]:
            self.fires_title.value = t("home.fires_none")
        elif len(fires["groups"]) == 1:
            self.fires_title.value = t("home.fires_one")
        else:
            self.fires_title.value = t("home.fires_many", count=len(fires["groups"]))
        self.fires_icon.color = FLAME if fires["groups"] else FOREST


def heat_calculator(app: App) -> ft.Control:
    t = app.t
    temp_field = input_field(t("calc.temperature"), "35", "°C", width=160, keyboard_type=ft.KeyboardType.NUMBER)
    rh_field = input_field(t("calc.humidity"), "60", "%", width=160, keyboard_type=ft.KeyboardType.NUMBER)
    message = text("", color=MUTED)
    result = text("", size=26, weight=ft.FontWeight.W_300)
    level = text("", size=16, weight=ft.FontWeight.W_700)

    def on_check(e):
        try:
            risk = heat_risk_checker(float(temp_field.value), float(rh_field.value))
        except ValueError:
            message.value = t("calc.invalid")
            app.page.update()
            return
        message.value = ""
        result.value = f"{risk['hi_c']:.0f}°C  /  {risk['hi_f']:.0f}°F"
        level.value = t(f"risk.{risk['level']}")
        level.color = RISK_COLORS[risk["level"]]
        app.page.update()

    return ft.Column(
        [
            text(t("calc.title"), size=20, weight=ft.FontWeight.W_600),
            intro(t("calc.intro")),
            ft.Container(height=4),
            ft.Row([temp_field, rh_field], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([primary_button(t("calc.check"), on_check)], alignment=ft.MainAxisAlignment.CENTER),
            message,
            result,
            level,
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Fire risk screen
# ---------------------------------------------------------------------------


def scenario_card(app: App, result: dict, selected: bool, on_click) -> ft.Control:
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
                ft.Container(image(CASE_ICONS[result["key"]], 44, 44), height=48, alignment=ft.Alignment.CENTER),
                text(f"{result['avg_percent']:.0f}%", size=26, weight=ft.FontWeight.W_600),
                ft.Container(text(app.t(f"case.{result['key']}"), size=14), height=40, alignment=ft.Alignment.TOP_CENTER),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


class PredictionView:
    """Fire danger for the chosen place, worked out automatically from live weather."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.intro = intro("")
        self.flame = ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=FOREST, size=26)
        self.danger = text("", size=19 if app.lang == "en" else 17, weight=ft.FontWeight.W_600)
        self.conditions = text("", size=13.5, color=MUTED)
        self.panel = ft.Container(
            bgcolor=MINT,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                [ft.Row([self.flame, self.danger], alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True), self.conditions],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.cards = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
        self.detail = ft.Column(spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.control = ft.Column(
            [
                title(t("risk.title"), app.lang),
                self.intro,
                ft.Container(height=8),
                self.panel,
                ft.Container(self.cards, margin=ft.Margin.only(top=6)),
                self.detail,
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def select(self, key: str):
        self.app.selected_case = key
        self.render()
        self.app.page.update()

    def render(self):
        app, t = self.app, self.app.t
        city = app.city_name()
        self.intro.value = t("risk.intro", city=city, city_of=georgian_genitive(city))
        self.panel.bgcolor, self.flame.color = MINT, FOREST

        if app.prediction_status == "error" and not app.prediction:
            self.danger.value, self.danger.color = t("risk.unavailable"), MUTED
            self.conditions.value = t("risk.no_weather")
            return
        if not app.prediction:
            self.danger.value, self.danger.color = t("risk.working"), INK
            self.conditions.value = t("risk.simulating", runs=PREDICTION_RUNS)
            return

        w, p = app.prediction["weather"], app.prediction["result"]
        level = danger_label(p["danger"])
        color, tint = DANGER_COLORS[level]
        if not w["is_day"]:
            light = t("risk.night")
        elif p["sun"] < 0.05:
            light = t("risk.overcast")
        else:
            light = t("risk.sunshine", percent=f"{p['sun'] * 100:.0f}")
        self.panel.bgcolor, self.flame.color = tint, color
        if app.prediction_status == "running":
            self.danger.value, self.danger.color = t("risk.working"), INK
        else:
            self.danger.value, self.danger.color = t("risk.danger", level=t(f"danger.{level}")), color
        self.conditions.value = t(
            "risk.conditions",
            temp=f"{to_unit(w['temperature_2m'], app.unit):.0f}", unit=app.unit,
            humidity=w["relative_humidity_2m"], speed=f"{w['wind_speed_10m']:.0f}",
            toward=t(f"toward.{p['wind']}"), light=light,
        )

        results = p["results"]
        self.cards.controls = [
            scenario_card(app, r, r["key"] == app.selected_case, lambda e, k=r["key"]: self.select(k)) for r in results
        ]
        result = next(r for r in results if r["key"] == app.selected_case)
        grid, cells = forest_grid(GRID_SIZE, GRID_SIZE, SAMPLE_CELL)
        paint_forest(cells, result["sample_grid"], SAMPLE_CELL)
        self.detail.controls = [
            ft.Container(height=8),
            text(t(f"case.{result['key']}"), size=19, weight=ft.FontWeight.W_600),
            text(t(f"case.{result['key']}.about"), color=MUTED),
            ft.Text(
                spans=rich(
                    t(
                        "risk.summary",
                        burned=f"{result['avg_burned']:.0f}", total=result["total_trees"],
                        chance=f"{result['fire_chance']:.0f}", worst=result["max_burned"],
                    )
                ),
                size=13.5,
                color=INK,
                font_family=FONT,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(grid, margin=ft.Margin.only(top=8)),
        ]


def fire_simulation(app: App) -> ft.Control:
    t = app.t
    directions = ["north", "east", "south", "west"]
    wind = choice([(d, t(f"wind.{d}")) for d in directions], "south", None, width=228)
    grid_control, cells = forest_grid(GRID_SIZE, GRID_SIZE, CELL)
    summary = text("")

    async def on_start(e):
        start_button.disabled = True
        wind.disabled = True
        summary.value = t("sim.burning")
        grid = make_grid(GRID_SIZE)
        direction = wind.selected[0]
        while has_fire(grid):
            paint_forest(cells, grid, CELL)
            app.page.update()
            await asyncio.sleep(STEP_SECONDS)
            spread(grid, direction)
        paint_forest(cells, grid, CELL)
        summary.value = t("sim.survived", alive=count_trees(grid), total=GRID_SIZE * GRID_SIZE - 1)
        start_button.disabled = False
        wind.disabled = False
        app.page.update()

    start_button = primary_button(t("sim.start"), on_start)
    paint_forest(cells, make_grid(GRID_SIZE), CELL)

    return ft.Column(
        [
            text(t("sim.title"), size=20, weight=ft.FontWeight.W_600),
            intro(t("sim.intro")),
            ft.Container(height=4),
            ft.Row([wind, start_button], spacing=12, run_spacing=10, wrap=True, alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(grid_control, margin=ft.Margin.symmetric(vertical=8), alignment=ft.Alignment.CENTER),
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
# (English name, lat, lon, label side). Tbilisi's label sits left, clear of the fire-prone east.
MAP_CITIES = [
    ("Tbilisi", 41.7151, 44.8271, "left"),
    ("Kutaisi", 42.2679, 42.6946, "right"),
    ("Batumi", 41.6168, 41.6367, "right"),
]
CITY_LABEL_WIDTH = 72

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


def georgia_map(app: App) -> ft.Stack:
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
                app.city_name(name), size=13, color=INK, weight=ft.FontWeight.W_600, font_family=FONT,
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
    offset = (glow - dot) / 2
    ring = ft.Container(
        width=dot, height=dot, border_radius=dot / 2, border=ft.Border.all(2, FLAME), opacity=0.7, left=offset, top=offset
    )
    pin = ft.Stack(
        [
            ft.Container(width=glow, height=glow, border_radius=glow / 2, bgcolor=FLAME, opacity=0.22),
            ring,
            ft.Container(
                width=dot, height=dot, border_radius=dot / 2, bgcolor=FLAME, border=ft.Border.all(1.5, CARD),
                left=offset, top=offset, tooltip=tooltip,
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


def fire_card(app: App, fire: dict, detections: int) -> ft.Control:
    t = app.t
    lat, lon = fire["latitude"], fire["longitude"]
    details = t("fires.power", power=f"{float(fire['frp']):.1f}")
    if detections > 1:
        details += t("fires.seen", count=detections)
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
                        left(app.when(detected_at(fire)), size=13, color=MUTED),
                        left(details, size=12.5, color=MUTED),
                    ],
                    spacing=1,
                    expand=True,
                ),
                ft.IconButton(
                    ft.Icons.OPEN_IN_NEW, icon_color=FOREST, icon_size=20, tooltip=t("fires.open_map"),
                    url=f"https://www.google.com/maps?q={lat},{lon}",
                ),
            ],
            spacing=12,
        ),
        padding=ft.Padding.only(left=10, right=4, top=10, bottom=10),
    )


class FiresView:
    """Map + list of fires in Georgia, drawn from `app.fires`."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.map = georgia_map(app)
        self.base_layers = list(self.map.controls)
        self.rings: list[ft.Container] = []
        self.status = text("", size=14, text_align=ft.TextAlign.LEFT, expand=True)
        self.list = ft.Column(spacing=10)
        self.refresh = ft.IconButton(
            ft.Icons.REFRESH, icon_color=INK, icon_size=24, tooltip=t("fires.check_again"),
            on_click=lambda e: app.page.run_task(app.load_fires),
        )
        self.control = ft.Column(
            [
                ft.Row([ft.Container(title(t("fires.title"), app.lang), expand=True), self.refresh], spacing=4),
                intro(t("fires.intro", days=FIRE_DAYS)),
                ft.Container(
                    self.map,
                    bgcolor="#E3EAE2",
                    border_radius=16,
                    padding=ft.Padding.symmetric(horizontal=(342 - MAP_WIDTH) / 2, vertical=36),
                    margin=ft.Margin.only(top=10, bottom=6),
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Container(
                    ft.Row([ft.Icon(ft.Icons.SATELLITE_ALT, color=MUTED, size=26), self.status], spacing=14),
                    bgcolor=PANEL,
                    border_radius=14,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=16),
                ),
                self.list,
                ft.Container(text(t("fires.credits"), size=11.5, color=MUTED), margin=ft.Margin.only(top=14)),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def render(self):
        app, t, fires = self.app, self.app.t, self.app.fires
        groups = fires["groups"]
        status = fires["status"]
        self.refresh.disabled = status in ("loading", "checking")

        pins, self.rings = [], []
        for g in groups.values():
            fire = g["fire"]
            pin, ring = fire_pin(
                float(fire["latitude"]), float(fire["longitude"]), float(fire["frp"]),
                f"{place_name(fire['address'])}\n{app.when(detected_at(fire))}",
            )
            pins.append(pin)
            self.rings.append(ring)
        self.map.controls = self.base_layers + pins
        newest_first = sorted(groups.values(), key=lambda g: detected_at(g["fire"]), reverse=True)
        self.list.controls = [fire_card(app, g["fire"], g["count"]) for g in newest_first]

        if status == "loading":
            self.status.value = t("fires.getting")
        elif status == "nasa_error":
            self.status.value = t("fires.nasa_error")
        elif status == "lookup_error":
            self.status.value = t("fires.lookup_error")
        elif status == "checking":
            self.status.value = t("fires.so_far", count=len(groups)) if groups else t("fires.checking", count=fires["total"])
        elif not groups:
            self.status.value = t("fires.none", days=FIRE_DAYS)
        elif len(groups) == 1:
            self.status.value = t("fires.found_one", days=FIRE_DAYS)
        else:
            self.status.value = t("fires.found_many", count=len(groups), days=FIRE_DAYS)


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


def top_bar(app: App) -> ft.Control:
    return ft.Container(
        padding=ft.Padding.only(left=20, right=10, top=10, bottom=8),
        content=ft.Row(
            [
                image("heat_seeker_logo.png", 163, 34),
                ft.IconButton(
                    ft.Icons.SETTINGS_OUTLINED, icon_color=INK, icon_size=26, tooltip=app.t("settings"),
                    on_click=lambda e: app.page.show_dialog(settings_sheet(app)),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
    )


class BottomNav:
    """Icon + label per screen; the active one turns green with a line under it."""

    ITEMS = [
        (ft.Icons.HOME_OUTLINED, ft.Icons.HOME, "nav.home"),
        (ft.Icons.LOCAL_FIRE_DEPARTMENT_OUTLINED, ft.Icons.LOCAL_FIRE_DEPARTMENT, "nav.fire_spread"),
        (ft.Icons.MAP_OUTLINED, ft.Icons.MAP, "nav.fires"),
    ]

    def __init__(self, app: App):
        self.icons, self.labels, self.lines = [], [], []
        items = []
        for index, (outlined, _, key) in enumerate(self.ITEMS):
            icon = ft.Icon(outlined, size=26)
            label = text(app.t(key), size=12.5, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            line = ft.Container(width=80, height=3, border_radius=2)
            self.icons.append(icon)
            self.labels.append(label)
            self.lines.append(line)
            items.append(
                ft.Container(
                    expand=True,
                    on_click=lambda e, i=index: app.go_to(i),
                    padding=ft.Padding.only(top=10),
                    content=ft.Column(
                        [icon, label, ft.Container(height=4), line],
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

    def select(self, index: int):
        for i, (outlined, filled, _) in enumerate(self.ITEMS):
            active = i == index
            self.icons[i].icon = filled if active else outlined
            self.icons[i].color = FOREST if active else INK
            self.labels[i].color = FOREST if active else INK
            self.labels[i].weight = ft.FontWeight.W_600 if active else None
            self.lines[i].bgcolor = FOREST if active else None


class Views:
    """Every screen, built in the app's current language."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.weather = WeatherPanel(app)
        self.shortcuts = Shortcuts(app)
        self.prediction = PredictionView(app)
        self.fires = FiresView(app)
        self.nav = BottomNav(app)

        check_location = ft.Container(
            on_click=lambda e: app.page.show_dialog(location_sheet(app)),
            ink=True,
            bgcolor=MINT,
            border_radius=14,
            height=58,
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PARK, color=FOREST, size=26),
                    text(t("home.check_location"), size=17, color=FOREST, weight=ft.FontWeight.W_500),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=12,
            ),
        )
        home = ft.Column(
            [self.weather.control, ft.Container(height=6), self.shortcuts.control, check_location],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.screens = [
            screen(home, heat_calculator(app)),
            screen(self.prediction.control, fire_simulation(app)),
            screen(self.fires.control),
        ]
        self.root = ft.Column([top_bar(app), *self.screens, self.nav.control], expand=True, spacing=0)

    def show_screen(self, index: int):
        self.nav.select(index)
        for i, s in enumerate(self.screens):
            s.visible = i == index

    def render_all(self):
        self.weather.render()
        self.shortcuts.render()
        self.prediction.render()
        self.fires.render()


def location_sheet(app: App) -> ft.BottomSheet:
    """Search any place in Georgia by name, or tap a built-in city."""
    t = app.t
    results = ft.Column(spacing=0)
    message = text("", color=MUTED, visible=False)

    def say(value: str):
        message.value = value
        message.visible = bool(value)

    def pick(key: str | None, name: str | None, lat: float, lon: float):
        app.page.pop_dialog()
        app.pick_place(key, name, lat, lon)

    def place_row(name: str, where: str, on_click) -> ft.Control:
        return ft.Container(
            on_click=on_click,
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
        results.controls = [
            place_row(app.city_name(name), app.region_name(region), lambda e, c=(name, lat, lon): pick(c[0], None, c[1], c[2]))
            for name, lat, lon, region in GEORGIAN_CITIES
        ]

    async def on_search(e):
        query = (search.value or "").strip()
        if not query:
            say("")
            show_cities()
            app.page.update()
            return
        say(t("location.searching"))
        app.page.update()
        try:
            places = await asyncio.to_thread(search_places, query, language=app.lang)
        except Exception:
            say(t("location.error"))
            app.page.update()
            return
        if places:
            say("")
            results.controls = [
                place_row(
                    p["name"], p["region"] or t("location.georgia"),
                    lambda e, p=p: pick(None, p["name"], p["latitude"], p["longitude"]),
                )
                for p in places
            ]
        else:
            say(t("location.none", query=query))
            results.controls = []
        app.page.update()

    search = input_field(t("location.search"), prefix_icon=ft.Icons.SEARCH, on_submit=on_search, autofocus=True)
    show_cities()
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        scrollable=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=24),
            content=ft.Column(
                [
                    text(t("location.title"), size=20, weight=ft.FontWeight.W_600),
                    intro(t("location.intro")),
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


def settings_sheet(app: App) -> ft.BottomSheet:
    t = app.t
    language = choice(
        [(code, name) for code, name in LANGUAGES.items()], app.lang,
        lambda e: app.set_language(e.control.selected[0]), width=300,
    )
    units = choice(
        [("C", t("settings.celsius")), ("F", t("settings.fahrenheit"))], app.unit,
        lambda e: app.set_unit(e.control.selected[0]), width=300,
    )
    heading = lambda key: text(t(key), size=15, weight=ft.FontWeight.W_600)  # noqa: E731
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=28),
            content=ft.Column(
                [
                    text(t("settings"), size=20, weight=ft.FontWeight.W_600),
                    ft.Container(height=4),
                    heading("settings.language"),
                    language,
                    ft.Container(height=6),
                    heading("settings.unit"),
                    units,
                    ft.Container(height=6),
                    heading("settings.sources"),
                    text(t("settings.sources_text"), size=13, color=MUTED),
                ],
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
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

    app = App(page)
    app.build()
    page.run_task(page.window.center)
    page.run_task(app.refresh_weather)
    page.run_task(app.load_fires)
    page.run_task(app.ping_forever)


if __name__ == "__main__":
    ft.run(main)
