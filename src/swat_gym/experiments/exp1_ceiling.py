"""Exp 1 gate: per-window oracle schedule vs one shared schedule = foresight value.

An estimate, not an upper bound (oracles can be under-converged). If within the ~250 $/ha
noise floor, skip PPO.

    uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
"""
from __future__ import annotations

import argparse
import functools
import json
from pathlib import Path

from ..plan import default_x
from ..rewarders import average
from ..windows import TEST_YEARS, TRAIN_YEARS
from .common import RUNS, mean, minimise, neg_mean_profit, paired, score

NOISE_FLOOR = 250.0


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=5_000, help="engine runs, shared schedule")
    ap.add_argument("--per-window-budget", type=int, default=2_000, help="evals per oracle")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=RUNS / "exp1_ceiling.json")
    args = ap.parse_args(argv)

    prices, train, test = average(), list(TRAIN_YEARS), list(TEST_YEARS)
    obj = functools.partial(neg_mean_profit, lever="I", prices=prices, no3_price=0.0)

    shared_x, n_shared, _ = minimise(functools.partial(obj, windows=train), default_x("I"),
                                     evals=args.budget // len(train), seed=args.seed,
                                     workers=args.workers, label="shared")
    shared_test = score("I", shared_x, test, prices, 0.0)

    oracle_test = []
    for sy in test:
        x, _, _ = minimise(functools.partial(obj, windows=[sy]), default_x("I"),
                           evals=args.per_window_budget, seed=args.seed + sy,
                           workers=args.workers, label=f"oracle {sy}")
        oracle_test += score("I", x, [sy], prices, 0.0)

    foresight = mean(oracle_test) - mean(shared_test)
    summary = {"test_years": test, "noise_floor": NOISE_FLOOR, "prices": prices.label,
               "shared_x": list(map(float, shared_x)), "shared_test": mean(shared_test),
               "oracle_test": mean(oracle_test), "foresight_test": foresight,
               "paired_test": paired(oracle_test, shared_test),
               "gate_pass": bool(foresight > NOISE_FLOOR)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"foresight {foresight:+.0f} $/ha  gate_pass={summary['gate_pass']}  -> {args.out}")
    return summary


if __name__ == "__main__":
    main()
