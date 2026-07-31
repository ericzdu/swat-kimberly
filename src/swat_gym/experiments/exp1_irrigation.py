"""Experiment 1 — irrigation (monthly growing-season cadence).

**Numbering = run order.** This is the first experiment: clearest a priori adaptivity case.

Pipeline (do not skip stages)::

    1. ``exp1_ceiling``     — perfect-foresight gate
    2. ``exp1_controller``  — CMA feedback controller row
    3. this module          — open-loop CMA monthly + PPO monthly + frozen (train-selected)

    uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
    uv run python -m swat_gym.experiments.exp1_controller --budget 5000
    uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..fastrunner import FastRunner
from ..monthly import (default_monthly_i_free, evaluate_monthly_i)
from ..monthly_env import EPISODE_STEPS, MonthlySwatEnv
from ..rewarders import average
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import (ROOT, _load_stage, _row, _save_stage, _stage, _water_breakeven,
                       mean, paired, score_measured)
from ._optimize import minimise

OUT = ROOT / "runs" / "exp1_irrigation.json"


def score_monthly(x, windows, prices, no3_price):
    with FastRunner() as runner:
        return [_row(evaluate_monthly_i(x, runner, prices=prices, start_year=sy,
                                        no3_price=no3_price), sy) for sy in windows]


def score_policy_monthly(model, windows, prices, no3_price, max_n):
    rows, plans = [], {}
    with MonthlySwatEnv(stochastic_weather=False, prices=prices, no3_price=no3_price,
                        arm="I", max_n=max_n) as env:
        for sy in windows:
            obs, _ = env.reset(start_year=sy)
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, _, info = env.step(action)
            rows.append(_row(info, sy))
            plans[sy] = env.month_mm.copy()
    return rows, plans


def score_month_plan(month_mm, windows, prices, no3_price):
    from ..monthly import encode_monthly_depths
    x = encode_monthly_depths(month_mm)
    return score_monthly(x, windows, prices, no3_price)


def train_monthly_ppo(args, cfg, prices, max_n, seed: int):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv

    scfg = {**cfg, "ppo_seed": seed}
    tag = f"ppo_s{seed}"
    ppo_path = args.out.with_name(f"{args.out.stem}_{tag}.zip")
    ckpt_dir = args.out.parent / f"{args.out.stem}_{tag}_ckpt"

    def make(i):
        def _f():
            return MonthlySwatEnv(stochastic_weather=True, train_years=TRAIN_YEARS,
                                  prices=prices, no3_price=args.no3_price, seed=seed + i,
                                  arm="I", max_n=max_n).to_gym()
        return _f

    venv = SubprocVecEnv([make(i) for i in range(args.n_envs)])
    try:
        if ppo_path.is_file() and _load_stage(args.out, tag, scfg) is not None:
            return PPO.load(str(ppo_path), env=venv)
        print(f"  seed {seed}: training {args.budget} timesteps "
              f"(episode={EPISODE_STEPS})", flush=True)
        model = PPO("MlpPolicy", venv, seed=seed, verbose=1,
                    n_steps=EPISODE_STEPS * 4, batch_size=EPISODE_STEPS * 2,
                    gamma=1.0, policy_kwargs={"log_std_init": -1.0})
        model.learn(total_timesteps=args.budget,
                    callback=CheckpointCallback(save_freq=max(1, args.budget // 20),
                                                save_path=str(ckpt_dir), name_prefix="ppo"))
        model.save(str(ppo_path.with_suffix("")))
        _save_stage(args.out, tag, scfg, {"num_timesteps": int(model.num_timesteps)})
        return model
    finally:
        venv.close()


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=300_000)
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ppo-seeds", type=int, default=3)
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--skip-ppo", action="store_true",
                    help="open-loop CMA only (use after a failed ceiling gate)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    max_n = None
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    evals = max(1, args.budget // len(train))
    t0 = time.time()
    cfg = {"arm": "I_monthly", "budget": args.budget, "seed": args.seed,
           "prices": prices.label, "train": train, "test": test}

    print(f"Exp1 irrigation monthly  budget={args.budget}  "
          f"CMA evals={evals} × {len(train)} windows", flush=True)

    measured_test = score_measured(test, prices, args.no3_price)
    default_x = default_monthly_i_free()
    default_test = score_monthly(default_x, test, prices, args.no3_price)
    print(f"measured {mean(measured_test):.0f}  monthly-default {mean(default_test):.0f} "
          f"({mean(default_test) - mean(measured_test):+.0f})", flush=True)

    # Nesting gate: monthly default irrigation vs measured total within 1%.
    with FastRunner() as runner:
        d0 = evaluate_monthly_i(default_x, runner, prices=prices, start_year=2013)
    measured_mm = 3938.8
    nest_err = abs(d0["irrigation_mm"] - measured_mm) / measured_mm
    print(f"nesting: monthly default {d0['irrigation_mm']:.1f} mm vs measured "
          f"{measured_mm} ({100 * nest_err:.2f}% err)", flush=True)

    x0 = default_x
    with FastRunner() as runner:
        def obj(free):
            total = 0.0
            for sy in train:
                try:
                    total += evaluate_monthly_i(free, runner, prices=prices,
                                                start_year=sy)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train)
        x, n_evals, history = minimise(obj, x0, evals=evals, seed=args.seed)

    fixed_test = score_monthly(x, test, prices, args.no3_price)
    fixed_train = score_monthly(x, train, prices, args.no3_price)
    print(f"CMA fixed test {mean(fixed_test):.0f}  "
          f"(+{mean(fixed_test) - mean(default_test):.0f} vs default)", flush=True)

    summary = {
        "arm": "I_monthly", "budget": args.budget,
        "nesting_err": nest_err, "default_irrigation_mm": d0["irrigation_mm"],
        "cma_evals": n_evals, "cma_history": history,
        "mean_profit": {
            "measured_test": mean(measured_test),
            "default_test": mean(default_test),
            "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test),
        },
        "paired_test": {
            "default_vs_measured": paired(default_test, measured_test),
            "fixed_vs_default": paired(fixed_test, default_test),
        },
        "fixed_x": list(map(float, x)),
        "train_years": train, "test_years": test,
        "seconds": round(time.time() - t0, 1),
    }

    if not args.skip_ppo:
        seeds = [args.seed + 100 * i for i in range(max(1, args.ppo_seeds))]
        per_seed = {}
        for s in seeds:
            model = train_monthly_ppo(args, cfg, prices, max_n, s)
            p_test, p_plans = score_policy_monthly(model, test, prices, args.no3_price, max_n)
            p_train, p_plans_tr = score_policy_monthly(model, train, prices,
                                                      args.no3_price, max_n)
            fz_tr = {sy: score_month_plan(mm, train, prices, args.no3_price)
                     for sy, mm in p_plans_tr.items()}
            bf = max(fz_tr, key=lambda sy: mean(fz_tr[sy]))
            frozen_test = score_month_plan(p_plans_tr[bf], test, prices, args.no3_price)
            per_seed[s] = {
                "policy_test": mean(p_test), "frozen_test": mean(frozen_test),
                "adv": mean(p_test) - mean(fixed_test),
                "adaptivity_value": mean(p_test) - mean(frozen_test),
                "test": p_test, "frozen": frozen_test, "best_frozen": bf,
            }
        rep = sorted(seeds, key=lambda s: per_seed[s]["policy_test"])[len(seeds) // 2]
        r = per_seed[rep]
        summary["mean_profit"]["policy_test"] = r["policy_test"]
        summary["mean_profit"]["frozen_test"] = r["frozen_test"]
        summary["advantage_over_fixed"] = r["adv"]
        summary["adaptivity_value"] = r["adaptivity_value"]
        summary["paired_test"]["policy_vs_fixed"] = paired(r["test"], fixed_test)
        summary["paired_test"]["frozen_vs_policy"] = paired(r["frozen"], r["test"])
        summary["ppo_seeds"] = seeds
        summary["representative_seed"] = rep
        summary["across_seeds"] = {
            k: {"mean": float(np.mean([per_seed[s][k] for s in seeds])),
                "by_seed": {str(s): per_seed[s][k] for s in seeds}}
            for k in ("adv", "adaptivity_value", "policy_test")
        }
        summary["water_breakeven"] = _water_breakeven(r["test"], fixed_test, prices)
        print(f"PPO test {r['policy_test']:.0f}  frozen {r['frozen_test']:.0f}  "
              f"adaptivity {r['adaptivity_value']:+.0f}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
