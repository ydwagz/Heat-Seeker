import asyncio
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import flet as ft
import flet.canvas as cv

from core.fire_sim import (
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
from core import fwi
from core.heat import fetch_current_weather, fetch_fire_weather, heat_risk_checker, search_places
from core.nasa_firms import DAYS as FIRE_DAYS
from core.nasa_firms import (
    MIN_DAYS_SEEN,
    days_seen,
    fetch_fires,
    fetch_history,
    iter_fires_in_georgia,
    nearby_site,
    place_name,
)
import Testing
from translations import (
    CITY_NAMES,
    COMPASS,
    LANGUAGES,
    MONTHS,
    REGION_NAMES,
    WEEKDAYS,
    georgian_genitive,
    translate,
)

APP_DIR = Path(__file__).parent
IMAGES = APP_DIR / "assets"
APP_ICON = IMAGES / "brand" / "icon.ico"

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
MUTED = "#4B5563"  # text secondary (a step darker than usual, for reading outdoors)
FAINT = "#6B7280"  # text tertiary
FLAME = "#DC2626"  # danger / warning, fires
FLAME_TINT = "#FEE2E2"
BURNED = "#57534E"  # charred tree in the forest grids
BURNING = "#F97316"  # flames in the forest grids
# Living trees vary a little in shade so a calm, all-green forest doesn't look flat
TREE_SHADES = ["#1A7F4B", "#15803D", "#22915A", "#166534"]

# Inter for Latin letters and digits, Noto Sans Georgian for Georgian letters, both bundled
# in assets/fonts (OFL) in four real weights. Flet registers one file per family name, so each
# weight is its own family. Bundling the Georgian font matters on phones: Android's built-in
# Georgian font draws thinner, so Georgian headers looked lighter there than on the PC.
FONT = "Inter"
GEORGIAN = "Noto Georgian"
FONT_FILES = {
    "Inter": "/fonts/Inter-Regular.ttf",
    "Inter Medium": "/fonts/Inter-Medium.ttf",
    "Inter SemiBold": "/fonts/Inter-SemiBold.ttf",
    "Inter Bold": "/fonts/Inter-Bold.ttf",
    "Noto Georgian": "/fonts/NotoSansGeorgian-Regular.ttf",
    "Noto Georgian Medium": "/fonts/NotoSansGeorgian-Medium.ttf",
    "Noto Georgian SemiBold": "/fonts/NotoSansGeorgian-SemiBold.ttf",
    "Noto Georgian Bold": "/fonts/NotoSansGeorgian-Bold.ttf",
}
_WEIGHT_SUFFIX = {ft.FontWeight.W_500: " Medium", ft.FontWeight.W_600: " SemiBold", ft.FontWeight.W_700: " Bold"}


def font_for(weight) -> str:
    return FONT + _WEIGHT_SUFFIX.get(weight, "")


def georgian_for(weight) -> list[str]:
    """Fallback family for Georgian letters, in the same weight as the Latin text around them."""
    return [GEORGIAN + _WEIGHT_SUFFIX.get(weight, "")]

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
# One 4-step risk palette for the whole app: green, yellow, orange, red
RISK_GRADIENT = ["#22C55E", "#EAB308", "#F97316", "#EF4444"]
# Heat-risk pill background for each band
HEAT_TINTS = {"Safe": MINT, "Caution": "#FEF9C3", "Extreme Caution": "#FFEDD5", "Danger": FLAME_TINT, "Extreme Danger": "#FECACA"}
# Meter thumb fill: the gradient colour under each band, so the thumb reads as "you are here"
RISK_THUMB = {"Safe": "#22C55E", "Caution": "#84CC16", "Extreme Caution": "#EAB308", "Danger": "#F97316", "Extreme Danger": "#EF4444"}
SCALE_MIN_F = 40

# Fire danger classes of EFFIS (from the Fire Weather Index): (text colour, card tint), as a
# traffic light anyone reads at a glance: green = safe, yellow = caution, red = danger, with the
# red getting darker as the danger grows. "Low/Moderate/High/Extreme" also colour the forest cases.
DANGER_COLORS = {
    "Very low": (FOREST, MINT),
    "Low": (FOREST, MINT),
    "Moderate": ("#A16207", "#FEF3C7"),
    "High": ("#DC2626", "#FEE2E2"),
    "Very high": ("#B91C1C", "#FEE2E2"),
    "Extreme": ("#7F1D1D", "#FECACA"),
}
SAFE_LEVELS = {"Very low", "Low"}

# Prediction case icons, and a light tint for each case's card when it isn't selected
CASE_ICONS = {"natural": "forest/sun_icon.png", "glass": "forest/glass_icon.png", "flammable": "forest/flammable_litter_icon.png"}
CASE_TINTS = {"natural": "#FFFBEB", "glass": "#EFF6FF", "flammable": "#FFF7ED"}

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
    return ft.Text(
        value, size=size, color=color, weight=weight, font_family=font_for(weight),
        font_family_fallback=georgian_for(weight), text_align=text_align, **kwargs,
    )


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
                        font_family_fallback=georgian_for(bold_weight) if bold else None,
                        color=bold_color if bold else None,
                    ),
                )
            )
    return spans


def title(value: str, lang: str = "en") -> ft.Text:
    # Georgian words are longer and its letters wider, so screen titles step down a size
    return text(value, size=28 if lang == "en" else 24, weight=ft.FontWeight.W_700)


def section_title(value: str) -> ft.Text:
    return text(value, size=17, weight=ft.FontWeight.W_600)


def intro(value: str) -> ft.Text:
    """The line under a screen title that tells a new user what the screen is for."""
    return text(value, size=16, color=MUTED)


def image(name: str, width: float, height: float | None = None) -> ft.Image:
    # Served from the assets folder, so it also works in the Android app and in a browser
    return ft.Image(src=f"/{name}", width=width, height=height or width, fit=ft.BoxFit.CONTAIN)


def card(content: ft.Control, **kwargs) -> ft.Container:
    """White surface with the soft two-layer shadow."""
    kwargs.setdefault("padding", 18)
    kwargs.setdefault("bgcolor", CARD)
    return ft.Container(content=content, border_radius=16, shadow=SHADOW, **kwargs)


def pill(label: ft.Text, color: str, tint: str, icon: ft.IconData | None = None) -> ft.Container:
    """A rounded status label, e.g. the heat risk under the temperature."""
    label.color = color
    parts = [ft.Icon(icon, color=color, size=15)] if icon else []
    return ft.Container(
        ft.Row([*parts, label], spacing=6, tight=True),
        bgcolor=tint,
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=14, vertical=7),
    )


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
            text_style=ft.TextStyle(font_family=font_for(ft.FontWeight.W_600), font_family_fallback=georgian_for(ft.FontWeight.W_600),
                size=16, weight=ft.FontWeight.W_600,
            ),
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
        text_style=ft.TextStyle(font_family=FONT, font_family_fallback=[GEORGIAN], size=16, color=INK),
        label_style=ft.TextStyle(font_family=FONT, font_family_fallback=[GEORGIAN], color=MUTED),
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
            text_style=ft.TextStyle(font_family=font_for(ft.FontWeight.W_600), font_family_fallback=georgian_for(ft.FontWeight.W_600),
                size=14, weight=ft.FontWeight.W_600,
            ),
        ),
    )


