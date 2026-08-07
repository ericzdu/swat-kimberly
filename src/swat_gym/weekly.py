"""Weekly open-loop irrigation — an action-space resolution sensitivity for Exp 1.

**Why this exists.** The monthly arm decides a monthly *volume* and renders it as <=40 mm
passes (:func:`swat_gym.monthly.year_events`), so both arms now apply physically sized
irrigation and differ only in **decision granularity**: 42 volumes against 182. This arm asks
whether finer control finds a better open-loop optimum once application depth is no longer the
confound it used to be.

**Why open-loop only.** Cost scales with cadence for *closed-loop* arms and not for open-loop
ones. SWAT+ has no checkpoint-restart, so a closed-loop step costs a full-horizon re-run: a
weekly episode is 182 engine runs against monthly's 42, cutting trainable episodes from ~7,100
to ~1,650 at a 300k budget (daily would give ~230, which is untrainable). An open-loop schedule
costs **one engine run whatever its cadence** — only the search dimensionality grows, 42 -> 182.
So refining the action space helps open-loop search and hurts learned policies, which is worth
knowing in its own right.

The weekly space no longer nests the monthly one — deliberately. ``WEEK_DEPTH_MAX`` is the
physical application cap, not the monthly volume ceiling, so neither arm can concentrate a
month of water into one event. The two spaces are therefore comparable in what they *apply*
and differ in what they can *decide*, which is the question this arm exists to answer.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from .constrainers import MAX_N_LOADING, repair
from .env import DEFAULT_PLAN, N_YEARS, SPINUP, decode_year, time_sim
from .fastrunner import FastRunner
from .monthly import MAX_EVENT_MM, default_monthly_irr
from .rewarders import Prices, nass, profit
from .schedule import CALENDAR, GROWING_MONTHS, YearAction, _doy, _md, build

#: First day of the growing season (1 April).
WEEK_START_DOY = _doy(4, 1)

#: Weeks spanning April–September (183 days).
N_WEEKS = 26

#: One depth per growing-season week per year.
WEEKLY_I_DIM = N_YEARS * N_WEEKS  # 182

#: One pass per week, capped at the physical application depth rather than at the monthly
#: volume ceiling. It was ``MONTH_DEPTH_MAX`` (200 mm) so the weekly space would nest the
#: monthly one — but that nesting is what let an optimiser concentrate a month of water into a
#: single 200 mm event, which `irr.ops` then infiltrates whole (``sumq_frac = 0``, verified:
#: raising it to 0.25 diverts exactly 25 % of applied water to runoff, so the fraction is
#: fixed and rate-independent). The monthly arm now renders its volume as <= ``MAX_EVENT_MM``
#: passes, so both arms apply physical depths and differ only in decision granularity.
WEEK_DEPTH_MAX = MAX_EVENT_MM


def week_doys() -> tuple[int, ...]:
    """Day-of-year on which each week's single event is placed (mid-week)."""
    return tuple(WEEK_START_DOY + 7 * w + 3 for w in range(N_WEEKS))


def decode_weekly_depths(flat: Sequence[float]) -> np.ndarray:
    """Unit box -> physical mm, shape ``(N_YEARS, N_WEEKS)``."""
    a = np.asarray(flat, dtype=float).reshape(N_YEARS, N_WEEKS)
    return np.clip(a, 0.0, 1.0) * WEEK_DEPTH_MAX


def encode_weekly_depths(mm: np.ndarray) -> np.ndarray:
    """Physical mm -> unit box."""
    return np.clip(np.asarray(mm, float) / WEEK_DEPTH_MAX, 0.0, 1.0).ravel()


def monthly_to_weekly(month_mm: np.ndarray) -> np.ndarray:
    """Spread each month's total evenly over the weeks whose midpoint falls in it.

    Preserves the annual applied depth exactly, so the weekly start point nests the measured
    total the same way the monthly default does.
    """
    doys = week_doys()
    out = np.zeros((N_YEARS, N_WEEKS), dtype=float)
    for mi, mon in enumerate(GROWING_MONTHS):
        idx = [w for w, d in enumerate(doys) if _md(d)[0] == mon]
        if not idx:
            continue
        for y in range(N_YEARS):
            out[y, idx] = month_mm[y, mi] / len(idx)
    return out


def default_weekly_i_free() -> np.ndarray:
    """CMA-ES start point: the measured-practice monthly default, spread weekly."""
    return encode_weekly_depths(monthly_to_weekly(default_monthly_irr()))


def _end_doy(crop: str) -> int:
    """Last day irrigation can land: final cut for alfalfa, harvest otherwise."""
    cal = CALENDAR[crop]
    return _doy(*cal["cuts"][-1]) if crop == "alfa" else _doy(*cal["harvest"])


def plan_from_weekly_i(week_mm: np.ndarray, *, max_n: float | None = MAX_N_LOADING
                       ) -> list[YearAction]:
    """Rotation plan with weekly irrigation; every other lever pinned at ``DEFAULT_PLAN``.

    Weeks falling at or after harvest are **relocated** onto the last day before it rather than
    dropped, matching the monthly renderer. Dropping them instead loses 4.7 % of the measured
    depth, which breaks the nesting gate and would make the weekly arm look water-thrifty for a
    purely mechanical reason.
    """
    week_mm = np.asarray(week_mm, dtype=float).reshape(N_YEARS, N_WEEKS)
    doys = week_doys()
    plan: list[YearAction] = []
    for y in range(N_YEARS):
        base = decode_year(DEFAULT_PLAN[y])
        end = _end_doy(base.crop)
        acc: dict[int, float] = {}
        for d, v in zip(doys, week_mm[y]):
            if v <= 0:
                continue
            day = int(d) if int(d) < end else end - 1
            acc[day] = acc.get(day, 0.0) + float(v)
        events = tuple(sorted(acc.items()))
        plan.append(replace(base, irr_depth=0.0, irr_interval=0,
                            irr_month_depths=None, irr_day_depths=events))
    return repair(plan, max_n=max_n)


def evaluate_weekly_i(flat: Sequence[float], runner: FastRunner, *,
                      prices: Prices | None = None, start_year: int = 2013,
                      no3_price: float = 0.0,
                      max_n: float | None = MAX_N_LOADING) -> dict:
    """Open-loop score for a weekly irrigation vector — one engine run, 182 parameters."""
    prices = prices or nass(2024)
    mm = decode_weekly_depths(flat)
    edits = build(plan_from_weekly_i(mm, max_n=max_n))
    edits["time.sim"] = time_sim(start_year, N_YEARS + SPINUP)
    runner.run(edits)
    out = profit(runner, prices, no3_price=no3_price)
    out["start_year"] = start_year
    return out
