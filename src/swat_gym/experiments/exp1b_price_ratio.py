"""Experiment 1b — is the rotation result a finding, or a price assumption?

Exp 1's `R` arm eliminates alfalfa. That is only interesting if it survives the price vector,
because the rotation lever trades alfalfa against the annuals and Idaho alfalfa hay fell 43 % in
three years (the alfalfa:corn-silage ratio moved 1.63 -> 1.18 over 2022-24).

So: fix a handful of candidate rotations, sweep the alfalfa:corn price ratio, and find the
crossover where alfalfa becomes the profit-maximising choice. A single price vector would report
one point on this curve while hiding that it is a point.

Everything except the rotation is held at the measured-practice default, so the curves differ
only in crop sequence.

    uv run python -m swat_gym.experiments.exp1b_price_ratio
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..env import CROPS, DEFAULT_PLAN, N_YEARS, evaluate
from ..fastrunner import FastRunner
from ..rewarders import nass

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "exp1b_price_ratio.json"

#: Candidate rotations. `measured` is the field's own; `exp1_R` is what the `R` arm found.
ROTATIONS = {
    "measured":    ("corn", "barl", "alfa", "alfa", "alfa", "corn", "barl"),
    "exp1_R":      ("barl", "barl", "corn", "barl", "barl", "corn", "corn"),
    "alfalfa_all": ("alfa",) * N_YEARS,
    "corn_barl":   ("corn", "barl", "corn", "barl", "corn", "barl", "corn"),
}

RATIOS = (0.6, 0.8, 1.0, 1.18, 1.4, 1.63, 2.0, 2.5, 3.0)


def plan_vector(crops) -> np.ndarray:
    plan = DEFAULT_PLAN.copy()
    for i, crop in enumerate(crops):
        plan[i, 0:3] = 0.1
        plan[i, CROPS.index(crop)] = 0.9
    return plan.ravel()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    base = nass(2024)
    rows = {}
    with FastRunner() as r:
        for name, crops in ROTATIONS.items():
            vec = plan_vector(crops)
            # Yields do not depend on price, so run once and re-price.
            d = evaluate(vec, r, prices=base, start_year=args.start_year)
            rows[name] = {
                "crops": list(crops),
                "realised_crops": [c for c, _, _ in d["plan"]],
                "no3": d["no3_leached_kg"],
                "profit_by_ratio": {},
            }
            from ..rewarders import profit
            for ratio in RATIOS:
                rows[name]["profit_by_ratio"][str(ratio)] = profit(r, base.at_ratio(ratio))["profit"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"ratios": list(RATIOS), "rotations": rows}, indent=2))

    print(f"\nprofit ($/ha over 7 years) vs alfalfa:corn-silage price ratio\n")
    print(f"{'rotation':<13}" + "".join(f"{r:>9}" for r in RATIOS))
    for name, row in rows.items():
        print(f"{name:<13}" + "".join(
            f"{row['profit_by_ratio'][str(r)]:>9.0f}" for r in RATIOS))
    print(f"\n{'':13}" + "".join(f"{'':>9}" for _ in RATIOS))
    best = {r: max(rows, key=lambda n: rows[n]["profit_by_ratio"][str(r)]) for r in RATIOS}
    print("best rotation: " + ", ".join(f"{r}:{best[r]}" for r in RATIOS))
    print(f"\nNASS 2024 ratio is {base.alfalfa_ratio():.2f}; 2022-23 was 1.63.")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
