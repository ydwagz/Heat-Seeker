"""Canadian Forest Fire Weather Index (FWI) System.

The FWI System is the fire danger rating used by Canada and, through EFFIS (the European
Forest Fire Information System), across Europe, the Mediterranean and the Caucasus,
including Georgia. It turns daily noon weather into six numbers:

    FFMC  Fine Fuel Moisture Code   dryness of litter and fine fuels (hours to dry)
    DMC   Duff Moisture Code        dryness of loosely packed organic layers (weeks)
    DC    Drought Code              dryness of deep, compact organic layers (months)
    ISI   Initial Spread Index      how fast a fire would spread (FFMC + wind)
    BUI   Buildup Index             how much fuel is available to burn (DMC + DC)
    FWI   Fire Weather Index        overall fire intensity (ISI + BUI)

FFMC, DMC and DC carry over from day to day, so the index is calculated as a chain
starting from the standard start-up values below. The equations are those of
Van Wagner, C.E. (1987), "Development and structure of the Canadian Forest Fire Weather
Index System", Forestry Technical Report 35, Canadian Forestry Service, Ottawa.
"""

from dataclasses import dataclass
from math import exp, log, sqrt

# Standard start-up values for the moisture codes (Van Wagner 1987)
START_FFMC = 85.0
START_DMC = 6.0
START_DC = 15.0

# Effective day length for the DMC and day-length adjustment for the DC, January..December,
# for the latitudes of the standard tables (they suit Georgia, 41-43.5 deg N)
DMC_DAY_LENGTH = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]
DC_DAY_LENGTH = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]

# EFFIS fire danger classes: (upper FWI bound, class name). Above the last bound: "Extreme".
EFFIS_CLASSES = [
    (5.2, "Very low"),
    (11.2, "Low"),
    (21.3, "Moderate"),
    (38.0, "High"),
    (50.0, "Very high"),
]


@dataclass(frozen=True)
class DayWeather:
    """Noon weather for one day, as the FWI System expects it."""

    month: int  # 1-12
    temp: float  # air temperature at noon, deg C
    rh: float  # relative humidity at noon, %
    wind: float  # wind speed at noon, km/h (10 m height)
    rain: float  # rain over the previous 24 hours, mm


@dataclass(frozen=True)
class FWIResult:
    ffmc: float
    dmc: float
    dc: float
    isi: float
    bui: float
    fwi: float

    @property
    def danger(self) -> str:
        return danger_class(self.fwi)


def ffmc(temp: float, rh: float, wind: float, rain: float, ffmc_yesterday: float) -> float:
    """Fine Fuel Moisture Code (Van Wagner 1987, equations 1-10)."""
    rh = min(max(rh, 0.0), 100.0)
    mo = 147.2 * (101.0 - ffmc_yesterday) / (59.5 + ffmc_yesterday)  # moisture content, %
    if rain > 0.5:
        rf = rain - 0.5  # rain that actually reaches the fuel
        wetting = 42.5 * rf * exp(-100.0 / (251.0 - mo)) * (1.0 - exp(-6.93 / rf))
        if mo > 150.0:
            mo += wetting + 0.0015 * (mo - 150.0) ** 2 * sqrt(rf)
        else:
            mo += wetting
        mo = min(mo, 250.0)

    drying_eq = 0.942 * rh**0.679 + 11.0 * exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (1.0 - exp(-0.115 * rh))
    if mo > drying_eq:  # fuel dries towards the equilibrium
        k0 = 0.424 * (1.0 - (rh / 100.0) ** 1.7) + 0.0694 * sqrt(wind) * (1.0 - (rh / 100.0) ** 8)
        kd = k0 * 0.581 * exp(0.0365 * temp)
        m = drying_eq + (mo - drying_eq) * 10.0 ** (-kd)
    else:
        wetting_eq = 0.618 * rh**0.753 + 10.0 * exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (1.0 - exp(-0.115 * rh))
        if mo < wetting_eq:  # fuel takes up moisture from humid air
            k1 = 0.424 * (1.0 - ((100.0 - rh) / 100.0) ** 1.7) + 0.0694 * sqrt(wind) * (1.0 - ((100.0 - rh) / 100.0) ** 8)
            kw = k1 * 0.581 * exp(0.0365 * temp)
            m = wetting_eq - (wetting_eq - mo) * 10.0 ** (-kw)
        else:
            m = mo
    return min(max(59.5 * (250.0 - m) / (147.2 + m), 0.0), 101.0)


