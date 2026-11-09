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
    OBJECTS_PER_FOREST,
    PREDICTION_RUNS,
    SCENARIOS,
    TREE,
    count_trees,
    has_fire,
    make_forest,
    predict_spread,
    spread,
    start_fire,
)
from heat import fetch_current_weather, heat_risk_checker, search_places
from NASA_FIRMS_API import DAYS as FIRE_DAYS
from NASA_FIRMS_API import fetch_fires, iter_fires_in_georgia, place_name
import Testing
from translations import CITY_NAMES, COMPASS, LANGUAGES, MONTHS, REGION_NAMES, georgian_genitive, translate

APP_DIR = Path(__file__).parent
IMAGES = APP_DIR / "Images"
APP_ICON = IMAGES / "icon.ico"

WINDOW_WIDTH = 390
WINDOW_HEIGHT = 844
PAGE_PADDING = 20

GRID_SIZE = 10
STEP_SECONDS = 0.25  # pause between fire spread steps in the Predict fire animation
SAMPLE_CELL = 26  # px per cell in the prediction forest
WEATHER_REFRESH_SECONDS = 15 * 60  # Open-Meteo updates current weather every 15 minutes
CASE_OBJECTS = {key: obj for key, _, obj in SCENARIOS}

# Design system palette
CANVAS = "#F8F9FA"  # background
CARD = "#FFFFFF"  # surfaces (cards)
PANEL = "#F3F4F6"  # neutral soft fill: map, loading states
LINE = "#E5E7EB"  # borders, dividers
FOREST = "#1A7F4B"  # primary green: main actions, active states, positive status
MINT = "#E8F5EE"  # soft green: positive status backgrounds, selected cards
INK = "#111827"  # text primary
MUTED = "#6B7280"  # text secondary
FAINT = "#9CA3AF"  # text tertiary
FLAME = "#DC2626"  # danger / warning, fires
FLAME_TINT = "#FEE2E2"
BURNED = "#D1D5DB"  # burned tree in the forest grids

# Inter, bundled in Images/fonts (OFL). Flet registers one file per family name, so each
# weight is its own family; Georgian letters fall back to the system's Georgian font.
FONT = "Inter"
FONT_FILES = {
    "Inter": "/fonts/Inter-Regular.ttf",
    "Inter Medium": "/fonts/Inter-Medium.ttf",
    "Inter SemiBold": "/fonts/Inter-SemiBold.ttf",
    "Inter Bold": "/fonts/Inter-Bold.ttf",
}
_WEIGHT_FAMILY = {
    ft.FontWeight.W_500: "Inter Medium",
    ft.FontWeight.W_600: "Inter SemiBold",
    ft.FontWeight.W_700: "Inter Bold",
}


def font_for(weight) -> str:
    return _WEIGHT_FAMILY.get(weight, FONT)

# Soft elevation: 0 1px 3px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.04)
SHADOW = [
    ft.BoxShadow(blur_radius=3, offset=ft.Offset(0, 1), color=ft.Colors.with_opacity(0.06, "#000000")),
    ft.BoxShadow(blur_radius=12, offset=ft.Offset(0, 4), color=ft.Colors.with_opacity(0.04, "#000000")),
]

# Heat risk bands, coolest to hottest: (level, text colour, upper bound of heat index in °F)
RISK_BANDS = [
    ("Safe", FOREST, 80),
    ("Caution", "#CA8A04", 90),
    ("Extreme Caution", "#EA580C", 103),
    ("Danger", FLAME, 125),
    ("Extreme Danger", "#991B1B", 140),
]
RISK_COLORS = {level: color for level, color, _ in RISK_BANDS}
RISK_GRADIENT = ["#22C55E", "#EAB308", "#EF4444"]
# Meter thumb fill: the gradient colour under each band, so the thumb reads as "you are here"
RISK_THUMB = {"Safe": "#22C55E", "Caution": "#84CC16", "Extreme Caution": "#EAB308", "Danger": "#F97316", "Extreme Danger": "#EF4444"}
SCALE_MIN_F = 40

