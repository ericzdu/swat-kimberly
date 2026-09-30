"""Management plans: the measured default, the two levers, and open-loop scoring.

A lever maps a unit-box vector ``x`` to a full 7-year plan; everything it doesn't control
stays at measured practice.
  I: 42 monthly irrigation depths (Apr-Sep x 7 years).
  N: per annual-crop year, 6 monthly mineral-N rates + 1 April manure rate (4 x 7 = 28).
     Irrigation stays at measured practice; alfalfa years get no N.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from .rewarders import Prices, nass, profit
from .schedule import CALENDAR, GROWING_MONTHS, YearAction, _doy, _md, build

N_YEARS = 7                 # scored years
SPINUP = 1                  # 2012-style spin-up year, skipped by print.prt nyskip
WEATHER_YEARS = (1995, 2025)
N_GROWING = len(GROWING_MONTHS)

MEASURED_ROTATION = ("corn", "barl", "alfa", "alfa", "alfa", "corn", "barl")
#: Measured GRACEnet manure per year: (Mg/ha, source). Applied 10 April (DOY 100).
MEASURED_MANURE = ((43.8, "gn2013"), (48.0, "gn2014"), (0.0, "gn2013"), (0.0, "gn2013"),
                   (0.0, "gn2013"), (88.3, "gn2018"), (54.3, "gn2019"))
MANURE_DOY = 100
#: Measured-practice irrigation: every 7 days from DOY 130 at 32.824 mm -> 3,938.8 mm total.
DEFAULT_IRR = {"irr_start_doy": 130, "irr_interval": 7, "irr_depth": 32.824}
MEASURED_IRRIGATION_MM = 3938.8

MONTH_DEPTH_MAX = 200.0     # mm per month (lever I range)
MAX_EVENT_MM = 40.0         # mm per pass; big single events fake leaching in SWAT+
MONTH_N_MAX = 150.0         # kg N/ha per month (lever N range)
MANURE_MAX = 90.0           # Mg/ha per year (lever N range)

ANNUAL_YEARS = tuple(y for y, c in enumerate(MEASURED_ROTATION) if c != "alfa")
DIMS = {"I": N_YEARS * N_GROWING, "N": len(ANNUAL_YEARS) * (N_GROWING + 1)}


def default_plan() -> list[YearAction]:
    return [YearAction(crop=c, manure_mg=mg, manure_doy=MANURE_DOY, manure_src=src,
                       **DEFAULT_IRR)
            for c, (mg, src) in zip(MEASURED_ROTATION, MEASURED_MANURE)]


def time_sim(start_year: int, n_years: int = N_YEARS + SPINUP) -> str:
    return ("time.sim: written by swat_gym.plan\n"
            "day_start  yrc_start   day_end   yrc_end      step  \n"
            f"{0:>10}{start_year:>11}{0:>10}{start_year + n_years - 1:>10}{0:>10}  \n")


# -- irrigation rendering -------------------------------------------------------------

def _season_end(crop: str) -> int:
    cal = CALENDAR[crop]
    return _doy(*cal["cuts"][-1]) if crop == "alfa" else _doy(*cal["harvest"])


def _days_in_month(mon: int) -> int:
    return _doy(mon + 1, 1) - _doy(mon, 1) if mon < 12 else 31


def _spread(volume: float, first: int, last: int, max_event: float):
    """Equal passes on distinct days in [first, last]; returns (passes, leftover volume)."""
    usable = last - first + 1
    if volume <= 0 or usable <= 0:
        return [], max(0.0, volume)
    n = min(max(1, int(np.ceil(volume / max_event))), usable)
    per = volume / n
    overflow = 0.0
    if per > max_event:
        overflow = volume - usable * max_event
        per, n = max_event, usable
    return [(first + int(k * usable / n), per) for k in range(n)], overflow


def year_events(month_mm_year, crop: str, max_event: float = MAX_EVENT_MM):
    """Six monthly volumes -> ((doy, mm), ...) passes <= max_event, before harvest.

    Deterministic and state-independent. Overflow is carried back to earlier days.
    """
    end = _season_end(crop)
    season_start = _doy(GROWING_MONTHS[0], 1)
    acc: dict[int, float] = {}
    carry = 0.0
    for mi, mon in enumerate(GROWING_MONTHS):
        first = _doy(mon, 1)
        last = min(first + _days_in_month(mon) - 1, end - 1)
        events, over = _spread(float(month_mm_year[mi]), first, last, max_event)
        for doy, mm in events:
            acc[doy] = acc.get(doy, 0.0) + mm
        carry += over
    doy = end - 1
    while carry > 1e-9 and doy >= season_start:
        room = max_event - acc.get(doy, 0.0)
        if room > 1e-9:
            take = min(room, carry)
            acc[doy] = acc.get(doy, 0.0) + take
            carry -= take
        doy -= 1
    return tuple(sorted((d, v) for d, v in acc.items() if v > 0))


def default_monthly_irr() -> np.ndarray:
    """Measured-practice irrigation as monthly mm, shape (N_YEARS, N_GROWING)."""
    out = np.zeros((N_YEARS, N_GROWING))
    for y, a in enumerate(default_plan()):
        end = _season_end(a.crop)
        doy = a.irr_start_doy
        while doy < end:
            mon = _md(doy)[0]
            if mon in GROWING_MONTHS:
                out[y, GROWING_MONTHS.index(mon)] += a.irr_depth
            doy += a.irr_interval
    return out


# -- levers ---------------------------------------------------------------------------

def default_x(lever: str) -> np.ndarray:
    """Measured practice in the lever's unit box (the CMA-ES start point)."""
    if lever == "I":
        return np.clip(default_monthly_irr() / MONTH_DEPTH_MAX, 0.0, 1.0).ravel()
    x = np.zeros((len(ANNUAL_YEARS), N_GROWING + 1))
    for i, y in enumerate(ANNUAL_YEARS):
        x[i, -1] = MEASURED_MANURE[y][0] / MANURE_MAX
    return x.ravel()


def plan_from(lever: str, x: Sequence[float]) -> list[YearAction]:
    """Unit-box vector -> full plan."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    base = default_plan()
    if lever == "I":
        month_mm = x.reshape(N_YEARS, N_GROWING) * MONTH_DEPTH_MAX
    else:
        month_mm = default_monthly_irr()
    plan = [replace(a, irr_day_depths=year_events(month_mm[y], a.crop))
            for y, a in enumerate(base)]
    if lever == "N":
        xn = x.reshape(len(ANNUAL_YEARS), N_GROWING + 1)
        for i, y in enumerate(ANNUAL_YEARS):
            splits = tuple((_doy(mon, 15), float(xn[i, m] * MONTH_N_MAX))
                           for m, mon in enumerate(GROWING_MONTHS))
            plan[y] = replace(plan[y], fert_splits=splits,
                              manure_mg=float(xn[i, -1] * MANURE_MAX))
    return plan


def evaluate(lever: str, x: Sequence[float], runner, *, prices: Prices | None = None,
             start_year: int = 2013, no3_price: float = 0.0) -> dict:
    """Simulate the lever's plan on one weather window and return profit terms."""
    edits = build(plan_from(lever, x))
    edits["time.sim"] = time_sim(start_year)
    runner.run(edits)
    out = profit(runner, prices or nass(2024), no3_price=no3_price)
    out["start_year"] = start_year
    return out
