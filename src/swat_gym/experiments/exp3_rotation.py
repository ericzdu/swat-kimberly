"""Experiment 3 — rotation by exhaustive enumeration (no CMA, no PPO).

There are 3^7 = 2,187 crop sequences; feasibility repair collapses many. Enumerating removes
optimizer artefacts on a discrete landscape.

Adaptivity is demoted: annual crop choice has little within-year state to react to. The
alfalfa:corn price sweep (:meth:`Prices.at_ratio`) is the calibration-bias sensitivity — a
−25 % corn yield bias is arithmetically a +33 % corn price.

    uv run python -m swat_gym.experiments.exp3_rotation
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..constrainers import repair, violations
from ..env import CROPS, DEFAULT_PLAN, N_YEARS, decode_year, evaluate
from ..fastrunner import FastRunner
from ..rewarders import average, profit
from ..schedule import YearAction
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import ROOT, _row, mean, paired, score_measured

OUT = ROOT / "runs" / "exp3_rotation.json"
RATIOS = (0.6, 1.0, 1.18, 1.4, 1.63, 2.0, 3.0)


def _plan_from_crops(crops: tuple[str, ...]) -> list[YearAction]:
    plan = []
    for y, crop in enumerate(crops):
        base = decode_year(DEFAULT_PLAN[y])
        plan.append(replace(base, crop=crop))
    return repair(plan)


def _vector_from_plan(plan: list[YearAction]) -> np.ndarray:
    full = DEFAULT_PLAN.copy()
    for y, a in enumerate(plan):
        full[y, 0:3] = 0.1
        full[y, CROPS.index(a.crop)] = 0.9
    return full.ravel()


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-seqs", type=int, default=0,
                    help="cap on sequences scored (0 = all feasible)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    t0 = time.time()

    seen: set[tuple[str, ...]] = set()
    feasible: list[tuple[str, ...]] = []
    for crops in itertools.product(CROPS, repeat=N_YEARS):
        plan = _plan_from_crops(crops)
        key = tuple(a.crop for a in plan)
        if key in seen:
            continue
        seen.add(key)
        if violations(plan):
            continue
        feasible.append(key)
        if args.max_seqs and len(feasible) >= args.max_seqs:
            break

    print(f"feasible unique rotations: {len(feasible)}", flush=True)

    results = []
    with FastRunner() as runner:
        for crops in feasible:
            vec = _vector_from_plan(_plan_from_crops(crops))
            profits = [evaluate(vec, runner, prices=prices, start_year=sy)["profit"]
                       for sy in train]
            results.append({"crops": list(crops), "train_mean": float(np.mean(profits))})

    results.sort(key=lambda r: r["train_mean"], reverse=True)
    best = results[0]
    best_vec = _vector_from_plan(_plan_from_crops(tuple(best["crops"])))

    with FastRunner() as runner:
        best_test = [_row(evaluate(best_vec, runner, prices=prices, start_year=sy), sy)
                     for sy in test]
        best_train = [_row(evaluate(best_vec, runner, prices=prices, start_year=sy), sy)
                      for sy in train]
        # Price sweep: one engine run, re-price.
        evaluate(best_vec, runner, prices=prices, start_year=test[0])
        sweep = {str(r): profit(runner, prices.at_ratio(r))["profit"] for r in RATIOS}
        default_vec = DEFAULT_PLAN.ravel()
        default_test = [_row(evaluate(default_vec, runner, prices=prices, start_year=sy), sy)
                        for sy in test]

    measured_test = score_measured(test, prices, 0.0)

    summary = {
        "n_feasible": len(feasible),
        "best_crops": best["crops"],
        "mean_profit": {
            "measured_test": mean(measured_test),
            "default_test": mean(default_test),
            "best_train": mean(best_train),
            "best_test": mean(best_test),
        },
        "paired_test": {
            "best_vs_default": paired(best_test, default_test),
            "best_vs_measured": paired(best_test, measured_test),
        },
        "top5": results[:5],
        "price_sweep": sweep,
        "seconds": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"best {best['crops']}  test {mean(best_test):.0f} $/ha")
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
