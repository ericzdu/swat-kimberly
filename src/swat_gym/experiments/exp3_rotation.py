"""Experiment 3 — rotation by exhaustive enumeration (no CMA, no PPO).

There are 3^7 = 2,187 crop sequences; feasibility repair collapses many. Enumerating removes
optimizer artefacts on a discrete landscape.

Adaptivity is demoted: annual crop choice has little within-year state to react to. The
alfalfa:corn price sweep (:meth:`Prices.at_ratio`) is the calibration-bias sensitivity — a
−25 % corn yield bias is arithmetically a +33 % corn price.

**The λ_n frontier is free here and used to be missing.** Rule 1 wants the whole swept-λ_n
curve, not one point, and enumeration ranked sequences on a single profit scalar at λ_n = 0 —
so the winner could be *re-scored* at another nitrate price but never *re-selected*, which is
the question that matters ("what rotation would you choose if nitrate were priced?"). Every
enumerated sequence now stores its train means in the separable form
:func:`~swat_gym.frontier.profit_at` consumes, so re-selection at any λ is exact arithmetic on
stored numbers and costs no engine runs. The mean of a linear function is that function of the
means, so storing six means per sequence is not an approximation of storing every row.

``--max-n`` has no default, for the reason in :func:`~swat_gym.experiments._focused.run`: the
cap binds on ``DEFAULT_PLAN`` itself, so a capped rotation run cannot be composed with or
compared against an uncapped Exp 1 (rule 2). The rotation lever does not touch nitrogen, which
is exactly why the cap has to be stated rather than inherited from a default.

    uv run python -m swat_gym.experiments.exp3_rotation --max-n none
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..constrainers import repair, violations
from ..env import CROPS, DEFAULT_PLAN, N_YEARS, decode_year, evaluate
from ..fastrunner import FastRunner
from ..rewarders import average, profit
from ..schedule import YearAction
from ..frontier import SCORED_WATER, profit_at
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import ROOT, _max_n_arg, _row, mean, paired, score_measured

OUT = ROOT / "runs" / "exp3_rotation.json"
RATIOS = (0.6, 1.0, 1.18, 1.4, 1.63, 2.0, 3.0)
#: Nitrate prices the winner is re-selected at, $/kg N. Reported as a curve, never one point.
NO3_GRID = (0.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)

#: The separable terms a stored train mean needs for exact re-pricing (see ``frontier``).
TERMS = ("revenue", "irrigation_mm", "manure_cost", "fert_cost", "op_cost", "no3")


def _mean_terms(rows: list[dict]) -> dict:
    """Window-mean of each separable profit term.

    Exact for re-selection: profit is linear in every price, so the mean over windows of
    ``profit_at(row, λ)`` equals ``profit_at(mean_terms, λ)``.
    """
    return {k: float(np.mean([r[k] for r in rows])) for k in TERMS}


def _select_at(results: list[dict], no3_price: float) -> dict:
    """Best sequence by train mean profit at a given nitrate price — arithmetic, no engine."""
    best = max(results, key=lambda r: profit_at(r["train_terms"], SCORED_WATER, no3_price))
    return {"crops": best["crops"],
            "train_mean": profit_at(best["train_terms"], SCORED_WATER, no3_price)}


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
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="nitrate price the headline sequence is selected at; the whole "
                         "NO3_GRID is re-selected exactly either way (rule 1)")
    ap.add_argument("--max-n", type=_max_n_arg, default=None, metavar="KG|none",
                    help="REQUIRED. N loading cap kg N/ha/yr, or 'none'. No default: the cap "
                         "binds on DEFAULT_PLAN, so it must match any experiment these "
                         "results are composed with (rule 2)")
    ap.add_argument("--out", type=Path, default=OUT)
    tokens = list(argv) if argv is not None else sys.argv[1:]
    if not any(t == "--max-n" or t.startswith("--max-n=") for t in tokens):
        ap.error("--max-n is required: '--max-n 400' for the capped world, '--max-n none' for "
                 "the uncapped one (rule 2).")
    args = ap.parse_args(argv)
    max_n = args.max_n

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
            # Store the separable terms, not just the scalar. Same engine runs, and it is what
            # makes selection at any λ_n exact rather than unavailable.
            rows = [_row(evaluate(vec, runner, prices=prices, start_year=sy,
                                  no3_price=args.no3_price, max_n=max_n), sy)
                    for sy in train]
            results.append({"crops": list(crops),
                            "train_mean": mean(rows),
                            "train_terms": _mean_terms(rows)})

    # Selection happens at the run's nitrate price; the rest of the grid is re-selected from
    # the same stored terms, so the frontier is a curve and not one interior point (rule 1).
    frontier = {f"{lam:g}": _select_at(results, lam) for lam in sorted({*NO3_GRID,
                                                                       args.no3_price})}
    best = _select_at(results, args.no3_price)
    results.sort(key=lambda r: profit_at(r["train_terms"], SCORED_WATER, args.no3_price),
                 reverse=True)
    best_vec = _vector_from_plan(_plan_from_crops(tuple(best["crops"])))

    with FastRunner() as runner:
        best_test = [_row(evaluate(best_vec, runner, prices=prices, start_year=sy,
                                   no3_price=args.no3_price, max_n=max_n), sy)
                     for sy in test]
        best_train = [_row(evaluate(best_vec, runner, prices=prices, start_year=sy,
                                    no3_price=args.no3_price, max_n=max_n), sy)
                      for sy in train]
        # Price sweep: one engine run, re-price.
        evaluate(best_vec, runner, prices=prices, start_year=test[0],
                 no3_price=args.no3_price, max_n=max_n)
        sweep = {str(r): profit(runner, prices.at_ratio(r))["profit"] for r in RATIOS}
        default_vec = DEFAULT_PLAN.ravel()
        default_test = [_row(evaluate(default_vec, runner, prices=prices, start_year=sy,
                                      no3_price=args.no3_price, max_n=max_n), sy)
                        for sy in test]

    measured_test = score_measured(test, prices, args.no3_price)

    summary = {
        "n_feasible": len(feasible),
        "best_crops": best["crops"],
        # Recorded because Exp 4 refuses to warm-start from an artefact built in another world.
        "max_n": max_n, "no3_price": args.no3_price,
        # The deliverable of rule 1: which rotation wins at each nitrate price, exactly, with
        # no further simulation. A single row of this table is not the result.
        "no3_frontier": frontier,
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
        "top5": [{k: r[k] for k in ("crops", "train_mean")} for r in results[:5]],
        # Every sequence's separable train means, so any future price question is arithmetic.
        "train_terms": {"|".join(r["crops"]): r["train_terms"] for r in results},
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
