"""CMA-ES-optimised parametric feedback irrigation controller.

Same optimizer and monthly action space as the open-loop bar; differs only in policy class
(state-feedback vs open-loop). Separates "adaptivity has no value here" from "PPO failed."

Controller (per growing-season month)::

    depth = clip(a + b * (sw_target - sw) + c * precip_deficit, 0, MONTH_DEPTH_MAX)

where ``sw`` and recent precip come from the previous month's ``hru_wb`` monthly row.
Three unit-box parameters ``(a, b, c)`` — tiny search, same engine-run budget accounting.

    uv run python -m swat_gym.experiments.exp1_controller --budget 5000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from dataclasses import replace

from ..env import N_YEARS, SPINUP, time_sim
from ..fastrunner import FastRunner
from ..monthly import (MONTH_DEPTH_MAX, N_GROWING, plan_from_monthly_i)
from ..rewarders import average, profit
from ..schedule import GROWING_MONTHS, build
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import ROOT, _row, mean, paired
from ._optimize import minimise

OUT = ROOT / "runs" / "exp1_controller.json"

#: Nominal soil-water target (mm) — order of field capacity for Portneuf silt loam.
SW_TARGET = 250.0
#: Nominal monthly precip (mm) against which a deficit is measured.
PRECIP_NORM = 20.0


def _decode_abc(vec) -> tuple[float, float, float]:
    """Unit box → (baseline mm, soil-water gain, precip-deficit gain)."""
    a = float(np.clip(vec[0], 0, 1)) * MONTH_DEPTH_MAX
    b = float(np.clip(vec[1], 0, 1)) * 2.0       # mm per mm of SW deficit
    c = float(np.clip(vec[2], 0, 1)) * 2.0       # mm per mm of precip deficit
    return a, b, c


def _month_state(runner: FastRunner, year_idx: int, month: int) -> tuple[float, float]:
    """Soil water and precip for ``month`` of decision year ``year_idx`` (0-based).

    Reads monthly ``hru_wb``. Missing rows (spin-up / before first month) return neutral
    defaults so the controller degrades to the baseline ``a``.
    """
    try:
        wb = runner.read("hru_wb_mon.txt")
    except Exception:
        return SW_TARGET, PRECIP_NORM
    if wb is None or len(wb) == 0:
        return SW_TARGET, PRECIP_NORM
    # Filter to the decision year: after spin-up, year_idx 0 is the first scored year.
    # Monthly tables carry mon / yr columns in SWAT+ output.
    cols = {c.lower(): c for c in wb.columns}
    mon_c = cols.get("mon") or cols.get("month")
    yr_c = cols.get("yr") or cols.get("year") or cols.get("yrc")
    sw_c = cols.get("sw_final") or cols.get("sw")
    precip_c = cols.get("precip") or cols.get("rain")
    if not (mon_c and sw_c):
        return SW_TARGET, float(wb[precip_c].iloc[-1]) if precip_c else PRECIP_NORM
    sub = wb
    if yr_c is not None:
        # Approximate: take rows whose month matches; use the year_idx-th occurrence.
        hits = sub[sub[mon_c] == month]
        if len(hits) == 0:
            return SW_TARGET, PRECIP_NORM
        row = hits.iloc[min(year_idx, len(hits) - 1)]
    else:
        hits = sub[sub[mon_c] == month]
        row = hits.iloc[-1] if len(hits) else sub.iloc[-1]
    sw = float(row[sw_c])
    precip = float(row[precip_c]) if precip_c and precip_c in row.index else PRECIP_NORM
    return sw, precip


def rollout_controller(abc, runner: FastRunner, *, start_year: int, prices,
                       no3_price: float = 0.0, max_n: float | None = None) -> dict:
    """Closed-loop monthly irrigation over the rotation; returns profit dict."""
    a, b, c = _decode_abc(abc)
    month_mm = np.zeros((N_YEARS, N_GROWING), dtype=float)

    # Full-horizon replay each month (correctness first; truncation is a later speed opt).
    # Month 0 of year 0 has no prior state — apply baseline ``a``.
    for y in range(N_YEARS):
        for mi, mon in enumerate(GROWING_MONTHS):
            if y == 0 and mi == 0:
                sw, precip = SW_TARGET, PRECIP_NORM
            else:
                # State from the just-completed prefix: re-run with depths decided so far.
                plan = plan_from_monthly_i(month_mm, max_n=max_n)
                edits = build(plan)
                edits["time.sim"] = time_sim(start_year, N_YEARS + SPINUP)
                runner.run(edits)
                # Previous month within year, or last month of previous year.
                if mi == 0:
                    prev_mon = GROWING_MONTHS[-1]
                    prev_y = y - 1
                else:
                    prev_mon = GROWING_MONTHS[mi - 1]
                    prev_y = y
                sw, precip = _month_state(runner, prev_y, prev_mon)

            deficit_sw = max(0.0, SW_TARGET - sw)
            deficit_p = max(0.0, PRECIP_NORM - precip)
            depth = float(np.clip(a + b * deficit_sw + c * deficit_p, 0.0, MONTH_DEPTH_MAX))
            month_mm[y, mi] = depth

    plan = plan_from_monthly_i(month_mm, max_n=max_n)
    edits = build(plan)
    edits["time.sim"] = time_sim(start_year, N_YEARS + SPINUP)
    runner.run(edits)
    out = profit(runner, prices, no3_price=no3_price)
    out["month_mm"] = month_mm.round(2).tolist()
    out["start_year"] = start_year
    return out


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=5_000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="$/kg N on leached nitrate; must match the arm this row is "
                         "compared against or the comparison is meaningless")
    ap.add_argument("--water-price", type=float, default=None,
                    help="$/mm/ha override for the placeholder DEFAULT_WATER")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    if args.water_price is not None:
        prices = replace(prices, water=args.water_price,
                         label=f"{prices.label}@w={args.water_price:g}")
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    evals = max(1, args.budget // len(train))
    x0 = np.array([0.2, 0.3, 0.3])  # mild baseline + some feedback
    t0 = time.time()

    with FastRunner() as runner:
        def obj(free):
            total = 0.0
            for sy in train:
                try:
                    total += rollout_controller(free, runner, start_year=sy,
                                                prices=prices,
                                                no3_price=args.no3_price)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train)

        best, n_evals, history = minimise(obj, x0, evals=evals, seed=args.seed)

        def score(windows):
            return [_row(rollout_controller(best, runner, start_year=sy, prices=prices,
                                            no3_price=args.no3_price), sy)
                    for sy in windows]

        train_rows, test_rows = score(train), score(test)

    summary = {
        "abc": list(map(float, best)), "decoded": dict(zip("abc", _decode_abc(best))),
        "no3_price": args.no3_price, "prices": prices.label,
        "n_evals": n_evals, "history": history,
        "train": mean(train_rows), "test": mean(test_rows),
        "per_window_test": test_rows,
        "seconds": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"controller train {summary['train']:.0f}  test {summary['test']:.0f} $/ha")
    print(f"params a,b,c = {summary['decoded']}")
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