def dmc(temp: float, rh: float, rain: float, month: int, dmc_yesterday: float) -> float:
    """Duff Moisture Code (Van Wagner 1987, equations 11-17)."""
    rh = min(max(rh, 0.0), 100.0)
    po = dmc_yesterday
    if rain > 1.5:
        re = 0.92 * rain - 1.27  # effective rain
        mo = 20.0 + exp(5.6348 - po / 43.43)
        if po <= 33.0:
            b = 100.0 / (0.5 + 0.3 * po)
        elif po <= 65.0:
            b = 14.0 - 1.3 * log(po)
        else:
            b = 6.2 * log(po) - 17.2
        mr = mo + 1000.0 * re / (48.77 + b * re)
        po = max(244.72 - 43.43 * log(mr - 20.0), 0.0)
    drying = 0.0
    if temp > -1.1:
        drying = 1.894 * (temp + 1.1) * (100.0 - rh) * DMC_DAY_LENGTH[month - 1] * 1e-6
    return max(po + 100.0 * drying, 0.0)


def dc(temp: float, rain: float, month: int, dc_yesterday: float) -> float:
    """Drought Code (Van Wagner 1987, equations 18-23)."""
    do = dc_yesterday
    if rain > 2.8:
        rd = 0.83 * rain - 1.27  # effective rain
        qo = 800.0 * exp(-do / 400.0)  # moisture equivalent
        qr = qo + 3.937 * rd
        do = max(400.0 * log(800.0 / qr), 0.0)
    evaporation = (0.36 * (max(temp, -2.8) + 2.8) + DC_DAY_LENGTH[month - 1]) / 2.0
    return max(do + max(evaporation, 0.0), 0.0)


def isi(ffmc_today: float, wind: float) -> float:
    """Initial Spread Index (Van Wagner 1987, equations 24-26)."""
    m = 147.2 * (101.0 - ffmc_today) / (59.5 + ffmc_today)
    wind_factor = exp(0.05039 * wind)
    fuel_factor = 91.9 * exp(-0.1386 * m) * (1.0 + m**5.31 / 4.93e7)
    return 0.208 * wind_factor * fuel_factor


def bui(dmc_today: float, dc_today: float) -> float:
    """Buildup Index (Van Wagner 1987, equations 27a-27b)."""
    if dmc_today == 0.0 and dc_today == 0.0:
        return 0.0
    if dmc_today <= 0.4 * dc_today:
        u = 0.8 * dmc_today * dc_today / (dmc_today + 0.4 * dc_today)
    else:
        u = dmc_today - (1.0 - 0.8 * dc_today / (dmc_today + 0.4 * dc_today)) * (0.92 + (0.0114 * dmc_today) ** 1.7)
    return max(u, 0.0)


def fwi(isi_today: float, bui_today: float) -> float:
    """Fire Weather Index (Van Wagner 1987, equations 28-30)."""
    if bui_today <= 80.0:
        duff_factor = 0.626 * bui_today**0.809 + 2.0
    else:
        duff_factor = 1000.0 / (25.0 + 108.64 * exp(-0.023 * bui_today))
    b = 0.1 * isi_today * duff_factor
    if b > 1.0:
        return exp(2.72 * (0.434 * log(b)) ** 0.647)
    return b


def next_day(day: DayWeather, yesterday: FWIResult | None = None) -> FWIResult:
    """All six FWI System values for one day, given yesterday's codes (or the start-up values)."""
    f0, p0, d0 = (yesterday.ffmc, yesterday.dmc, yesterday.dc) if yesterday else (START_FFMC, START_DMC, START_DC)
    f = ffmc(day.temp, day.rh, day.wind, day.rain, f0)
    p = dmc(day.temp, day.rh, day.rain, day.month, p0)
    d = dc(day.temp, day.rain, day.month, d0)
    i = isi(f, day.wind)
    u = bui(p, d)
    return FWIResult(ffmc=f, dmc=p, dc=d, isi=i, bui=u, fwi=fwi(i, u))


def run(days: list[DayWeather], start: FWIResult | None = None) -> list[FWIResult]:
    """The FWI System day by day over a series of days."""
    results: list[FWIResult] = []
    previous = start
    for day in days:
        previous = next_day(day, previous)
        results.append(previous)
    return results


def danger_class(value: float) -> str:
    """EFFIS fire danger class for an FWI value."""
    for upper, name in EFFIS_CLASSES:
        if value < upper:
            return name
    return "Extreme"