def to_unit(celsius: float, unit: str) -> float:
    return celsius * 9 / 5 + 32 if unit == "F" else celsius


# --- Forest grids drawn with icons ------------------------------------------


def forest_symbol(symbol: str, size: int, shade: int = 0) -> ft.Control | None:
    if symbol == TREE:
        return ft.Icon(ft.Icons.PARK, color=TREE_SHADES[shade % len(TREE_SHADES)], size=size * 0.82)
    if symbol == FIRE:
        return ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=BURNING, size=size * 0.86)
    if symbol == ASH:
        return ft.Icon(ft.Icons.PARK, color=BURNED, size=size * 0.82)  # charred tree
    if symbol == GLASS:
        return image("forest/glass_icon.png", size * 0.5, size * 0.72)
    if symbol == FLAMMABLE:
        return image("forest/flammable_litter_icon.png", size * 0.66, size * 0.74)
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
    for r, (row_cells, row) in enumerate(zip(cells, grid)):
        for c, (cell, symbol) in enumerate(zip(row_cells, row)):
            if cell.data != symbol:  # only rebuild cells that changed
                cell.data = symbol
                cell.content = forest_symbol(symbol, size, shade=(r * 7 + c * 3 + r * c) % 5)


# ---------------------------------------------------------------------------
# App state: data lives here, screens draw themselves from it
# ---------------------------------------------------------------------------


async def with_retry(fetch, *args, attempts: int = 2, wait: float = 1.5):
    """Run a blocking download in a worker thread, trying again once if it fails
    (a dropped connection or a busy server usually works a moment later)."""
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(fetch, *args)
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(wait)


def fire_weather_index(series: list[dict]) -> list[dict]:
    """Run the Canadian Fire Weather Index over the daily noon weather, oldest day first.

    Each day keeps its weather and gains an "fwi" entry (fwi.FWIResult). The past days only
    serve to bring the slow moisture codes (DMC, DC) up to date; the app shows today and the
    forecast days.
    """
    results = fwi.run([fwi.DayWeather(d["month"], d["temp"], d["rh"], d["wind"], d["rain"]) for d in series])
    return [{**day, "fwi": result} for day, result in zip(series, results)]


LOADER_BG = "#DCEAF6"  # same light blue as the app icon and the phone's splash screen