# Fire danger levels from the prediction: (text colour, card tint). Soft green only when it's safe.
DANGER_COLORS = {
    "Low": (FOREST, MINT),
    "Moderate": ("#A16207", "#FEF9C3"),
    "High": ("#C2410C", "#FFEDD5"),
    "Extreme": ("#B91C1C", FLAME_TINT),
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
    return ft.Text(value, size=size, color=color, weight=weight, font_family=font_for(weight), text_align=text_align, **kwargs)


def rich(template_text: str, bold_color: str | None = None, bold_weight=ft.FontWeight.W_700) -> list[ft.TextSpan]:
    """Turn 'plain **bold** plain' into spans; bold parts can take a colour and weight."""
    spans = []
    for i, part in enumerate(re.split(r"\*\*", template_text)):
        if part:
            bold = i % 2 == 1
            spans.append(
                ft.TextSpan(
                    part,
                    ft.TextStyle(
                        weight=bold_weight if bold else None,
                        font_family=font_for(bold_weight) if bold else None,
                        color=bold_color if bold else None,
                    ),
                )
            )
    return spans


def title(value: str, lang: str = "en") -> ft.Text:
    # Georgian words are longer and its letters wider, so screen titles step down a size
    return text(value, size=24 if lang == "en" else 21, weight=ft.FontWeight.W_600)


def section_title(value: str) -> ft.Text:
    return text(value, size=17, weight=ft.FontWeight.W_600)


def intro(value: str) -> ft.Text:
    """The line under a screen title that tells a new user what the screen is for."""
    return text(value, size=14.5, color=MUTED)


def image(name: str, width: float, height: float | None = None) -> ft.Image:
    # Served from the assets folder (Images), so it also works on a phone or in a browser
    return ft.Image(src=f"/{name}", width=width, height=height or width, fit=ft.BoxFit.CONTAIN)


def card(content: ft.Control, **kwargs) -> ft.Container:
    """White surface with the soft two-layer shadow."""
    kwargs.setdefault("padding", 16)
    return ft.Container(content=content, bgcolor=CARD, border_radius=16, shadow=SHADOW, **kwargs)


def icon_badge(icon: ft.Control, tint: str = MINT, size: int = 44) -> ft.Container:
    """An icon on a soft circular background."""
    return ft.Container(icon, width=size, height=size, border_radius=size / 2, bgcolor=tint, alignment=ft.Alignment.CENTER)


def primary_button(label: str, on_click) -> ft.FilledButton:
    return ft.FilledButton(
        label,
        on_click=on_click,
        height=48,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DISABLED: LINE, ft.ControlState.DEFAULT: FOREST},
            color={ft.ControlState.DISABLED: MUTED, ft.ControlState.DEFAULT: CARD},
            overlay_color=ft.Colors.with_opacity(0.12, CARD),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=24),
            text_style=ft.TextStyle(font_family=font_for(ft.FontWeight.W_600), size=16, weight=ft.FontWeight.W_600),
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
            text_style=ft.TextStyle(font_family=font_for(ft.FontWeight.W_600), size=14, weight=ft.FontWeight.W_600),
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
        return ft.Icon(ft.Icons.PARK, color=BURNED, size=size * 0.82)  # burned tree
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
        self.fire_run: dict | None = None  # last Predict fire result: case, grid, burned, total, wind
        self.animating = False
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
        self.fire_run = None
        self.go_to(HOME)
        self.page.run_task(self.refresh_weather)

    # --- Data -------------------------------------------------------------------
    async def refresh_weather(self):
        self.weather_status = "loading"
        self.prediction_status = "running" if self.weather else "waiting"
        self.views.render_all()
        self.page.update()
        try:
            if Testing.TESTING:
                w = Testing.test_weather()
            else:
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

    async def refresh_forever(self):
        """Fetch the live weather again every 15 minutes; the prediction follows it."""
        while True:
            await asyncio.sleep(WEATHER_REFRESH_SECONDS)
            if not self.animating:
                await self.refresh_weather()

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
            detections = Testing.test_fires() if Testing.TESTING else await asyncio.to_thread(fetch_fires)
        except Exception:
            self.fires["status"] = "nasa_error"
            self._render_fires()
            return

        self.fires.update(status="checking", total=len(detections))
        self._render_fires()
        # One fire usually shows up as several detections a few hundred metres apart:
        # group them by ~1 km cell, keep the newest, and count the rest.
        groups = self.fires["groups"]
        # Test fires already carry an address, so they skip the OpenStreetMap look-up
        located = iter(detections) if Testing.TESTING else iter_fires_in_georgia(detections)
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


def metric_label(value: str) -> ft.Text:
    return text(value, size=12, color=MUTED, weight=ft.FontWeight.W_500)


