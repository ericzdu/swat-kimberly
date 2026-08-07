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

#: Max mm applied in one month. Generous enough that the annual default (~33 mm × ~3–5
#: events/month) nests inside without clipping.
MONTH_DEPTH_MAX = 200.0

#: Largest single application, mm. From ``irr.ops``' own ``sprinkler_high`` preset — the
#: engine's notion of a big sprinkler pass. ``sprinkler_med`` is 9.1 mm and ``drip`` 25 mm.
#:
#: **Why a month's water is delivered in passes rather than one event.** Every row of
#: ``irr.ops`` sets ``sumq_frac = 0``, so applied irrigation is routed entirely into the soil
#: with none shed as surface runoff. That is sound at realistic application depths and false at
#: large ones: holding annual depth fixed at 562.7 mm and varying only event size, runoff stays
#: flat at 2.26–2.46 mm/yr across a 17-fold range (10.8 → 187.6 mm), while percolation climbs
#: 0.00 → 54.25 and leaching 0.00 → 143.90 kg N/ha. A single 188 mm application infiltrates
#: whole because the model has no infiltration-rate limit on irrigation.
#:
#: Rendering one month as one event therefore *manufactured* the leaching that Exp 1's arms
#: then differed in — the column ranked action-space coarseness, not management. Splitting the
#: same volume into ≤40 mm passes leaves applied water identical and takes leaching to exactly
#: zero (`scripts/event_size_check.py`).
#:
#: The site needs ~563 mm/yr, which is ~24 passes at this cap — against measured practice's
#: 22.6/yr. Six monthly events was never close to how the field is actually watered.
MAX_EVENT_MM = 40.0


def _days_in_month(mon: int) -> int:
    return _doy(mon + 1, 1) - _doy(mon, 1) if mon < 12 else 31


def _spread(volume: float, first: int, last: int,
            max_event: float) -> tuple[list[tuple[int, float]], float]:
    """Place ``volume`` as equal passes on distinct days in ``[first, last]``.

    Returns the passes and whatever volume would not fit under ``max_event``.
    """
    usable = last - first + 1
    if volume <= 0 or usable <= 0:
        return [], max(0.0, volume)
    n = min(max(1, int(np.ceil(volume / max_event))), usable)
    per = volume / n
    overflow = 0.0
    if per > max_event:                      # month cannot absorb it at a physical rate
        overflow = volume - usable * max_event
        per, n = max_event, usable
    return [(first + int(k * usable / n), per) for k in range(n)], overflow


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


def year_events(month_mm_year, crop: str,
                max_event: float = MAX_EVENT_MM) -> tuple[tuple[int, float], ...]:
    """One year's six monthly volumes as day-level passes of at most ``max_event``.

    Shared by the open-loop and policy paths — objective parity depends on both calling this.

    **This transform must stay deterministic and policy-agnostic.** Placing passes by soil
    water — irrigating when the profile is dry — would make the *renderer* a closed-loop
    controller, and every arm, including the fixed open-loop schedules, would silently inherit
    adaptation from it. The comparison between searched schedules and learned policies would
    then be meaningless, and invisibly so, because the behaviour lives in the plan builder
    rather than in the reward. Responsive timing belongs in an action space where an arm is
    credited for it (see :mod:`swat_gym.experiments.exp1_controller`).

    Water that falls after harvest, or that a month cannot absorb at a physical rate, is
    carried back onto earlier days with spare capacity rather than dropped — dropping it loses
    4.7 % of the measured depth and breaks the nesting gate — and never stacked onto one day,
    which would recreate the very over-application this rendering exists to prevent.
    """
    cal = CALENDAR[crop]
    end = _doy(*cal["cuts"][-1]) if crop == "alfa" else _doy(*cal["harvest"])
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

    # Fill backwards from harvest into whatever headroom remains.
    doy = end - 1
    while carry > 1e-9 and doy >= season_start:
        room = max_event - acc.get(doy, 0.0)
        if room > 1e-9:
            take = min(room, carry)
            acc[doy] = acc.get(doy, 0.0) + take
            carry -= take
        doy -= 1
    return tuple(sorted((d, v) for d, v in acc.items() if v > 0))


def plan_from_monthly_i(month_mm: np.ndarray, *, constrain: bool = True,
                        max_n: float | None = MAX_N_LOADING,
                        max_event: float = MAX_EVENT_MM) -> list[YearAction]:
    """Build a full rotation plan with monthly irrigation; other levers at ``DEFAULT_PLAN``.

    Monthly volumes are rendered as ≤``max_event`` passes (see :data:`MAX_EVENT_MM`), so the
    action stays a monthly *volume* while the simulation sees physically sized applications.
    """
    month_mm = np.asarray(month_mm, dtype=float).reshape(N_YEARS, N_GROWING)
    plan: list[YearAction] = []
    for y in range(N_YEARS):
        base = decode_year(DEFAULT_PLAN[y])
        plan.append(replace(
            base,
            irr_depth=0.0,  # unused when day depths are set
            irr_interval=0,
            irr_month_depths=None,
            irr_day_depths=year_events(month_mm[y], base.crop, max_event),
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