class LoadingScreen:
    """Loading, step 3 (steps 1 and 2 are the phone's splash and Flet's startup screen, set in
    pyproject.toml): the app's artwork, name and a progress bar over the app, on the same blue,
    until the first weather arrives. Then it fades into the Home screen."""

    MIN_SECONDS = 1.2  # long enough to read, so it doesn't just flash

    def __init__(self, app: "App"):
        self.app = app
        t = app.t
        self.shown_at = asyncio.get_event_loop().time()
        self.done = False
        self.art = ft.Container(
            image("splash.png", 220),
            scale=1.0,
            animate_scale=ft.Animation(1100, ft.AnimationCurve.EASE_IN_OUT),
        )
        self.control = ft.Container(
            left=0, top=0, right=0, bottom=0,
            bgcolor=LOADER_BG,
            alignment=ft.Alignment.CENTER,
            opacity=1.0,
            animate_opacity=ft.Animation(450, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                [
                    self.art,
                    text("Heat-Seeker", size=28, weight=ft.FontWeight.W_700),
                    text(t("loading.tagline"), size=14.5, color=MUTED),
                    ft.Container(height=26),
                    ft.ProgressBar(width=160, bar_height=4, border_radius=2, color=FOREST, bgcolor="#C3D7EA"),
                    ft.Container(height=10),
                    text(t("loading.weather", city=app.city_name()), size=13, color=MUTED),
                ],
                spacing=4,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    async def pulse(self):
        """Let the artwork gently breathe while waiting."""
        while not self.done:
            self.art.scale = 1.06 if self.art.scale == 1.0 else 1.0
            self.app.page.update()
            await asyncio.sleep(1.1)

    async def finish(self):
        elapsed = asyncio.get_event_loop().time() - self.shown_at
        if elapsed < self.MIN_SECONDS:
            await asyncio.sleep(self.MIN_SECONDS - elapsed)
        self.done = True
        self.control.opacity = 0
        self.app.page.update()
        await asyncio.sleep(0.5)
        if self.control in self.app.page.overlay:
            self.app.page.overlay.remove(self.control)
        self.app.page.update()


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
        # Fire Weather Index per day: past days (for the moisture codes) + today + 6 forecast days
        self.fire_days: list[dict] | None = None
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
        self.prefs = ft.SharedPreferences()  # remembers language and unit between launches
        self.loader: "LoadingScreen | None" = None  # shown until the first weather arrives

    # --- Saved settings ---------------------------------------------------------
    async def load_settings(self):
        try:
            lang, unit = await self.prefs.get("lang"), await self.prefs.get("unit")
        except Exception:
            return  # storage unavailable: keep the defaults
        if lang in LANGUAGES:
            self.lang = lang
        if unit in ("C", "F"):
            self.unit = unit

    async def save_setting(self, key: str, value: str):
        try:
            await self.prefs.set(key, value)
        except Exception:
            pass  # not being able to save a preference shouldn't break the app

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
        self.page.run_task(self.save_setting, "lang", lang)
        self.page.pop_dialog()
        self.build()
        self.page.show_dialog(settings_sheet(self))  # reopen so the switch is visible in the new language

    def set_unit(self, unit: str):
        self.unit = unit
        self.page.run_task(self.save_setting, "unit", unit)
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
        if Testing.TESTING:
            w, series = Testing.test_weather(), Testing.test_fire_weather()
        else:
            # Both downloads at once; each is retried, and one failing doesn't sink the other
            lat, lon = self.place["lat"], self.place["lon"]
            w, series = await asyncio.gather(
                with_retry(fetch_current_weather, lat, lon),
                with_retry(fetch_fire_weather, lat, lon),
                return_exceptions=True,
            )
        if isinstance(w, Exception):
            self.weather_status = "error"
            self.prediction_status = "error"
            self.views.render_all()
            self.page.update()
            self._hide_loader()
            return
        self.weather, self.weather_status = w, "ready"
        self.views.weather.render()
        self.page.update()
        self._hide_loader()
        if isinstance(series, Exception):  # live weather is shown, only the fire danger is missing
            self.fire_days, self.prediction = None, None
            self.prediction_status = "error"
            self.views.prediction.render()
            self.views.shortcuts.render()
            self.page.update()
            return
        self.fire_days = fire_weather_index(series)
        await self.run_prediction()

    def show_loader(self):
        self.loader = LoadingScreen(self)
        self.page.overlay.append(self.loader.control)
        self.page.update()
        self.page.run_task(self.loader.pulse)

    def _hide_loader(self):
        if self.loader:
            loader, self.loader = self.loader, None
            self.page.run_task(loader.finish)

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
        week = [d for d in self.fire_days if d["forecast"]]  # today first
        today = week[0]["fwi"]
        p = await asyncio.to_thread(
            predict_spread,
            today.fwi,
            w["wind_direction_10m"], w["wind_speed_10m"],
            w["is_day"], w["cloud_cover"],
        )
        self.prediction = {"weather": w, "result": p, "fwi": today, "week": week}
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
        history: dict[str, list[dict]] = {}  # earlier detections around each industrial site
        # Test fires already carry an address, so they skip the OpenStreetMap look-up
        located = iter(detections) if Testing.TESTING else iter_fires_in_georgia(detections, self.lang)
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
                industrial = await self._industrial_heat(fire, detections, history)
                groups[cell] = {"fire": fire, "count": 1, "industrial": industrial}
            else:
                group["count"] += 1
                if detected_at(fire) > detected_at(group["fire"]):
                    group["fire"] = fire
            self._render_fires()
        self.fires["status"] = "done"
        self.fires["checked"] = datetime.now(GEORGIA_TZ)
        self._render_fires()

    async def _industrial_heat(self, fire: dict, detections: list[dict], history: dict) -> dict | None:
        """{"site", "days"} when a hot spot sits at a factory and keeps coming back, else None."""
        lat, lon = float(fire["latitude"]), float(fire["longitude"])
        site = nearby_site(lat, lon)
        if site is None:
            return None
        if site["en"] not in history:
            try:
                if Testing.TESTING:
                    history[site["en"]] = Testing.test_history()
                else:
                    history[site["en"]] = await asyncio.to_thread(fetch_history, site["lat"], site["lon"])
            except Exception:
                history[site["en"]] = []  # no history: judge on the last 5 days alone
        seen = days_seen(lat, lon, history[site["en"]] + detections)
        return {"site": site, "days": seen} if seen >= MIN_DAYS_SEEN else None

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


def metric(icon: ft.IconData, label: str | ft.Text, value: ft.Text, color: str = MUTED, tint: str = PANEL) -> ft.Control:
    """One light card in the Humidity / Wind / Clouds row: coloured icon, value, label."""
    return card(
        ft.Column(
            [
                icon_badge(ft.Icon(icon, color=color, size=16), tint, size=30),
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


def day_icon_name(day: dict) -> str:
    """Picture for a forecast day: snow or rain first, then strong wind, then cloud or sun.
    Days are always shown as daytime, so there is no night picture here."""
    code = day.get("code") or 0
    if code in SNOW_CODES:
        return "weather_snow.png"
    if code in RAIN_CODES:
        return "weather_rain.png"
    if day.get("wind", 0) >= WINDY_KMH:
        return "weather_wind.png"
    if code in FOG_CODES or code == 3:  # fog or overcast
        return "weather_cloud.png"
    return "weather_sun.png"  # clear, mainly clear or partly cloudy


def weather_picture(w: dict) -> ft.Control:
    return image("weather/" + weather_icon_name(w), 72)


SCALE_WIDTH = 284  # fits inside the weather panel on phones as narrow as 360 dp
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
        self.heat_label = text("", size=15, weight=ft.FontWeight.W_600)
        self.heat_pill = pill(self.heat_label, FOREST, MINT, ft.CupertinoIcons.THERMOMETER)
        self.heat_pill.visible = False
        self.marker = ft.Container(
            width=MARKER, height=MARKER, border_radius=MARKER / 2, bgcolor=FOREST, border=ft.Border.all(4, CARD),
            shadow=THUMB_SHADOW, left=0, top=0, visible=False,
        )
        track = ft.Container(
            width=SCALE_WIDTH, height=8, top=(MARKER - 8) / 2, border_radius=4,
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
        weather = ft.Column(
            [
                location,
                gap(4),
                ft.Row(
                    [self.degrees, self.picture],
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                gap(6),
                self.heat_pill,
                gap(8),
                self.feels,
                gap(20),
                meter,
                gap(20),
                ft.Row(
                    [
                        metric(ft.CupertinoIcons.DROP, t("weather.humidity"), self.humidity, "#2563EB", "#DBEAFE"),
                        metric(ft.CupertinoIcons.WIND, self.wind_label, self.wind, "#0D9488", "#CCFBF1"),
                        metric(ft.CupertinoIcons.CLOUD, t("weather.clouds"), self.clouds, "#475569", "#E2E8F0"),
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
        self.control = ft.Container(
            weather,
            border_radius=24,
            padding=ft.Padding.only(left=12, right=12, top=10, bottom=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER, colors=["#DDEBF9", "#EEF5FC"],
            ),
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
        self.feels.value = t("weather.feels_only", temp=f"{to_unit(risk['hi_c'], app.unit):.0f}")
        self.heat_label.value = t(f"risk.{risk['level']}")
        self.heat_label.color = RISK_COLORS[risk["level"]]
        self.heat_pill.content.controls[0].color = RISK_COLORS[risk["level"]]
        self.heat_pill.bgcolor = HEAT_TINTS[risk["level"]]
        self.heat_pill.visible = True
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
        padding=ft.Padding.symmetric(horizontal=16, vertical=18),
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
        self.danger_title.spans = []
        if status == "error":
            self.danger_title.value = t("home.danger_unavailable")
            self.danger_detail.value = t("home.danger_retry")
            self.shield.color, self.danger_badge.bgcolor = MUTED, PANEL
        elif status == "ready" and app.prediction:
            level = app.prediction["fwi"].danger
            self.danger_title.value = ""
            self.danger_title.spans = rich(
                t("home.danger_today", level=t(f"danger.{level}")), bold_color=DANGER_COLORS[level][0]
            )
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
        elif not real_fires(fires["groups"]):
            self.fires_title.value = t("home.fires_none")
        elif len(real_fires(fires["groups"])) == 1:
            self.fires_title.value = t("home.fires_one")
        else:
            self.fires_title.value = t("home.fires_many", count=len(real_fires(fires["groups"])))
        if real_fires(fires["groups"]):
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
    # hidden until there's something to show, so the card has no empty space at the bottom
    message = text("", size=14, color=FLAME, visible=False)
    result = text("", size=24, weight=ft.FontWeight.W_600, visible=False)
    level = text("", size=15, weight=ft.FontWeight.W_500, visible=False)

    def on_check(e):
        try:
            risk = heat_risk_checker(float(temp_field.value), float(rh_field.value))
        except ValueError:
            message.value, message.visible = t("calc.invalid"), True
            result.visible = level.visible = False
            app.page.update()
            return
        message.visible = False
        result.visible = level.visible = True
        result.value = f"{risk['hi_c']:.0f}°C  /  {risk['hi_f']:.0f}°F"
        level.value = t(f"risk.{risk['level']}")
        level.color = RISK_COLORS[risk["level"]]
        app.page.update()

    return card(ft.Column(
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
    ), bgcolor="#FFF8EB", padding=ft.Padding.symmetric(horizontal=16, vertical=20))


# ---------------------------------------------------------------------------
# Fire risk screen
# ---------------------------------------------------------------------------


def case_level(result: dict) -> str:
    """Risk step for one forest case, from the share of trees that burn on average."""
    percent = result["avg_percent"]
    if percent < 5:
        return "Low"
    if percent < 20:
        return "Moderate"
    if percent < 45:
        return "High"
    return "Extreme"


def scenario_card(app: App, result: dict, selected: bool, on_click) -> ft.Control:
    """All three cards share a border and fill so they read as one set; the selected card takes
    its risk colour, and the percentage is coloured once a case is more than low risk."""
    level = case_level(result)
    color, tint = DANGER_COLORS[level]
    return ft.Container(
        expand=True,
        on_click=on_click,
        ink=True,
        bgcolor=tint if selected else CASE_TINTS[result["key"]],
        border_radius=16,
        border=ft.Border.all(2, color) if selected else ft.Border.all(1, "#D1D5DB"),
        shadow=SHADOW if selected else None,
        padding=ft.Padding.symmetric(horizontal=4, vertical=18),
        content=ft.Column(
            [
                ft.Container(image(CASE_ICONS[result["key"]], 40, 40), height=44, alignment=ft.Alignment.CENTER),
                text(
                    f"{result['avg_percent']:.0f}%", size=24, weight=ft.FontWeight.W_600,
                    color=INK if level == "Low" else color,
                ),
                ft.Container(
                    text(app.t(f"case.{result['key']}"), size=13, color=INK if selected else MUTED, weight=ft.FontWeight.W_500),
                    height=36, alignment=ft.Alignment.TOP_CENTER,
                ),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def day_name(app: App, date: str, index: int, long: bool = False) -> str:
    """'Today' for the first forecast day, otherwise the weekday (short or long)."""
    if index == 0:
        return app.t("when.today")
    weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
    return WEEKDAYS[app.lang]["long" if long else "short"][weekday]


def forecast_day(app: App, index: int, day: dict) -> ft.Control:
    """One day in the 7-day strip: weekday, the FWI as a big number coloured by its EFFIS
    class, and the day's top temperature."""
    result = day["fwi"]
    color, tint = DANGER_COLORS[result.danger]
    top = day.get("tmax")
    return ft.Container(
        ft.Column(
            [
                text(day_name(app, day["date"], index), size=13.5, color=INK if index == 0 else MUTED,
                     weight=ft.FontWeight.W_600 if index == 0 else ft.FontWeight.W_500),
                ft.Container(image("weather/" + day_icon_name(day), 32), padding=ft.Padding.symmetric(vertical=2)),
                text(f"{result.fwi:.0f}", size=26 if result.fwi < 99.5 else 20, color=color, weight=ft.FontWeight.W_700),
                text(f"{to_unit(top, app.unit):.0f}°" if top is not None else "", size=14, color=MUTED),
            ],
            spacing=2,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        tooltip=f"{app.t(f'danger.{result.danger}')} · FWI {result.fwi:.1f}",
    )


def forest_legend(app: App, case: str) -> list[ft.Control]:
    """What each symbol in the forest grid means, for the case being shown."""
    t = app.t
    entry = lambda symbol, key: ft.Row(  # noqa: E731
        [ft.Container(forest_symbol(symbol, 18), width=18, height=18, alignment=ft.Alignment.CENTER),
         text(t(key), size=12, color=MUTED)],
        spacing=4, tight=True,
    )
    items = [entry(TREE, "legend.tree"), entry(FIRE, "legend.fire"), entry(ASH, "legend.burned")]
    if case == "glass":
        items.append(entry(GLASS, "legend.glass"))
    if case == "flammable":
        items.append(entry(FLAMMABLE, "legend.litter"))
    return items


class PredictionView:
    """Fire danger for the chosen place, worked out from live weather, plus Predict fire."""

    def __init__(self, app: App):
        self.app = app
        t = app.t
        self.intro = intro("")
        self.flame = ft.Icon(ft.CupertinoIcons.FLAME, color=FOREST, size=22)
        self.danger = text("", size=17, weight=ft.FontWeight.W_600)  # status while there's no level yet
        self.status_row = ft.Row([self.flame, self.danger], alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True)
        self.level_caption = text(t("risk.danger_label"), size=15, color=MUTED, weight=ft.FontWeight.W_500)
        self.level_text = text("", size=28 if app.lang == "en" else 22, color=CARD, weight=ft.FontWeight.W_700)
        self.level_pill = ft.Container(
            ft.Row([ft.Icon(ft.CupertinoIcons.FLAME_FILL, color=CARD, size=28), self.level_text], spacing=10, tight=True),
            border_radius=999,
            padding=ft.Padding.symmetric(horizontal=28, vertical=12),
        )
        self.level_block = ft.Column(
            [self.level_caption, self.level_pill], spacing=6, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False,
        )
        self.conditions = text("", size=13.5, color=MUTED)  # status line while there's no prediction
        self.explain = text("", size=16, color=INK, style=ft.TextStyle(height=1.35))
        # Four compact weather stats: icon, value, label
        self.stat_values = [text("", size=18, weight=ft.FontWeight.W_700) for _ in range(4)]
        self.stat_labels = [text("", size=13 if app.lang == "en" else 12, color=MUTED) for _ in range(4)]
        self.stat_icons = [ft.Icon(icon, color=INK, size=26) for icon in (
            ft.CupertinoIcons.THERMOMETER, ft.CupertinoIcons.DROP, ft.CupertinoIcons.WIND, ft.CupertinoIcons.SUN_MAX,
        )]
        self.stats = ft.Container(
            ft.Row(
                [
                    ft.Column([icon, value, label], spacing=1, tight=True, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                    for icon, value, label in zip(self.stat_icons, self.stat_values, self.stat_labels)
                ],
                spacing=2,
            ),
            bgcolor=ft.Colors.with_opacity(0.6, CARD),
            border_radius=14,
            padding=ft.Padding.symmetric(horizontal=2, vertical=12),
            visible=False,
        )
        self.fwi_line = text("", size=13, color=MUTED, weight=ft.FontWeight.W_500)
        # Next 7 days of fire danger, and the riskiest of them
        self.week_row = ft.Row(spacing=4, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self.week_peak = text("", size=16, color=INK)
        self.peak_chip = ft.Container(
            self.week_peak, border_radius=999, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
        )
        self.week_block = card(
            ft.Column(
                [
                    section_title(t("risk.week_title")),
                    text(t("risk.week_about"), size=15, color=MUTED),
                    ft.Container(height=10),
                    self.week_row,
                    ft.Container(height=12),
                    self.peak_chip,
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=16),
            visible=False,
        )
        self.sim_caption = text(t("risk.sim_caption"), size=12, color=FAINT)  # light footer note
        self.panel = ft.Container(
            bgcolor=MINT,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=12, vertical=20),
            content=ft.Column(
                [
                    self.status_row,
                    self.level_block,
                    self.fwi_line,
                    ft.Container(height=8),
                    self.conditions,
                    self.stats,
                    ft.Container(height=4),
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
        self.callout = ft.Text("", size=17, color=INK, font_family=FONT, font_family_fallback=[GEORGIAN], text_align=ft.TextAlign.CENTER)
        self.callout_detail = text("", size=13.5, color=MUTED)
        grid, self.cells = forest_grid(GRID_SIZE, GRID_SIZE, SAMPLE_CELL)
        self.legend = ft.Row(spacing=14, run_spacing=6, wrap=True, alignment=ft.MainAxisAlignment.CENTER)
        self.predict_button = primary_button(t("predict.button"), self.predict)
        self.outcome = ft.Text("", size=14, color=INK, font_family=FONT, font_family_fallback=[GEORGIAN], text_align=ft.TextAlign.CENTER)
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
                            ft.Container(self.legend, margin=ft.Margin.only(top=10)),
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
                ft.Container(self.week_block, margin=ft.Margin.only(top=6)),
                ft.Container(self.sim_caption, margin=ft.Margin.only(top=14, bottom=4)),
                self.cards,
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
        self.status_row.visible, self.level_block.visible = True, False
        self.fwi_line.value = ""
        self.stats.visible, self.conditions.visible = False, True
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

        w, p, today = app.prediction["weather"], app.prediction["result"], app.prediction["fwi"]
        week = app.prediction["week"]
        level = today.danger
        color, tint = DANGER_COLORS[level]
        self.fwi_line.value = t("risk.fwi_line", value=f"{today.fwi:.1f}")
        self.week_row.controls = [forecast_day(app, i, d) for i, d in enumerate(week)]
        peak_index = max(range(len(week)), key=lambda i: week[i]["fwi"].fwi)
        peak = week[peak_index]["fwi"]
        self.week_peak.value = ""
        peak_key = "risk.week_peak_safe" if peak.danger in SAFE_LEVELS else "risk.week_peak"
        self.week_peak.spans = rich(
            t(peak_key, level=t(f"danger.{peak.danger}"), day=day_name(app, week[peak_index]["date"], peak_index, long=True)),
            bold_color=DANGER_COLORS[peak.danger][0],
        )
        self.peak_chip.bgcolor = DANGER_COLORS[peak.danger][1]
        self.week_block.visible = True
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
            self.status_row.visible, self.level_block.visible = False, True
            self.level_text.value = t(f"danger.{level}")
            self.level_pill.bgcolor = color
        self.conditions.visible, self.stats.visible = False, True
        values = [
            f"{to_unit(w['temperature_2m'], app.unit):.0f}°{app.unit}",
            f"{w['relative_humidity_2m']}%",
            t("weather.wind_value", speed=f"{w['wind_speed_10m']:.0f}"),
            f"{p['sun'] * 100:.0f}%" if light == "sun" else "–",
        ]
        labels = [t("risk.stat_air"), t("weather.humidity"), t("weather.wind"), t(f"risk.stat_{light}")]
        for value_text, label_text, value, label in zip(self.stat_values, self.stat_labels, values, labels):
            value_text.value, label_text.value = value, label
        self.stat_icons[3].icon = {
            "sun": ft.CupertinoIcons.SUN_MAX, "overcast": ft.CupertinoIcons.CLOUD, "night": ft.CupertinoIcons.MOON,
        }[light]
        self.explain.value = t(f"risk.explain.{light}", toward=t(f"toward.{p['wind']}"))

        results = p["results"]
        self.cards.controls = [
            scenario_card(app, r, r["key"] == app.selected_case, lambda e, k=r["key"]: self.select(k)) for r in results
        ]
        result = next(r for r in results if r["key"] == app.selected_case)
        self.detail.visible = True
        self.case_title.value = t(f"case.{result['key']}")
        self.case_about.value = t(f"case.{result['key']}.about")
        self.legend.controls = forest_legend(app, result["key"])
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


def _data(name: str, default=None):
    path = APP_DIR / "data" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


GEORGIA = _data("georgia_outline.json")  # land border + real coastline, [lon, lat]
RIVERS = _data("georgia_rivers.json", {"rivers": []})["rivers"]
ELEVATION = _data("georgia_elevation.json")  # optional; without it the map has no relief shading
MAJOR_RIVERS = {"Mtkvari", "Rioni", "Enguri", "Alazani"}

# (English name, lat, lon, label side, label nudge up in px). Tbilisi's label sits left, clear of the
# fire-prone east; Batumi's sits a little higher so it doesn't run along the Turkish border.
MAP_CITIES = [
    ("Tbilisi", 41.7151, 44.8271, "left", 0),
    ("Kutaisi", 42.2679, 42.6946, "right", 0),
    ("Batumi", 41.6168, 41.6367, "right", 7),
]
CITY_LABEL_WIDTH = 72

# Map colours: flat, light land on a white card, soft blue sea
MAP_BG = "#EEF1F4"  # neighbouring countries: grey, so Georgia's white land stands out
MAP_SEA = "#C9DFF2"
MAP_LAND = "#FFFFFF"
MAP_BORDER = "#1F2937"
MAP_RIVER = "#4F8FCB"
RELIEF_INK = "#1F2937"

# Equirectangular projection fitted to Georgia's outline; longitude is squeezed by
# cos(latitude) so the country keeps its real proportions. The canvas fills the card.
MAP_WIDTH = WINDOW_WIDTH - 2 * PAGE_PADDING - 26
MAP_PAD_X = 14
MAP_PAD_Y = 26
_LONS = [lon for lon, _ in GEORGIA["outline"]]
_LATS = [lat for _, lat in GEORGIA["outline"]]
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = min(_LONS), max(_LONS), min(_LATS), max(_LATS)
LON_SQUEEZE = math.cos(math.radians((LAT_MIN + LAT_MAX) / 2))
MAP_SCALE = (MAP_WIDTH - 2 * MAP_PAD_X) / ((LON_MAX - LON_MIN) * LON_SQUEEZE)
MAP_HEIGHT = round((LAT_MAX - LAT_MIN) * MAP_SCALE + 2 * MAP_PAD_Y)

# Neighbouring coasts (lat, lon) so the Black Sea reads as a sea, not a gap in the map
RUSSIAN_COAST = [(43.58, 39.72), (43.43, 39.92)]  # Sochi, Adler -> Psou mouth
TURKISH_COAST = [(41.39, 41.42), (41.35, 41.31), (41.27, 41.14), (41.19, 40.99), (41.18, 40.88), (41.09, 40.73),
                 (41.02, 40.52), (40.95, 40.27)]  # Hopa ... Of


def map_xy(lat: float, lon: float) -> tuple[float, float]:
    x = MAP_PAD_X + (lon - LON_MIN) * LON_SQUEEZE * MAP_SCALE
    y = MAP_PAD_Y + (LAT_MAX - lat) * MAP_SCALE
    return x, y


def in_georgia(lon: float, lat: float) -> bool:
    poly, hit = GEORGIA["outline"], False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _relief() -> list[tuple[float, float, float, float, float]]:
    """Hill shading from the elevation grid, lit from the north-west, as (x, y, w, h, opacity)
    rectangles; neighbouring cells in a row with the same shade are merged into one."""
    if not ELEVATION:
        return []
    step = ELEVATION["step"]
    raw = {
        tuple(float(v) for v in key.split(",")): h for key, h in ELEVATION["heights"].items() if h is not None
    }
    # The grid holds single-point samples, which look speckled; a 3x3 weighted average
    # (1-2-1 in each direction) smooths them into broad ridges and valleys.
    heights = {}
    for lat, lon in raw:
        total = weight = 0.0
        for dy, wy in ((-1, 1), (0, 2), (1, 1)):
            for dx, wx in ((-1, 1), (0, 2), (1, 1)):
                h = raw.get((round(lat + dy * step, 3), round(lon + dx * step, 3)))
                if h is not None:
                    total += h * wy * wx
                    weight += wy * wx
        heights[(lat, lon)] = total / weight
    get = lambda lat, lon, default: heights.get((round(lat, 3), round(lon, 3)), default)  # noqa: E731
    dy_m = step * 111_200
    light = (-0.5, 0.5, math.sqrt(0.5))  # x east, y north, z up: azimuth 315°, altitude 45°
    cell_w, cell_h = step * LON_SQUEEZE * MAP_SCALE, step * MAP_SCALE
    rows: dict[float, list[tuple[float, float]]] = {}
    for (lat, lon), h in heights.items():
        if h is None or not in_georgia(lon, lat):
            continue
        dx_m = dy_m * math.cos(math.radians(lat))
        dzdx = (get(lat, lon + step, h) - get(lat, lon - step, h)) / (2 * dx_m) * 2  # 2x exaggeration
        dzdy = (get(lat + step, lon, h) - get(lat - step, lon, h)) / (2 * dy_m) * 2
        n = math.sqrt(dzdx * dzdx + dzdy * dzdy + 1)
        lit = (-dzdx * light[0] - dzdy * light[1] + light[2]) / n
        # shadowed slopes darken; higher ground gets a faint grey tint so ranges read at a glance
        alpha = min(max((0.71 - lit) * 0.55, 0), 0.24) + min(max(h, 0) / 4000, 1) * 0.12
        alpha = round(alpha / 0.012) * 0.012
        if alpha >= 0.012:
            rows.setdefault(lat, []).append((lon, alpha))
    rects = []
    for lat, cells in rows.items():
        cells.sort()
        run_start, run_end, run_alpha = None, None, None
        for lon, alpha in cells + [(None, None)]:
            if run_start is not None and (lon is None or alpha != run_alpha or round(lon - run_end, 3) > step):
                x0, y = map_xy(lat, run_start)
                x1, _ = map_xy(lat, run_end)
                # whole-pixel edges: neighbouring patches meet exactly, with no seams or overlaps
                left, right = round(x0 - cell_w / 2), round(x1 + cell_w / 2)
                top, bottom = round(y - cell_h / 2), round(y + cell_h / 2)
                rects.append((left, top, right - left, bottom - top, run_alpha))
                run_start = None
            if lon is None:
                break
            if run_start is None:
                run_start, run_alpha = lon, alpha
            run_end = lon
    return rects


RELIEF = _relief()


def _path(points: list[tuple[float, float]], close: bool = False) -> list:
    elements = [cv.Path.MoveTo(*points[0]), *[cv.Path.LineTo(x, y) for x, y in points[1:]]]
    return elements + [cv.Path.Close()] if close else elements


def georgia_map(app: App) -> ft.Stack:
    """Georgia with the Black Sea, relief shading, major rivers and three cities. Pins are added
    to the returned Stack."""
    land = _path([map_xy(lat, lon) for lon, lat in GEORGIA["outline"]], close=True)
    far_west = (MAP_PAD_X - 400) / (LON_SQUEEZE * MAP_SCALE) + LON_MIN  # well past the card's left edge
    sea_points = (
        [(44.6, far_west), *RUSSIAN_COAST]
        + [(lat, lon) for lon, lat in GEORGIA["coast"]]
        + [*TURKISH_COAST, (40.2, 40.27), (40.2, far_west)]
    )
    sea = _path([map_xy(lat, lon) for lat, lon in sea_points], close=True)
    stroke = lambda color, width: ft.Paint(  # noqa: E731
        color=color, style=ft.PaintingStyle.STROKE, stroke_width=width,
        stroke_join=ft.StrokeJoin.ROUND, stroke_cap=ft.StrokeCap.ROUND,
    )
    shapes = [
        cv.Path(sea, paint=ft.Paint(color=MAP_SEA, style=ft.PaintingStyle.FILL)),
        cv.Shadow(land, color=ft.Colors.with_opacity(0.35, "#000000"), elevation=3),
        cv.Path(land, paint=ft.Paint(color=MAP_LAND, style=ft.PaintingStyle.FILL)),
        *[
            cv.Rect(x, y, w, h, paint=ft.Paint(color=ft.Colors.with_opacity(a, RELIEF_INK), anti_alias=False))
            for x, y, w, h, a in RELIEF
        ],
    ]
    for river in RIVERS:
        width = 1.7 if river["en"] in MAJOR_RIVERS else 1.1
        for line in river["lines"]:
            shapes.append(cv.Path(_path([map_xy(lat, lon) for lon, lat in line]), paint=stroke(MAP_RIVER, width)))
    shapes.append(cv.Path(land, paint=stroke(MAP_BORDER, 1.5)))

    labels = []
    for name, lat, lon, side, nudge in MAP_CITIES:
        x, y = map_xy(lat, lon)
        shapes.append(cv.Circle(x, y, 4.5, paint=ft.Paint(color=CARD)))
        shapes.append(cv.Circle(x, y, 2.8, paint=ft.Paint(color=INK)))
        left = x + 7 if side == "right" else x - 7 - CITY_LABEL_WIDTH
        align = ft.TextAlign.LEFT if side == "right" else ft.TextAlign.RIGHT
        labels.append(
            ft.Text(
                app.city_name(name), size=12, color=INK, weight=ft.FontWeight.W_500,
                font_family=font_for(ft.FontWeight.W_500), font_family_fallback=georgian_for(ft.FontWeight.W_500),
                left=left, top=y - 9 - nudge, width=CITY_LABEL_WIDTH, text_align=align,
            )
        )
    country = ft.Text(
        app.t("map.country"), size=15, color=MAP_BORDER, weight=ft.FontWeight.W_600,
        font_family=font_for(ft.FontWeight.W_600), font_family_fallback=georgian_for(ft.FontWeight.W_600),
        style=ft.TextStyle(letter_spacing=1.2),
        right=16, top=14,
    )
    return ft.Stack(
        [cv.Canvas(shapes, width=MAP_WIDTH, height=MAP_HEIGHT), *labels, country],
        width=MAP_WIDTH,
        height=MAP_HEIGHT,
        clip_behavior=ft.ClipBehavior.NONE,
    )


def fire_pin(lat: float, lon: float, power_mw: float, tooltip: str) -> tuple[ft.Control, ft.Container]:
    """A red location pin with a soft glow and drop shadow, bigger for more powerful fires.
    Its tip sits on the fire. Returns (pin, ring); the ring pings out from the tip."""
    x, y = map_xy(lat, lon)
    size = round(26 + min(8, 3 * math.log2(1 + power_mw)))
    box_w, box_h = size + 28, size + 18
    tip_x, tip_y = box_w / 2, box_h - 9  # where the pin points, inside the box
    glow = size * 0.5
    ring = ft.Container(
        width=10, height=10, border_radius=5, border=ft.Border.all(2, FLAME), opacity=0.7,
        left=tip_x - 5, top=tip_y - 5,
    )
    pin = ft.Stack(
        [
            ft.Container(  # soft red glow around the spot
                width=glow * 2, height=glow * 2, border_radius=glow, left=tip_x - glow, top=tip_y - glow,
                bgcolor=ft.Colors.with_opacity(0.16, FLAME),
                shadow=ft.BoxShadow(blur_radius=14, spread_radius=2, color=ft.Colors.with_opacity(0.30, FLAME)),
            ),
            ring,
            ft.Container(  # contact shadow under the tip
                width=10, height=3, border_radius=5, left=tip_x - 5, top=tip_y - 1.5,
                bgcolor=ft.Colors.with_opacity(0.14, "#000000"),
                shadow=ft.BoxShadow(blur_radius=3, color=ft.Colors.with_opacity(0.18, "#000000")),
            ),
            ft.Container(
                ft.Icon(
                    ft.Icons.LOCATION_ON, size=size, color=FLAME,
                    shadows=[ft.BoxShadow(blur_radius=6, offset=ft.Offset(0, 3), color=ft.Colors.with_opacity(0.30, "#000000"))],
                ),
                left=tip_x - size / 2, top=tip_y - size * 0.92, tooltip=tooltip,
            ),
        ],
        left=x - tip_x, top=y - tip_y, width=box_w, height=box_h, clip_behavior=ft.ClipBehavior.NONE,
    )
    return pin, ring


def real_fires(groups: dict) -> list[dict]:
    return [g for g in groups.values() if not g.get("industrial")]


def industrial_spots(groups: dict) -> list[dict]:
    return [g for g in groups.values() if g.get("industrial")]


def heat_pin(lat: float, lon: float, tooltip: str) -> ft.Control:
    """A small grey square for likely industrial heat: shown, but not pinging like a fire,
    and square so it isn't mistaken for a round city dot."""
    x, y = map_xy(lat, lon)
    size = 11
    return ft.Container(
        width=size, height=size, border_radius=2.5, bgcolor="#4B5563", border=ft.Border.all(1.5, CARD), shadow=SHADOW,
        left=x - size / 2, top=y - size / 2, tooltip=tooltip,
    )


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
    tag = ft.Container(
        text(t("fires.active_label"), size=11.5, color="#B91C1C", weight=ft.FontWeight.W_600),
        bgcolor=FLAME_TINT,
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )
    return card(
        ft.Row(
            [
                icon_badge(ft.Icon(ft.CupertinoIcons.FLAME_FILL, color=FLAME, size=21), FLAME_TINT),
                ft.Column(
                    [
                        ft.Row([tag], spacing=0),
                        left(place_name(fire["address"]), size=15.5, weight=ft.FontWeight.W_600),
                        left(app.when(detected_at(fire)), size=13.5, color=MUTED),
                        left(details, size=12.5, color=FAINT),
                    ],
                    spacing=2,
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


def map_legend(app: App) -> ft.Control:
    """Small key under the map: fire pin, industrial heat square, city dot."""
    t = app.t
    entry = lambda mark, key: ft.Row([mark, text(t(key), size=12, color=MUTED)], spacing=5, tight=True)  # noqa: E731
    return ft.Row(
        [
            entry(ft.Icon(ft.Icons.LOCATION_ON, color=FLAME, size=16), "map.legend_fire"),
            entry(ft.Container(width=10, height=10, border_radius=2.5, bgcolor="#4B5563"), "map.legend_industrial"),
            entry(ft.Container(width=8, height=8, border_radius=4, bgcolor=INK), "map.legend_city"),
        ],
        spacing=14,
        run_spacing=4,
        wrap=True,
        alignment=ft.MainAxisAlignment.CENTER,
    )


def industrial_card(app: App, group: dict) -> ft.Control:
    t, fire, info = app.t, group["fire"], group["industrial"]
    lat, lon = fire["latitude"], fire["longitude"]
    site = info["site"]["ka" if app.lang == "ka" else "en"]
    left = lambda value, **kw: text(value, text_align=ft.TextAlign.LEFT, **kw)  # noqa: E731
    tag = ft.Container(
        text(t("fires.industrial_label"), size=11.5, color=MUTED, weight=ft.FontWeight.W_600),
        bgcolor=PANEL,
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )
    return card(
        ft.Row(
            [
                icon_badge(ft.Icon(ft.Icons.FACTORY_OUTLINED, color=MUTED, size=21), PANEL),
                ft.Column(
                    [
                        ft.Row([tag], spacing=0),
                        left(place_name(fire["address"]), size=15.5, weight=ft.FontWeight.W_600),
                        left(app.when(detected_at(fire)), size=13.5, color=MUTED),
                        left(t("fires.industrial_detail", site=site, days=info["days"]), size=12.5, color=FAINT),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.IconButton(
                    ft.CupertinoIcons.ARROW_UP_RIGHT_SQUARE, icon_color=MUTED, icon_size=20, tooltip=t("fires.open_map"),
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
        self.updated = text("", size=12.5, color=FAINT)
        self.note = text("", size=13.5, color=MUTED, visible=False)
        self.status_icon = ft.Icon(ft.CupertinoIcons.ANTENNA_RADIOWAVES_LEFT_RIGHT, color=MUTED, size=22)
        self.status_badge = icon_badge(self.status_icon, PANEL, 48)
        self.list = ft.Column(spacing=12)
        self.status_card = card(
            ft.Column(
                [self.status_badge, self.status, self.note],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=20),
        )
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
                self.updated,
                ft.Container(height=8),
                card(
                    ft.Column([self.map, map_legend(app)], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.only(bottom=12), bgcolor=MAP_BG,
                    alignment=ft.Alignment.CENTER, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
                self.status_card,
                self.list,
                ft.Container(text(t("fires.credits"), size=11.5, color=FAINT), margin=ft.Margin.only(top=12)),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def render(self):
        app, t, fires = self.app, self.app.t, self.app.fires
        fire_groups, heat_groups = real_fires(fires["groups"]), industrial_spots(fires["groups"])
        groups = fire_groups  # the counts and messages below are about real fires
        status = fires["status"]
        self.refresh.disabled = status in ("loading", "checking")

        pins, self.rings = [], []
        for g in heat_groups:
            fire = g["fire"]
            pins.append(
                heat_pin(
                    float(fire["latitude"]), float(fire["longitude"]),
                    f"{t('fires.industrial_label')}\n{place_name(fire['address'])}",
                )
            )
        for g in fire_groups:
            fire = g["fire"]
            pin, ring = fire_pin(
                float(fire["latitude"]), float(fire["longitude"]), float(fire["frp"]),
                f"{place_name(fire['address'])}\n{app.when(detected_at(fire))}",
            )
            pins.append(pin)
            self.rings.append(ring)
        self.map.controls = self.base_layers + pins
        newest = lambda gs: sorted(gs, key=lambda g: detected_at(g["fire"]), reverse=True)  # noqa: E731
        self.list.controls = [fire_card(app, g["fire"], g["count"]) for g in newest(fire_groups)] + [
            industrial_card(app, g) for g in newest(heat_groups)
        ]

        checked = fires.get("checked")
        self.updated.value = t("fires.updated", time=f"{checked:%H:%M}") if checked else ""
        self.updated.visible = bool(checked)
        self.note.visible = bool(heat_groups) and status not in ("loading", "nasa_error")
        if len(heat_groups) == 1:
            self.note.value = t("fires.industrial_one")
        elif heat_groups:
            self.note.value = t("fires.industrial_many", count=len(heat_groups))

        if groups:
            self.status_icon.color, self.status_badge.bgcolor, self.status_card.bgcolor = FLAME, CARD, "#FEF2F2"
        elif status == "done":
            self.status_icon.color, self.status_badge.bgcolor, self.status_card.bgcolor = FOREST, CARD, "#F0FAF4"
        else:
            self.status_icon.color, self.status_badge.bgcolor, self.status_card.bgcolor = MUTED, PANEL, CARD
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
        bgcolor=CANVAS,
        border=ft.Border.only(bottom=ft.BorderSide(1, LINE)),
        content=ft.Row(
            [
                ft.Row(
                    [
                        image("brand/heat_seeker_mark.png", 37, 24),
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
    """Line icon + label per screen. Active: green line on top, filled icon on a soft green pill, green label."""

    ITEMS = [
        (ft.CupertinoIcons.HOUSE, ft.CupertinoIcons.HOUSE_FILL, "nav.home"),
        (ft.CupertinoIcons.FLAME, ft.CupertinoIcons.FLAME_FILL, "nav.fire_spread"),
        (ft.CupertinoIcons.MAP, ft.CupertinoIcons.MAP_FILL, "nav.fires"),
    ]

    def __init__(self, app: App):
        self.icons, self.pills, self.labels, self.lines = [], [], [], []
        items = []
        for index, (outlined, _, key) in enumerate(self.ITEMS):
            icon = ft.Icon(outlined, size=22)
            pill = ft.Container(icon, width=56, height=30, border_radius=15, alignment=ft.Alignment.CENTER)
            line = ft.Container(width=40, height=3, border_radius=ft.BorderRadius.only(bottom_left=3, bottom_right=3))
            self.lines.append(line)
            label = text(app.t(key), size=11.5, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            self.icons.append(icon)
            self.pills.append(pill)
            self.labels.append(label)
            items.append(
                ft.Container(
                    expand=True,
                    ink=True,
                    on_click=lambda e, i=index: app.go_to(i),
                    alignment=ft.Alignment.TOP_CENTER,  # the active line sits on the bar's top edge
                    content=ft.Column(
                        [line, ft.Container(height=7), pill, label],
                        spacing=3,
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        self.control = ft.Container(
            height=72,
            bgcolor=CARD,
            border=ft.Border.only(top=ft.BorderSide(1, LINE)),
            content=ft.Row(items, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        )

    def select(self, index: int):
        for i, (outlined, filled, _) in enumerate(self.ITEMS):
            active = i == index
            self.icons[i].icon = filled if active else outlined
            self.icons[i].color = FOREST if active else FAINT
            self.pills[i].bgcolor = MINT if active else None
            self.lines[i].bgcolor = FOREST if active else None
            weight = ft.FontWeight.W_600 if active else ft.FontWeight.W_500
            self.labels[i].weight, self.labels[i].font_family = weight, font_for(weight)
            self.labels[i].color = FOREST if active else MUTED


class Views:
    """Every screen, built in the app's current language."""

    def __init__(self, app: App):
        self.app = app
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
        # On phones, keep the header below the status bar (clock, battery, notifications) and the
        # tab bar above the gesture/navigation bar. Their backgrounds still run behind those bars,
        # so there's no stray strip of another colour. On the PC the insets are zero.
        header = ft.Container(
            ft.SafeArea(top_bar(app), avoid_intrusions_bottom=False),
            bgcolor=CANVAS,
        )
        tabs = ft.Container(
            ft.SafeArea(self.nav.control, avoid_intrusions_top=False),
            bgcolor=CARD,
        )
        self.root = ft.Column([header, *self.screens, tabs], expand=True, spacing=0)

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


async def center_window(page: ft.Page):
    try:
        await page.window.center()
    except Exception:
        pass  # centring is only cosmetic; never let it surface as an error


async def main(page: ft.Page):
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
    page.update()  # apply the window size and fonts now, before waiting for the saved settings

    app = App(page)
    await app.load_settings()  # saved language and unit, before anything is drawn
    app.show_loader()
    app.build()
    if page.platform and page.platform.is_desktop() and not page.web:
        page.run_task(center_window, page)  # phones and browsers have no window to move
    page.run_task(app.refresh_weather)
    page.run_task(app.refresh_forever)
    page.run_task(app.load_fires)
    page.run_task(app.ping_forever)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
