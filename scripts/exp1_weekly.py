#!/usr/bin/env python3
"""Weekly open-loop irrigation — action-space resolution sensitivity for Exp 1.

Same protocol as the monthly open-loop arm (CMA-ES on the training windows, scored on the
held-out ones, nitrogen pinned, no loading cap), differing only in temporal resolution:
182 parameters instead of 42.

Budget note: an open-loop evaluation costs one engine run *whatever the cadence*, so weekly is
no more expensive per evaluation than monthly — only the search space is 4.3x larger. A weekly
result at or below the monthly optimum at equal evaluations is therefore under-search rather
than evidence against finer control, and the weekly space nests the monthly one by construction
(`WEEK_DEPTH_MAX == MONTH_DEPTH_MAX`).

    uv run python scripts/exp1_weekly.py --budget 100000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from swat_gym.experiments._focused import _row, mean, paired
from swat_gym.experiments._optimize import minimise
from swat_gym.fastrunner import FastRunner
from swat_gym.rewarders import average
from swat_gym.weekly import WEEKLY_I_DIM, default_weekly_i_free, evaluate_weekly_i
from swat_gym.windows import TEST_YEARS, TRAIN_YEARS, assert_no_leakage

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "exp1_weekly.json"
MEASURED_MM = 3938.8


def score(x, windows, prices, no3_price, max_n):
    with FastRunner() as r:
        return [_row(evaluate_weekly_i(x, r, prices=prices, start_year=sy,
                                       no3_price=no3_price, max_n=max_n), sy)
                for sy in windows]


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=100_000,
                    help="engine runs; evals = budget // len(train_windows)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    max_n = None                      # nitrogen pinned; the cap is not a measurement
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    evals = max(1, args.budget // len(train))
    t0 = time.time()
    print(f"weekly open-loop: {WEEKLY_I_DIM} params, {evals} CMA evals x {len(train)} windows",
          flush=True)

    x0 = default_weekly_i_free()
    default_test = score(x0, test, prices, args.no3_price, max_n)

    # Nesting gate, the same one the monthly arm must pass.
    with FastRunner() as r:
        d0 = evaluate_weekly_i(x0, r, prices=prices, start_year=2013, max_n=max_n)
    nest_err = abs(d0["irrigation_mm"] - MEASURED_MM) / MEASURED_MM
    print(f"nesting: weekly default {d0['irrigation_mm']:.1f} mm vs measured {MEASURED_MM} "
          f"({100 * nest_err:.2f}% err)", flush=True)
    if nest_err > 0.01:
        raise SystemExit("weekly default does not nest measured depth — refusing to score arms")

    with FastRunner() as r:
        def obj(free):
            total = 0.0
            for sy in train:
                try:
                    total += evaluate_weekly_i(free, r, prices=prices, start_year=sy,
                                               max_n=max_n)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train)

        x, n_evals, hist = minimise(obj, x0, evals=evals, seed=args.seed)

    fixed_train = score(x, train, prices, args.no3_price, max_n)
    fixed_test = score(x, test, prices, args.no3_price, max_n)

    summary = {
        "arm": "I_weekly", "dim": WEEKLY_I_DIM, "budget": args.budget,
        "no3_price": args.no3_price, "max_n": max_n,
        "nesting_err": nest_err, "default_irrigation_mm": d0["irrigation_mm"],
        "cma_evals": n_evals, "cma_history": hist,
        "mean_profit": {
            "default_test": mean(default_test),
            "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test),
        },
        "paired_test": {"fixed_vs_default": paired(fixed_test, default_test)},
        "per_window_test": fixed_test,
        "fixed_x": list(map(float, x)),
        "train_years": train, "test_years": test,
        "seconds": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nweekly default test {mean(default_test):.0f}")
    print(f"weekly CMA    train {mean(fixed_train):.0f}  test {mean(fixed_test):.0f}")
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
