"""Experiment 2b — is the PPO advantage actually *adaptivity*?

Exp 2 reports the policy beating an optimized fixed schedule by +2,245 $/ha on held-out weather.
Two things could produce that number without any adaptivity at all, and both are testable.

**Control 1 — the frozen-plan test.** A policy that ignores its observations still emits *some*
action sequence, and that sequence may simply be a better point in action space than the
fixed-schedule optimizer found in its budget. So: take the action sequence the policy produces
on window *w*, freeze it, and replay it as a fixed schedule on every window. If the frozen plan
scores about what the adaptive policy scores, the advantage is optimization, not adaptivity. If
it collapses, the policy is genuinely conditioning on state.

**Control 2 — water-price sensitivity.** The policy irrigates far more than the fixed schedule,
and ``DEFAULT_WATER`` is an unfetched placeholder. Report the water price at which the advantage
disappears, so a reader can judge it against a real district rate instead of ours.

    uv run python -m swat_gym.experiments.exp2b_controls
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..env import ACTION_DIM, N_YEARS, SwatEnv, evaluate
from ..fastrunner import FastRunner
from ..rewarders import Prices, nass
from .exp2_rl import TEST_YEARS

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "exp2b_controls.json"


def policy_actions(model, windows, no3_price):
    """The raw action sequence the policy emits on each window."""
    seqs = {}
    with SwatEnv(stochastic_weather=False, no3_price=no3_price) as env:
        for sy in windows:
            obs, _ = env.reset(start_year=sy)
            acts, done = [], False
            while not done:
                a, _ = model.predict(obs, deterministic=True)
                acts.append(np.asarray(a, dtype=float).copy())
                obs, _, done, _, _ = env.step(a)
            seqs[sy] = np.concatenate(acts)
    return seqs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "runs" / "exp2_rl_ppo.zip")
    ap.add_argument("--exp2", type=Path, default=ROOT / "runs" / "exp2_rl.json")
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    from stable_baselines3 import PPO
    model = PPO.load(str(args.model))
    exp2 = json.loads(args.exp2.read_text())
    prices = nass(2024)

    seqs = policy_actions(model, TEST_YEARS, args.no3_price)

    # --- Control 1: freeze each window's plan, replay everywhere -------------------------
    frozen = {}
    with FastRunner() as r:
        for src, vec in seqs.items():
            frozen[src] = {}
            for tgt in TEST_YEARS:
                d = evaluate(vec, r, prices=prices, start_year=tgt, no3_price=args.no3_price)
                frozen[src][tgt] = d["profit"]

    policy_test = {r_["start_year"]: r_["profit"] for r_ in exp2["per_window"]["policy_test"]}
    fixed_test = {r_["start_year"]: r_["profit"] for r_ in exp2["per_window"]["fixed_test"]}

    # Off-diagonal only: a frozen plan scored on weather it was not produced for.
    off = [frozen[s][t] for s in TEST_YEARS for t in TEST_YEARS if s != t]
    best_frozen_src = max(TEST_YEARS,
                          key=lambda s: np.mean([frozen[s][t] for t in TEST_YEARS]))
    best_frozen = float(np.mean([frozen[best_frozen_src][t] for t in TEST_YEARS]))

    mean_policy = float(np.mean(list(policy_test.values())))
    mean_fixed = float(np.mean(list(fixed_test.values())))
    mean_frozen_off = float(np.mean(off))

    # --- Control 2: water-price break-even -----------------------------------------------
    pol_mm = float(np.mean([r_["irrigation_mm"] for r_ in exp2["per_window"]["policy_test"]]))
    fix_mm = float(np.mean([r_["irrigation_mm"] for r_ in exp2["per_window"]["fixed_test"]]))
    adv = mean_policy - mean_fixed
    extra_mm = pol_mm - fix_mm
    breakeven = prices.water + adv / extra_mm if extra_mm > 0 else float("inf")

    out = {
        "mean_policy": mean_policy,
        "mean_fixed": mean_fixed,
        "advantage": adv,
        "mean_frozen_offdiagonal": mean_frozen_off,
        "best_frozen_plan": {"source_window": best_frozen_src, "mean_profit": best_frozen},
        "adaptivity_share": (mean_policy - best_frozen) / adv if adv else float("nan"),
        "irrigation_mm": {"policy": pol_mm, "fixed": fix_mm,
                          "policy_mm_per_yr": pol_mm / N_YEARS, "fixed_mm_per_yr": fix_mm / N_YEARS},
        "water_price": {"used": prices.water, "breakeven": breakeven,
                        "breakeven_usd_per_acre_ft": breakeven / 10.0 * 1233.0},
        "frozen_matrix": {str(s): {str(t): v for t, v in row.items()} for s, row in frozen.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))

    print(f"\nadaptive policy (held-out)        {mean_policy:>10.0f}")
    print(f"optimized fixed schedule          {mean_fixed:>10.0f}")
    print(f"advantage                         {adv:>+10.0f}")
    print(f"\nCONTROL 1 — freeze the policy's own plan and replay it")
    print(f"  best frozen plan (from {best_frozen_src}) {best_frozen:>10.0f}")
    print(f"  frozen, off-diagonal mean       {mean_frozen_off:>10.0f}")
    print(f"  => share of advantage that is genuine adaptivity: "
          f"{100 * out['adaptivity_share']:.0f} %")
    print(f"\nCONTROL 2 — water price")
    print(f"  policy irrigates {pol_mm / N_YEARS:.0f} mm/yr vs fixed {fix_mm / N_YEARS:.0f} mm/yr "
          f"(measured practice 563)")
    print(f"  advantage vanishes at {breakeven:.2f} $/mm-ha "
          f"(~${out['water_price']['breakeven_usd_per_acre_ft']:.0f}/acre-ft); "
          f"we used {prices.water:.2f}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
