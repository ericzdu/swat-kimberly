"""Experiment 1 — which levers move the objective, and what is the bar RL must beat?

Six arms, each freeing a different subset of the action dimensions and optimizing an
**open-loop** schedule: the arm emits one complete 7-year plan, one engine run returns one
reward. The ablation *is* the experiment -- the question is not "what is the best schedule" but
"which action dimensions are worth handing an agent at all".

Deterministic weather on purpose. This runs on the measured 2012-2019 window so its numbers are
comparable with the calibration, and because an optimized fixed schedule on a fixed trace is
exactly the bar Experiment 2 has to beat. Stochastic weather enters in Exp 2, not here.

Arms are run in parallel processes, one :class:`FastRunner` each -- a runner owns a scratch
directory and is not shareable.

    uv run python -m swat_gym.experiments.exp1_ablation --evals 3000
"""
from __future__ import annotations

import argparse
import json
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np

from ..env import ARMS, N_YEARS, arm_vector, default_free, evaluate
from ..fastrunner import FastRunner
from ..rewarders import nass
from ._optimize import minimise

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "exp1_ablation.json"


def _run_arm(args) -> dict:
    arm, evals, seed, start_year, no3_price = args
    dims = ARMS[arm]
    prices = nass(2024)
    t0 = time.time()
    calls = {"n": 0}

    with FastRunner() as runner:
        def score(free) -> float:
            calls["n"] += 1
            try:
                d = evaluate(arm_vector(free, arm), runner, prices=prices,
                             start_year=start_year, no3_price=no3_price)
            except Exception:
                return 1e9
            return -d["profit"]          # minimise

        best_free, _, _ = minimise(score, default_free(arm), evals=evals, seed=seed)

        best = evaluate(arm_vector(best_free, arm), runner, prices=prices,
                        start_year=start_year, no3_price=no3_price)
        # Every arm's `default` is the same DEFAULT_PLAN, so `gain_vs_default` is comparable
        # across arms and `baseline` is exactly zero by construction.
        default = evaluate(arm_vector(default_free(arm), arm), runner, prices=prices,
                           start_year=start_year, no3_price=no3_price)

    return {
        "arm": arm,
        "free_dims": list(dims),
        "n_params": N_YEARS * len(dims),
        "evaluations": calls["n"],
        "seconds": round(time.time() - t0, 1),
        "profit": best["profit"],
        "profit_default": default["profit"],
        "gain_vs_default": best["profit"] - default["profit"],
        "revenue": best["revenue"],
        "water_cost": best["water_cost"],
        "manure_cost": best["manure_cost"],
        "irrigation_mm": best["irrigation_mm"],
        "manure_mg": best["manure_mg"],
        "no3_leached_kg": best["no3_leached_kg"],
        "plan": best["plan"],
        "x": list(map(float, best_free)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", type=int, default=3000, help="approx objective calls per arm")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="$/kg N leaching penalty; 0 keeps it a reported externality")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    jobs = [(arm, args.evals, args.seed, args.start_year, args.no3_price) for arm in ARMS]
    t0 = time.time()
    with get_context("spawn").Pool(len(jobs)) as pool:
        results = pool.map(_run_arm, jobs)

    results.sort(key=lambda r: -r["profit"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "start_year": args.start_year,
        "prices": nass(2024).label,
        "no3_price": args.no3_price,
        "wall_seconds": round(time.time() - t0, 1),
        "arms": results,
    }, indent=2))

    print(f"\n{'arm':<10}{'params':>8}{'evals':>8}{'profit':>12}{'vs default':>12}"
          f"{'irr mm':>9}{'manure':>9}{'NO3':>8}")
    for r in results:
        print(f"{r['arm']:<10}{r['n_params']:>8}{r['evaluations']:>8}{r['profit']:>12.0f}"
              f"{r['gain_vs_default']:>12.0f}{r['irrigation_mm']:>9.0f}"
              f"{r['manure_mg']:>9.0f}{r['no3_leached_kg']:>8.1f}")
    print(f"\n-> {args.out}  ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
