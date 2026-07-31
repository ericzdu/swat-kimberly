"""Monthly growing-season irrigation schedules.

Growing season is April–September (months 4–9): six decisions per year × seven years = 42
open-loop parameters for the irrigation arm. The annual ``(start, interval, depth)`` schedule
**nests** inside this space: :func:`annual_to_monthly` converts a fixed-interval year into six
monthly totals so ``DEFAULT_PLAN`` still reproduces the measured 3,938.8 mm baseline.

Open-loop only in Stage 1 — the gym lives in :mod:`swat_gym.env` once the ceiling gate passes.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from .constrainers import MAX_N_LOADING, repair
from .env import (DEFAULT_PLAN, N_YEARS, SPINUP, _lerp, decode_year, time_sim)
from .fastrunner import FastRunner
from .rewarders import Prices, nass, profit
from .schedule import (CALENDAR, GROWING_MONTHS, YearAction, _doy, _md, build)

#: Growing season length (April–September).
N_GROWING = len(GROWING_MONTHS)

#: Open-loop irrigation dimensionality: one depth per growing month per year.
MONTHLY_I_DIM = N_YEARS * N_GROWING  # 42

#: Max mm applied in one month (one mid-month event). Generous enough that the annual default
#: (~33 mm × ~3–5 events/month) nests inside without clipping.
MONTH_DEPTH_MAX = 200.0


def annual_to_monthly(irr_start_doy: int, irr_interval: int, irr_depth: float,
                      crop: str) -> tuple[float, ...]:
    """Collapse a fixed-interval year into six monthly totals (mm).

    Events after harvest / final cut are dropped, matching :func:`schedule._year_ops`.
    """
    depths = [0.0] * N_GROWING
    if irr_depth <= 0 or irr_interval <= 0:
        return tuple(depths)
    cal = CALENDAR[crop]
    end_doy = _doy(*cal["cuts"][-1]) if crop == "alfa" else _doy(*cal["harvest"])
    doy = int(irr_start_doy)
    while doy < end_doy:
        mon = _md(doy)[0]
        if mon in GROWING_MONTHS:
            depths[GROWING_MONTHS.index(mon)] += float(irr_depth)
        doy += int(irr_interval)
    return tuple(depths)


def default_monthly_irr() -> np.ndarray:
    """``DEFAULT_PLAN`` irrigation expressed as monthly depths, shape ``(N_YEARS, N_GROWING)``.

    Nesting: scoring this vector through :func:`evaluate_monthly_i` must match the annual
    default's applied depth to within 1 %.
    """
    out = np.zeros((N_YEARS, N_GROWING), dtype=float)
    for y in range(N_YEARS):
        a = decode_year(DEFAULT_PLAN[y])
        out[y] = annual_to_monthly(a.irr_start_doy, a.irr_interval, a.irr_depth, a.crop)
    return out


def encode_monthly_depths(mm: np.ndarray) -> np.ndarray:
    """Physical mm ``(N_YEARS, N_GROWING)`` → unit box ``[0, 1]``."""
    return np.clip(np.asarray(mm, dtype=float) / MONTH_DEPTH_MAX, 0.0, 1.0).ravel()


def decode_monthly_depths(flat: Sequence[float]) -> np.ndarray:
    """Unit box → physical mm ``(N_YEARS, N_GROWING)``."""
    a = np.asarray(flat, dtype=float).reshape(N_YEARS, N_GROWING)
    return np.clip(a, 0.0, 1.0) * MONTH_DEPTH_MAX


def plan_from_monthly_i(month_mm: np.ndarray, *, constrain: bool = True,
                        max_n: float | None = MAX_N_LOADING) -> list[YearAction]:
    """Build a full rotation plan with monthly irrigation; other levers at ``DEFAULT_PLAN``."""
    month_mm = np.asarray(month_mm, dtype=float).reshape(N_YEARS, N_GROWING)
    plan: list[YearAction] = []
    for y in range(N_YEARS):
        base = decode_year(DEFAULT_PLAN[y])
        plan.append(replace(
            base,
            irr_depth=0.0,  # unused when month depths are set
            irr_interval=0,
            irr_month_depths=tuple(float(v) for v in month_mm[y]),
        ))
    return repair(plan, max_n=max_n) if constrain else plan


def evaluate_monthly_i(flat: Sequence[float], runner: FastRunner, *,
                       prices: Prices | None = None, start_year: int = 2012,
                       constrain: bool = True, no3_price: float = 0.0,
                       max_n: float | None = MAX_N_LOADING) -> dict:
    """Open-loop score for a monthly irrigation vector (42 unit-box parameters)."""
    prices = prices or nass(2024)
    mm = decode_monthly_depths(flat)
    plan = plan_from_monthly_i(mm, constrain=constrain, max_n=max_n)
    edits = build(plan)
    edits["time.sim"] = time_sim(start_year, len(plan) + SPINUP)
    runner.run(edits)
    out = profit(runner, prices, no3_price=no3_price)
    out["plan_month_mm"] = mm.round(2).tolist()
    out["start_year"] = start_year
    return out


def default_monthly_i_free() -> np.ndarray:
    """CMA-ES start point: measured-practice irrigation in the monthly unit box."""
    return encode_monthly_depths(default_monthly_irr())
