"""Perfect-foresight adaptivity ceiling for monthly irrigation (Exp 1 gate).

Optimise a *separate* open-loop monthly schedule for each weather window (oracle), and
compare the mean to one *shared* schedule optimised across all training windows. The gap is
the value of perfect information — an absolute upper bound on what any adaptive policy can
earn with any observation.

If the gap is inside the ~200–300 $/ha noise floor, Exp 1's adaptivity answer is already
known and cluster PPO should be skipped.

    uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..fastrunner import FastRunner
from ..monthly import (MONTHLY_I_DIM, default_monthly_i_free, evaluate_monthly_i)
from ..rewarders import average
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import ROOT, _row, mean, paired
from ._optimize import minimise

#: Noise floor from prior cadence/N sweeps — ceiling must clear this to justify PPO.
NOISE_FLOOR = 250.0

OUT = ROOT / "runs" / "exp1_ceiling.json"


def _score_shared(x, windows, prices, no3_price):
    with FastRunner() as runner:
        return [_row(evaluate_monthly_i(x, runner, prices=prices, start_year=sy,
                                        no3_price=no3_price), sy) for sy in windows]


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=5_000,
                    help="engine runs for the shared schedule (split across train windows)")
    ap.add_argument("--per-window-budget", type=int, default=2_000,
                    help="engine runs per oracle (single-window) optimisation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    train = list(TRAIN_YEARS)
    test = list(TEST_YEARS)
    x0 = default_monthly_i_free()
    t0 = time.time()

    # Shared schedule: one plan, mean profit over all training windows.
    evals_shared = max(1, args.budget // len(train))
    print(f"shared schedule: {evals_shared} CMA evals × {len(train)} windows", flush=True)

    with FastRunner() as runner:
        def shared_obj(free):
            total = 0.0
            for sy in train:
                try:
                    total += evaluate_monthly_i(free, runner, prices=prices,
                                                start_year=sy)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train)

        shared_x, n_shared, hist_shared = minimise(
            shared_obj, x0, evals=evals_shared, seed=args.seed)

    shared_train = _score_shared(shared_x, train, prices, 0.0)
    shared_test = _score_shared(shared_x, test, prices, 0.0)
    print(f"  shared train {mean(shared_train):.0f}  test {mean(shared_test):.0f}", flush=True)

    # Oracle: separate schedule per train window, then also per test window for the ceiling.
    oracles = {}
    evals_pw = max(1, args.per_window_budget)
    print(f"per-window oracles: {evals_pw} evals each", flush=True)
    with FastRunner() as runner:
        for sy in train + test:
            def obj(free, sy=sy):
                try:
                    return -evaluate_monthly_i(free, runner, prices=prices,
                                               start_year=sy)["profit"]
                except Exception:
                    return 1e9
            x, n, hist = minimise(obj, x0, evals=evals_pw, seed=args.seed + sy)
            d = evaluate_monthly_i(x, runner, prices=prices, start_year=sy)
            oracles[sy] = {"x": list(map(float, x)), "n_evals": n,
                           "profit": d["profit"], "irrigation_mm": d["irrigation_mm"],
                           "history": hist}
            print(f"  oracle {sy}: {d['profit']:.0f} $/ha", flush=True)

    oracle_train = [_row({"profit": oracles[sy]["profit"],
                          "revenue": 0, "water_cost": 0, "manure_cost": 0,
                          "fert_cost": 0, "op_cost": 0, "n_fert_events": 0,
                          "irrigation_mm": oracles[sy]["irrigation_mm"],
                          "manure_mg": 0, "fert_n_kg": 0, "no3_leached_kg": 0}, sy)
                    for sy in train]
    # Re-score oracles properly for cost decomposition on test.
    oracle_test = []
    with FastRunner() as runner:
        for sy in test:
            d = evaluate_monthly_i(oracles[sy]["x"], runner, prices=prices, start_year=sy)
            oracle_test.append(_row(d, sy))

    # Also score train oracles with full _row for paired comparison.
    oracle_train = []
    with FastRunner() as runner:
        for sy in train:
            d = evaluate_monthly_i(oracles[sy]["x"], runner, prices=prices, start_year=sy)
            oracle_train.append(_row(d, sy))

    ceiling_train = mean(oracle_train) - mean(shared_train)
    ceiling_test = mean(oracle_test) - mean(shared_test)
    gate_pass = ceiling_test > NOISE_FLOOR

    summary = {
        "train_years": train, "test_years": test,
        "noise_floor": NOISE_FLOOR,
        "shared": {"x": list(map(float, shared_x)), "n_evals": n_shared,
                   "history": hist_shared,
                   "train": mean(shared_train), "test": mean(shared_test)},
        "oracle": {"train": mean(oracle_train), "test": mean(oracle_test),
                   "per_window": {str(k): {"profit": v["profit"], "n_evals": v["n_evals"]}
                                  for k, v in oracles.items()}},
        "ceiling_train": ceiling_train,
        "ceiling_test": ceiling_test,
        "paired_test": paired(oracle_test, shared_test),
        "gate_pass": gate_pass,
        "gate_note": (
            f"ceiling {ceiling_test:+.0f} $/ha "
            f"{'exceeds' if gate_pass else 'inside'} noise floor {NOISE_FLOOR:.0f} — "
            f"{'proceed to PPO' if gate_pass else 'skip cluster PPO; write bounded null'}"
        ),
        "seconds": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"\nceiling train {ceiling_train:+.0f}  test {ceiling_test:+.0f} $/ha")
    print(summary["gate_note"])
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
