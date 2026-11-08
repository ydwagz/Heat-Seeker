import asyncio
from pathlib import Path

import flet as ft

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

APP_ICON = Path(__file__).parent / "Images" / "icon.ico"

WINDOW_WIDTH = 390
WINDOW_HEIGHT = 844
PAGE_PADDING = 20

GRID_SIZE = 10
STEP_SECONDS = 0.2
CELL = 32  # px per cell in the fire simulation grid
SAMPLE_CELL = 22  # px per cell in the prediction grids

# Palette
SMOKE = "#EEF0EC"  # page
PAPER = "#F8F9F6"  # input fields
CHARCOAL = "#1F2622"  # text, primary buttons
LICHEN = "#67706A"  # secondary text
ASH = "#D3D8D2"  # lines

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
SCENARIO_ICONS = {"glass": GLASS, "flammable": FLAMMABLE}
SCALE_MIN_F = 40
SCALE_WIDTH = 300


def text(value="", size=15, color=CHARCOAL, weight=None, text_align=ft.TextAlign.CENTER, **kwargs) -> ft.Text:
    return ft.Text(
        value, size=size, color=color, weight=weight, font_family=FONT, text_align=text_align, **kwargs
    )


def heading(value: str) -> ft.Text:
    return text(value, size=20, weight=ft.FontWeight.W_600)


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
    return ft.Column([text(label, size=12.5, color=LICHEN), value], spacing=0, expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)


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
# Heat tab
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
        width=14,
        height=14,
        border_radius=7,
        bgcolor=PAPER,
        border=ft.Border.all(3, CHARCOAL),
        left=0,
        top=0,
        visible=False,
    )
    bar = ft.Stack(
        [ft.Container(bands, top=4), marker],
        width=SCALE_WIDTH,
        height=14,
    )
    ends = ft.Row(
        [text("Safe", size=12.5, color=LICHEN), text("Extreme danger", size=12.5, color=LICHEN)],
        width=SCALE_WIDTH,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    def set_value(hi_f: float):
        marker.left = scale_position(hi_f) * SCALE_WIDTH - 7
        marker.left = min(max(marker.left, 0), SCALE_WIDTH - 14)
        marker.visible = True

    return ft.Column([bar, ends], spacing=6, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER), set_value


def weather_header(page: ft.Page):
    """Centered live Tbilisi weather. Returns (control, async loader)."""
    temp = text("–°", size=112, weight=ft.FontWeight.W_200)
    feels = text("Loading live weather", size=17, color=LICHEN)
    scale, set_scale = heat_scale()
    humidity, wind, clouds, sky = text("–"), text("–"), text("–"), text("–")
    updated = text("", size=12.5, color=LICHEN)

    async def load(e=None):
        try:
            w = await asyncio.to_thread(fetch_current_weather)
        except Exception as err:
            feels.value = "Live weather is unavailable. Check your connection and refresh."
            feels.color = LICHEN
            updated.value = str(err)[:80]
            page.update()
            return
        risk = heat_risk_checker(w["temperature_2m"], w["relative_humidity_2m"])
        temp.value = f"{w['temperature_2m']:.0f}°"
        feels.value = f"Feels like {risk['hi_c']:.0f}°, {risk['level'].lower()}"
        feels.color = RISK_COLORS[risk["level"]]
        set_scale(risk["hi_f"])
        humidity.value = f"{w['relative_humidity_2m']}%"
        wind.value = f"{w['wind_speed_10m']:.0f} km/h {compass(w['wind_direction_10m'])}"
        clouds.value = f"{w['cloud_cover']}%"
        sky.value = "Day" if w["is_day"] else "Night"
        updated.value = f"Updated {w['time'][-5:]}"
        page.update()

    control = ft.Column(
        [
            ft.Row(
                [
                    text("Tbilisi", size=20, weight=ft.FontWeight.W_600),
                    ft.IconButton(
                        ft.Icons.REFRESH, icon_color=LICHEN, icon_size=18, tooltip="Refresh weather", on_click=load
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=0,
            ),
            ft.Container(temp, margin=ft.Margin.only(top=-18, bottom=-26)),
            feels,
            ft.Container(scale, margin=ft.Margin.only(top=14, bottom=20)),
            ft.Row([stat("Humidity", humidity), stat("Wind", wind)], spacing=24),
            ft.Row([stat("Clouds", clouds), stat("Sky", sky)], spacing=24),
            ft.Container(updated, margin=ft.Margin.only(top=6)),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=4,
    )
    return control, load


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
            heading("Check another temperature"),
            ft.Container(height=6),
            ft.Row([temp_field, rh_field], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([primary_button("Check", on_check), quiet_button("Use live weather", on_fetch)], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            message,
            result,
            ft.Row([level_dot, level], spacing=8, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Fire tab
# ---------------------------------------------------------------------------


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
            heading("Fire simulation"),
            text("Set where the wind blows, then start the fire.", color=LICHEN),
            ft.Container(height=6),
            ft.Row([wind, start_button], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(emoji_grid(cells, CELL), margin=ft.Margin.symmetric(vertical=8)),
            summary,
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def scenario_row(result: dict) -> ft.Control:
    cells = [[emoji_cell(emoji, SAMPLE_CELL) for emoji in row] for row in result["sample_grid"]]
    return ft.Column(
        [
            text(f"{result['label']} {SCENARIO_ICONS.get(result['key'], '')}", size=17, weight=ft.FontWeight.W_600),
            ft.Row(
                [
                    text(f"{result['avg_percent']:.0f}%", size=28, weight=ft.FontWeight.W_300),
                    text("of trees burn on average", color=LICHEN),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.BASELINE,
            ),
            text(
                f"A fire starts in {result['fire_chance']:.0f}% of forests. "
                f"Worst case: {result['max_burned']} trees.",
                size=13.5,
                color=LICHEN,
            ),
            ft.Container(emoji_grid(cells, SAMPLE_CELL), margin=ft.Margin.only(top=6)),
        ],
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def prediction_panel(page: ft.Page) -> ft.Control:
    message = text("", color=LICHEN, visible=False)
    conditions = text("", size=13.5, color=LICHEN)
    scenarios = ft.Column(spacing=16)

    async def on_predict(e):
        predict_button.disabled = True
        message.visible = True
        message.value = "Getting live weather…"
        scenarios.controls = []
        conditions.value = ""
        page.update()
        try:
            w = await asyncio.to_thread(fetch_current_weather)
        except Exception:
            message.value = "Live weather is unavailable. Check your connection and try again."
            predict_button.disabled = False
            page.update()
            return

        message.value = f"Simulating {PREDICTION_RUNS} forests for each case…"
        page.update()
        p = await asyncio.to_thread(
            predict_spread,
            w["temperature_2m"],
            w["relative_humidity_2m"],
            w["wind_direction_10m"],
            w["wind_speed_10m"],
            w["is_day"],
            w["cloud_cover"],
        )

        light = f"{p['sun'] * 100:.0f}% sun" if w["is_day"] else "night, so glass can't focus sunlight"
        message.value = ""
        message.visible = False
        conditions.value = (
            f"{w['temperature_2m']:.0f}°C, {w['relative_humidity_2m']}% humidity, "
            f"wind {w['wind_speed_10m']:.0f} km/h pushing fire {p['wind']}, {light}. "
            f"Fire danger is {danger_label(p['danger']).lower()}."
        )
        rows = []
        for r in p["results"]:
            if rows:
                rows.append(ft.Divider(height=1, color=ASH))
            rows.append(scenario_row(r))
        scenarios.controls = rows
        predict_button.disabled = False
        page.update()

    predict_button = primary_button("Predict with live weather", on_predict)

    return ft.Column(
        [
            heading("Live spreading prediction"),
            text(
                "How much of a forest would burn in Tbilisi's weather right now, "
                "left alone or with litter lying around.",
                color=LICHEN,
            ),
            ft.Container(height=6),
            ft.Row([predict_button], alignment=ft.MainAxisAlignment.CENTER),
            message,
            conditions,
            ft.Container(height=4),
            scenarios,
        ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def danger_label(danger: float) -> str:
    if danger < 0.15:
        return "Low"
    if danger < 0.4:
        return "Moderate"
    if danger < 0.7:
        return "High"
    return "Extreme"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def tab_page(*panels: ft.Control) -> ft.Control:
    """Pad panels, separate them with a hairline, and let the tab scroll on its own."""
    controls = []
    for panel in panels:
        if controls:
            controls.append(ft.Divider(height=48, color=ASH))
        controls.append(panel)
    return ft.Container(
        content=ft.Column(controls, scroll=ft.ScrollMode.AUTO, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.only(left=PAGE_PADDING, right=PAGE_PADDING, top=24, bottom=32),
    )


def main(page: ft.Page):
    page.title = "Heat Seeker"
    page.padding = 0
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
    )
    page.window.width = WINDOW_WIDTH
    page.window.height = WINDOW_HEIGHT
    page.window.resizable = False
    page.window.maximizable = False
    page.window.icon = str(APP_ICON)

    header, load_weather = weather_header(page)
    tab_text = ft.TextStyle(font_family=FONT, size=15, weight=ft.FontWeight.W_600)
    page.add(
        ft.Tabs(
            length=2,
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.TabBar(
                        tabs=[ft.Tab(label="Heat"), ft.Tab(label="Fire")],
                        scrollable=False,
                        label_color=CHARCOAL,
                        unselected_label_color=LICHEN,
                        label_text_style=tab_text,
                        unselected_label_text_style=tab_text,
                        indicator_color=CHARCOAL,
                        indicator_thickness=2,
                        indicator_size=ft.TabBarIndicatorSize.LABEL,
                        divider_color=ASH,
                        divider_height=1,
                        overlay_color=ft.Colors.TRANSPARENT,
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            tab_page(header, heat_panel(page)),
                            tab_page(fire_panel(page), prediction_panel(page)),
                        ],
                    ),
                ],
            ),
        )
    )
    page.run_task(page.window.center)
    page.run_task(load_weather)


if __name__ == "__main__":
    ft.run(main)