def metric(icon: ft.IconData, label: str | ft.Text, value: ft.Text) -> ft.Control:
    """One light card in the Humidity / Wind / Clouds row: icon, value, label."""
    return card(
        ft.Column(
            [
                ft.Icon(icon, color=MUTED, size=18),
                ft.Container(height=6),
                value,
                label if isinstance(label, ft.Text) else metric_label(label),
            ],
            spacing=0,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        padding=ft.Padding.symmetric(horizontal=6, vertical=10),
    )


# WMO weather codes reported by Open-Meteo
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
SNOW_CODES = {71, 73, 75, 77, 85, 86}
FOG_CODES = {45, 48}
WINDY_KMH = 30


def weather_icon_name(w: dict) -> str:
    """Which of the weathers.png icons fits the current weather, most noticeable condition first."""
    code = w.get("weather_code", 0)
    if code in SNOW_CODES:
        return "weather_snow.png"
    if code in RAIN_CODES:
        return "weather_rain.png"
    if w["wind_speed_10m"] >= WINDY_KMH:
        return "weather_wind.png"
    if not w["is_day"]:
        return "weather_night.png"
    if code in FOG_CODES or w["cloud_cover"] >= 60:
        return "weather_cloud.png"
    return "weather_sun.png"


def weather_picture(w: dict) -> ft.Control:
    return image(weather_icon_name(w), 72)


SCALE_WIDTH = WINDOW_WIDTH - 2 * PAGE_PADDING - 26  # content width inside the window frame and scrollbar
MARKER = 24  # 12px radius
THUMB_SHADOW = [
    ft.BoxShadow(blur_radius=6, offset=ft.Offset(0, 2), color=ft.Colors.with_opacity(0.18, "#000000")),
    ft.BoxShadow(blur_radius=1, offset=ft.Offset(0, 0), color=ft.Colors.with_opacity(0.10, "#000000")),
]


class WeatherPanel:
    """Location, temperature, feels-like, heat risk meter and conditions on Home."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.city = text("", size=15, color=MUTED, weight=ft.FontWeight.W_500)
        location = ft.PopupMenuButton(
            tooltip=t("weather.change_location"),
            menu_position=ft.PopupMenuPosition.UNDER,
            content=ft.Container(
                ft.Row(
                    [ft.Icon(ft.CupertinoIcons.MAP_PIN, color=MUTED, size=17), self.city,
                     ft.Icon(ft.CupertinoIcons.CHEVRON_DOWN, color=FAINT, size=13)],
                    spacing=4,
                    tight=True,
                ),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                border_radius=999,
            ),
            items=[
                ft.PopupMenuItem(
                    content=text(app.city_name(name), size=15, text_align=ft.TextAlign.LEFT),
                    on_click=lambda e, c=(name, lat, lon): app.pick_place(c[0], None, c[1], c[2]),
                )
                for name, lat, lon, _ in GEORGIAN_CITIES
            ],
        )
        self.degrees = text("–", size=60, weight=ft.FontWeight.W_700, style=ft.TextStyle(letter_spacing=-0.5, height=1.05))
        self.picture = ft.Container(width=76, height=72, alignment=ft.Alignment.CENTER)
        self.feels = text("", size=15, color=MUTED)
        self.marker = ft.Container(
            width=MARKER, height=MARKER, border_radius=MARKER / 2, bgcolor=FOREST, border=ft.Border.all(4, CARD),
            shadow=THUMB_SHADOW, left=0, top=0, visible=False,
        )
        track = ft.Container(
            width=SCALE_WIDTH, height=6, top=(MARKER - 6) / 2, border_radius=3,
            gradient=ft.LinearGradient(begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT, colors=RISK_GRADIENT),
        )
        meter = ft.Column(
            [
                ft.Stack([track, self.marker], width=SCALE_WIDTH, height=MARKER),
                ft.Row(
                    [text(t("scale.safe"), size=12, color=FAINT), text(t("scale.extreme"), size=12, color=FAINT)],
                    width=SCALE_WIDTH,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.humidity, self.wind, self.clouds = (
            text("–", size=16, weight=ft.FontWeight.W_600, style=ft.TextStyle(height=1.3)) for _ in range(3)
        )
        self.wind_label = metric_label(t("weather.wind"))
        self.updated = text("", size=12.5, color=FAINT)

        gap = lambda h: ft.Container(height=h)  # noqa: E731
        self.control = ft.Column(
            [
                location,
                gap(4),
                ft.Row(
                    [self.degrees, self.picture],
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                gap(4),
                self.feels,
                gap(20),
                meter,
                gap(20),
                ft.Row(
                    [
                        metric(ft.CupertinoIcons.DROP, t("weather.humidity"), self.humidity),
                        metric(ft.CupertinoIcons.WIND, self.wind_label, self.wind),
                        metric(ft.CupertinoIcons.CLOUD, t("weather.clouds"), self.clouds),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                gap(10),
                self.updated,
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def render(self):
        app, t, w = self.app, self.app.t, self.app.weather
        self.city.value = app.city_name()
        self.feels.spans = []
        if app.weather_status == "error":
            self.feels.value = t("weather.error")
            self.updated.value = ""
            return
        if w is None:
            self.feels.value = t("weather.loading")
            return
        risk = heat_risk_checker(w["temperature_2m"], w["relative_humidity_2m"])
        self.degrees.value = f"{to_unit(w['temperature_2m'], app.unit):.0f}°"
        self.feels.value = ""
        self.feels.spans = rich(
            t("weather.feels", temp=f"{to_unit(risk['hi_c'], app.unit):.0f}", level=t(f"risk.{risk['level']}")),
            bold_color=RISK_COLORS[risk["level"]],
            bold_weight=ft.FontWeight.W_500,
        )
        self.marker.left = min(max(scale_position(risk["hi_f"]) * SCALE_WIDTH - MARKER / 2, 0), SCALE_WIDTH - MARKER)
        self.marker.visible = True
        self.marker.bgcolor = RISK_THUMB[risk["level"]]
        self.picture.content = weather_picture(w)
        self.humidity.value = f"{w['relative_humidity_2m']}%"
        self.wind.value = t("weather.wind_value", speed=f"{w['wind_speed_10m']:.0f}")
        self.wind_label.value = t("weather.wind_from", dir=app.compass(w["wind_direction_10m"]))
        self.clouds.value = f"{w['cloud_cover']}%"
        if app.weather_status == "loading":
            self.updated.value = t("weather.updating")
        else:
            self.updated.value = t("weather.updated", time=w["time"][-5:])


def shortcut(badge: ft.Container, heading: ft.Text, detail: ft.Text, on_click) -> ft.Container:
    """A white card that takes the user to another screen."""
    heading.text_align = detail.text_align = ft.TextAlign.LEFT
    return card(
        ft.Row(
            [
                badge,
                ft.Column([heading, detail], spacing=2, expand=True),
                ft.Icon(ft.CupertinoIcons.CHEVRON_RIGHT, color=FAINT, size=16),
            ],
            spacing=14,
        ),
        on_click=on_click,
        ink=True,
    )


class Shortcuts:
    """The two cards under the weather that lead to the other screens."""

    def __init__(self, app: App):
        self.app = app
        self.shield = ft.Icon(ft.CupertinoIcons.SHIELD, color=FOREST, size=21)
        self.danger_badge = icon_badge(self.shield, size=40)
        self.danger_title = text("", size=15, weight=ft.FontWeight.W_600)
        self.danger_detail = text("", size=13, color=MUTED)
        self.fires_icon = ft.Icon(ft.CupertinoIcons.MAP, color=FOREST, size=21)
        self.fires_badge = icon_badge(self.fires_icon, size=40)
        self.fires_title = text("", size=15, weight=ft.FontWeight.W_600)
        self.control = ft.Column(
            [
                shortcut(self.danger_badge, self.danger_title, self.danger_detail, lambda e: app.go_to(FIRE_SPREAD)),
                shortcut(
                    self.fires_badge, self.fires_title,
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
            self.shield.color, self.danger_badge.bgcolor = MUTED, PANEL
        elif status == "ready" and app.prediction:
            level = danger_label(app.prediction["result"]["danger"])
            self.danger_title.value = t("home.danger_today", level=t(f"danger.{level}"))
            self.danger_detail.value = t(f"advice.{level}")
            self.shield.color, self.danger_badge.bgcolor = DANGER_COLORS[level]
        else:
            self.danger_title.value = (
                t("home.danger_loading_in", city=app.city_name()) if app.prediction else t("home.danger_loading")
            )
            self.danger_detail.value = t("home.danger_hint")
            self.shield.color, self.danger_badge.bgcolor = MUTED, PANEL

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
        if fires["groups"]:
            self.fires_icon.color, self.fires_badge.bgcolor = FLAME, FLAME_TINT
        else:
            self.fires_icon.color, self.fires_badge.bgcolor = FOREST, MINT


def check_location_button(app: App) -> ft.Container:
    """Full-width primary pill that opens the location search."""
    return ft.Container(
        on_click=lambda e: app.page.show_dialog(location_sheet(app)),
        ink=True,
        bgcolor=FOREST,
        border_radius=999,
        height=52,
        shadow=SHADOW,
        content=ft.Row(
            [
                ft.Icon(ft.Icons.PARK, color=CARD, size=21),
                text(app.t("home.check_location"), size=16, color=CARD, weight=ft.FontWeight.W_600),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        ),
    )


def heat_calculator(app: App) -> ft.Control:
    t = app.t
    temp_field = input_field(t("calc.temperature"), "35", "°C", expand=True, keyboard_type=ft.KeyboardType.NUMBER)
    rh_field = input_field(t("calc.humidity"), "60", "%", expand=True, keyboard_type=ft.KeyboardType.NUMBER)
    message = text("", size=14, color=FLAME)
    result = text("", size=24, weight=ft.FontWeight.W_600)
    level = text("", size=15, weight=ft.FontWeight.W_500)

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
            section_title(t("calc.title")),
            intro(t("calc.intro")),
            ft.Container(height=8),
            ft.Row([temp_field, rh_field], spacing=12),
            ft.Container(height=4),
            ft.Row([primary_button(t("calc.check"), on_check)], alignment=ft.MainAxisAlignment.CENTER),
            message,
            result,
            level,
        ],
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )


# ---------------------------------------------------------------------------
# Fire risk screen
# ---------------------------------------------------------------------------


def scenario_card(app: App, result: dict, selected: bool, on_click) -> ft.Control:
    """Selected: primary green border on soft green. Unselected: white with a light border."""
    return ft.Container(
        expand=True,
        on_click=on_click,
        ink=True,
        bgcolor=MINT if selected else CARD,
        border_radius=16,
        border=ft.Border.all(1.5, FOREST) if selected else ft.Border.all(1, LINE),
        padding=ft.Padding.symmetric(horizontal=4, vertical=16),
        content=ft.Column(
            [
                ft.Container(image(CASE_ICONS[result["key"]], 40, 40), height=44, alignment=ft.Alignment.CENTER),
                text(f"{result['avg_percent']:.0f}%", size=24, weight=ft.FontWeight.W_600),
                ft.Container(
                    text(app.t(f"case.{result['key']}"), size=13, color=INK if selected else MUTED, weight=ft.FontWeight.W_500),
                    height=36, alignment=ft.Alignment.TOP_CENTER,
                ),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


class PredictionView:
    """Fire danger for the chosen place, worked out from live weather, plus Predict fire."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.intro = intro("")
        self.flame = ft.Icon(ft.CupertinoIcons.FLAME, color=FOREST, size=22)
        self.danger = text("", size=17, weight=ft.FontWeight.W_600)
        self.conditions = text("", size=13.5, color=MUTED)
        self.explain = text("", size=14, color=INK)
        self.panel = ft.Container(
            bgcolor=MINT,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=18, vertical=16),
            content=ft.Column(
                [
                    ft.Row([self.flame, self.danger], alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True),
                    self.conditions,
                    self.explain,
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.cards = ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)

        # Detail for the selected case: built once, so Predict fire can animate the same grid
        self.case_title = section_title("")
        self.case_about = text("", size=14.5, color=MUTED)
        self.callout = ft.Text("", size=17, color=INK, font_family=FONT, text_align=ft.TextAlign.CENTER)
        self.callout_detail = text("", size=13.5, color=MUTED)
        grid, self.cells = forest_grid(GRID_SIZE, GRID_SIZE, SAMPLE_CELL)
        self.predict_button = primary_button(t("predict.button"), self.predict)
        self.outcome = ft.Text("", size=14, color=INK, font_family=FONT, text_align=ft.TextAlign.CENTER)
        self.detail = ft.Column(
            [
                ft.Container(height=16),
                self.case_title,
                self.case_about,
                ft.Container(height=4),
                card(
                    ft.Column(
                        [
                            self.callout,
                            self.callout_detail,
                            ft.Container(grid, margin=ft.Margin.only(top=10), alignment=ft.Alignment.CENTER),
                        ],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=18),
                ),
                ft.Container(height=8),
                ft.Row([self.predict_button], alignment=ft.MainAxisAlignment.CENTER),
                self.outcome,
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            visible=False,
        )
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
        if self.app.animating:
            return
        self.app.selected_case = key
        self.render()
        self.app.page.update()

    async def predict(self, e):
        """Fetch the current weather, then light a fire in the selected forest and let it spread."""
        app, t = self.app, self.app.t
        if app.animating:
            return
        app.animating = True
        app.fire_run = None
        self.render()
        app.page.update()

        await app.refresh_weather()
        while app._predicting:  # a refresh started elsewhere may still be finishing
            await asyncio.sleep(0.1)
        if app.weather_status == "error" or not app.prediction:
            app.animating = False
            app.views.prediction.render(message=t("predict.offline"))
            app.page.update()
            return

        p, key = app.prediction["result"], app.selected_case
        grid = make_forest(GRID_SIZE, CASE_OBJECTS[key], OBJECTS_PER_FOREST)
        total = count_trees(grid)
        start_fire(grid, CASE_OBJECTS[key])
        while True:
            view = app.views.prediction  # the screen is rebuilt if the language changes meanwhile
            view.outcome.spans = []
            view.outcome.value, view.outcome.color = app.t("predict.burning", toward=app.t(f"toward.{p['wind']}")), FLAME
            paint_forest(view.cells, grid, SAMPLE_CELL)
            app.page.update()
            if not has_fire(grid):
                break
            await asyncio.sleep(STEP_SECONDS)
            spread(grid, p["wind"], p["danger"], p["wind_strength"])

        app.fire_run = {"case": key, "grid": grid, "burned": total - count_trees(grid), "total": total, "wind": p["wind"]}
        app.animating = False
        app.views.prediction.render()
        app.page.update()

    def render(self, message: str | None = None):
        app, t = self.app, self.app.t
        city = app.city_name()
        self.intro.value = t("risk.intro", city=city, city_of=georgian_genitive(city))
        self.panel.bgcolor, self.flame.color = MINT, FOREST
        self.predict_button.disabled = app.animating
        self.predict_button.content = t("predict.running") if app.animating else t("predict.button")

        self.explain.value = ""
        if app.prediction_status == "error" and not app.prediction:
            self.panel.bgcolor, self.flame.color = PANEL, MUTED
            self.danger.value, self.danger.color = t("risk.unavailable"), MUTED
            self.conditions.value = t("risk.no_weather")
            return
        if not app.prediction:
            self.panel.bgcolor, self.flame.color = PANEL, MUTED
            self.danger.value, self.danger.color = t("risk.working"), INK
            self.conditions.value = t("risk.simulating", runs=PREDICTION_RUNS)
            return

        w, p = app.prediction["weather"], app.prediction["result"]
        level = danger_label(p["danger"])
        color, tint = DANGER_COLORS[level]
        if not w["is_day"]:
            light = "night"
        elif p["sun"] < 0.05:
            light = "overcast"
        else:
            light = "sun"
        self.panel.bgcolor, self.flame.color = tint, color
        if app.prediction_status == "running":
            self.danger.value, self.danger.color = t("risk.working"), INK
        else:
            self.danger.value, self.danger.color = t("risk.danger", level=t(f"danger.{level}")), color
        self.conditions.value = t(
            "risk.conditions",
            temp=f"{to_unit(w['temperature_2m'], app.unit):.0f}", unit=app.unit,
            humidity=w["relative_humidity_2m"], speed=f"{w['wind_speed_10m']:.0f}",
            light=t(f"risk.light.{light}", percent=f"{p['sun'] * 100:.0f}"),
        )
        self.explain.value = t(f"risk.explain.{light}", toward=t(f"toward.{p['wind']}"))

        results = p["results"]
        self.cards.controls = [
            scenario_card(app, r, r["key"] == app.selected_case, lambda e, k=r["key"]: self.select(k)) for r in results
        ]
        result = next(r for r in results if r["key"] == app.selected_case)
        self.detail.visible = True
        self.case_title.value = t(f"case.{result['key']}")
        self.case_about.value = t(f"case.{result['key']}.about")
        self.callout.spans = rich(t("risk.callout", burned=f"{result['avg_burned']:.0f}", total=result["total_trees"]))
        self.callout_detail.value = t(
            "risk.callout_detail", chance=f"{result['fire_chance']:.0f}", worst=result["max_burned"]
        )
        if app.animating:
            return  # the animation owns the grid and the outcome line

        run = app.fire_run if app.fire_run and app.fire_run["case"] == app.selected_case else None
        paint_forest(self.cells, run["grid"] if run else result["sample_grid"], SAMPLE_CELL)
        self.outcome.spans = []
        if message:
            self.outcome.value, self.outcome.color = message, FLAME
        elif run:
            self.outcome.value, self.outcome.color = "", INK
            self.outcome.spans = rich(
                t("predict.result", burned=run["burned"], total=run["total"], toward=t(f"toward.{run['wind']}")),
                bold_color=FLAME if run["burned"] else FOREST,
            )
        else:
            self.outcome.value, self.outcome.color = t("predict.hint"), MUTED


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
MAP_WIDTH = 302
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
        cv.Path(outline, paint=ft.Paint(color=PANEL, style=ft.PaintingStyle.FILL)),
        cv.Path(
            outline,
            paint=ft.Paint(color="#374151", style=ft.PaintingStyle.STROKE, stroke_width=1.5, stroke_join=ft.StrokeJoin.ROUND),
        ),
    ]
    labels = []
    for name, lat, lon, side in MAP_CITIES:
        x, y = map_xy(lat, lon)
        shapes.append(cv.Circle(x, y, 3, paint=ft.Paint(color=MUTED)))
        left = x + 6 if side == "right" else x - 6 - CITY_LABEL_WIDTH
        align = ft.TextAlign.LEFT if side == "right" else ft.TextAlign.RIGHT
        labels.append(
            ft.Text(
                app.city_name(name), size=12.5, color=INK, weight=ft.FontWeight.W_500,
                font_family=font_for(ft.FontWeight.W_500),
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
                icon_badge(ft.Icon(ft.CupertinoIcons.FLAME, color=FLAME, size=21), FLAME_TINT),
                ft.Column(
                    [
                        left(place_name(fire["address"]), size=15.5, weight=ft.FontWeight.W_600),
                        left(app.when(detected_at(fire)), size=13.5, color=MUTED),
                        left(details, size=12.5, color=FAINT),
                    ],
                    spacing=1,
                    expand=True,
                ),
                ft.IconButton(
                    ft.CupertinoIcons.ARROW_UP_RIGHT_SQUARE, icon_color=FOREST, icon_size=20, tooltip=t("fires.open_map"),
                    url=f"https://www.google.com/maps?q={lat},{lon}",
                ),
            ],
            spacing=14,
        ),
        padding=ft.Padding.only(left=16, right=6, top=14, bottom=14),
    )


class FiresView:
    """Map + list of fires in Georgia, drawn from `app.fires`."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.map = georgia_map(app)
        self.base_layers = list(self.map.controls)
        self.rings: list[ft.Container] = []
        self.status = text("", size=15)
        self.status_icon = ft.Icon(ft.CupertinoIcons.ANTENNA_RADIOWAVES_LEFT_RIGHT, color=MUTED, size=22)
        self.status_badge = icon_badge(self.status_icon, PANEL, 48)
        self.list = ft.Column(spacing=12)
        self.refresh = ft.IconButton(
            ft.CupertinoIcons.ARROW_CLOCKWISE, icon_color=MUTED, icon_size=20, tooltip=t("fires.check_again"),
            on_click=lambda e: app.page.run_task(app.load_fires),
        )
        self.control = ft.Column(
            [
                ft.Row(
                    [ft.Container(width=40), ft.Container(title(t("fires.title"), app.lang), expand=True), self.refresh],
                    spacing=0,
                ),
                intro(t("fires.intro", days=FIRE_DAYS)),
                ft.Container(height=8),
                card(self.map, padding=ft.Padding.symmetric(vertical=28), alignment=ft.Alignment.CENTER),
                card(
                    ft.Column(
                        [self.status_badge, self.status],
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(horizontal=20, vertical=20),
                ),
                self.list,
                ft.Container(text(t("fires.credits"), size=11.5, color=FAINT), margin=ft.Margin.only(top=12)),
            ],
            spacing=12,
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

        if groups:
            self.status_icon.color, self.status_badge.bgcolor = FLAME, FLAME_TINT
        elif status == "done":
            self.status_icon.color, self.status_badge.bgcolor = FOREST, MINT
        else:
            self.status_icon.color, self.status_badge.bgcolor = MUTED, PANEL
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


def screen(*sections: ft.Control, footer: ft.Control | None = None) -> ft.Container:
    """Pad sections, separate them with space and a hairline, and let the screen scroll on its own.

    A footer stays pinned under the scrolling part, 20px above the tab bar, so it is never cut off.
    """
    controls = []
    for section in sections:
        if controls:
            controls.append(ft.Divider(height=56, color=LINE))
        controls.append(section)
    scrolling = ft.Container(
        expand=True,
        content=ft.Column(controls, scroll=ft.ScrollMode.AUTO, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.Padding.only(left=PAGE_PADDING, right=PAGE_PADDING, top=8, bottom=32 if footer is None else 16),
    )
    if footer is None:
        return scrolling
    pinned = ft.Container(footer, padding=ft.Padding.only(left=PAGE_PADDING, right=PAGE_PADDING, top=12, bottom=20))
    return ft.Container(expand=True, content=ft.Column([scrolling, pinned], spacing=0))


def test_tag(app: App) -> ft.Control:
    """Amber pill shown while Testing.TESTING is on, so test values aren't mistaken for live data."""
    return ft.Container(
        text(app.t("test.tag"), size=11, color="#92400E", weight=ft.FontWeight.W_600),
        bgcolor="#FEF3C7",
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        tooltip=app.t("test.tooltip"),
    )


def top_bar(app: App) -> ft.Control:
    return ft.Container(
        height=56,
        padding=ft.Padding.only(left=PAGE_PADDING, right=8),
        content=ft.Row(
            [
                ft.Row(
                    [
                        image("heat_seeker_mark.png", 37, 24),
                        text("Heat-Seeker", size=17, weight=ft.FontWeight.W_600),
                        test_tag(app) if Testing.TESTING else ft.Container(),
                    ],
                    spacing=8,
                    tight=True,
                ),
                ft.IconButton(
                    ft.CupertinoIcons.GEAR_ALT, icon_color=MUTED, icon_size=22, tooltip=app.t("settings"),
                    on_click=lambda e: app.page.show_dialog(settings_sheet(app)),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
    )


class BottomNav:
    """Line icon + label per screen. Active: filled icon on a soft green pill, green label."""

    ITEMS = [
        (ft.CupertinoIcons.HOUSE, ft.CupertinoIcons.HOUSE_FILL, "nav.home"),
        (ft.CupertinoIcons.FLAME, ft.CupertinoIcons.FLAME_FILL, "nav.fire_spread"),
        (ft.CupertinoIcons.MAP, ft.CupertinoIcons.MAP_FILL, "nav.fires"),
    ]

    def __init__(self, app: App):
        self.icons, self.pills, self.labels = [], [], []
        items = []
        for index, (outlined, _, key) in enumerate(self.ITEMS):
            icon = ft.Icon(outlined, size=22)
            pill = ft.Container(icon, width=56, height=30, border_radius=15, alignment=ft.Alignment.CENTER)
            label = text(app.t(key), size=11.5, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            self.icons.append(icon)
            self.pills.append(pill)
            self.labels.append(label)
            items.append(
                ft.Container(
                    expand=True,
                    on_click=lambda e, i=index: app.go_to(i),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        [pill, label],
                        spacing=3,
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        self.control = ft.Container(
            height=70,
            bgcolor=CARD,
            border=ft.Border.only(top=ft.BorderSide(1, LINE)),
            padding=ft.Padding.only(top=2),
            content=ft.Row(items, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        )

    def select(self, index: int):
        for i, (outlined, filled, _) in enumerate(self.ITEMS):
            active = i == index
            self.icons[i].icon = filled if active else outlined
            self.icons[i].color = FOREST if active else FAINT
            self.pills[i].bgcolor = MINT if active else None
            weight = ft.FontWeight.W_600 if active else ft.FontWeight.W_500
            self.labels[i].weight, self.labels[i].font_family = weight, font_for(weight)
            self.labels[i].color = FOREST if active else MUTED


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

        home = ft.Column(
            [
                self.weather.control,
                ft.Container(height=24),
                self.shortcuts.control,
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.screens = [
            screen(home, heat_calculator(app), footer=check_location_button(app)),
            screen(self.prediction.control),
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
                    ft.Icon(ft.CupertinoIcons.LOCATION, color=FOREST, size=20),
                    ft.Column(
                        [
                            text(name, size=15, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.LEFT),
                            text(where, size=13, color=MUTED, text_align=ft.TextAlign.LEFT),
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

    search = input_field(t("location.search"), prefix_icon=ft.CupertinoIcons.SEARCH, on_submit=on_search, autofocus=True)
    show_cities()
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        scrollable=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=24),
            content=ft.Column(
                [
                    title(t("location.title"), app.lang),
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
    heading = lambda key: text(t(key), size=13, color=MUTED, weight=ft.FontWeight.W_500)  # noqa: E731
    return ft.BottomSheet(
        bgcolor=CANVAS,
        show_drag_handle=True,
        content=ft.Container(
            padding=ft.Padding.only(left=20, right=20, bottom=28),
            content=ft.Column(
                [
                    title(t("settings"), app.lang),
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
    page.fonts = FONT_FILES

    app = App(page)
    app.build()
    page.run_task(page.window.center)
    page.run_task(app.refresh_weather)
    page.run_task(app.refresh_forever)
    page.run_task(app.load_fires)
    page.run_task(app.ping_forever)


if __name__ == "__main__":
    ft.run(main, assets_dir="Images")
