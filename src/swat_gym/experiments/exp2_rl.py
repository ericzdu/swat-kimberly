"""Experiment 2 — does adaptivity pay once weather is stochastic?

The research question, and the first one for which RL is the right tool. Three pieces:

1. **The bar.** An *optimized fixed schedule* — one plan, chosen open-loop, scored as the mean
   profit across the training weather windows. This is the honest comparator: beating an
   unoptimized default would prove nothing.
2. **The policy.** PPO on the annual-cadence :class:`~swat_gym.env.SwatEnv`, which resamples an
   8-year weather window every episode, so the policy sees weather it must react to.
3. **Held-out evaluation.** Both are scored on weather windows never used for training.

The split is by window start year: **1995-2011 train, 2012-2018 test**. The test half contains
the measured GRACEnet rotation window, which keeps the headline number interpretable against
the calibration.

Why this is a real question and not a formality: on a single deterministic trace a sequential
policy *cannot* beat an optimized fixed schedule, because there is nothing to condition on. Any
advantage here has to come from adaptivity. A null is a result.

    uv run python -m swat_gym.experiments.exp2_rl --timesteps 60000 --fixed-evals 300
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..env import ARMS, N_YEARS, SwatEnv, arm_vector, default_free, evaluate
from ..fastrunner import FastRunner
from ..rewarders import nass
from ._optimize import minimise

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "exp2_rl.json"

TRAIN_YEARS = list(range(1995, 2012))   # 17 windows
TEST_YEARS = list(range(2012, 2019))    # 7 windows, includes the measured rotation


def make_env(train_years, seed, no3_price):
    """Picklable factory for SubprocVecEnv."""
    def _f():
        return SwatEnv(stochastic_weather=True, train_years=train_years,
                       no3_price=no3_price, seed=seed).to_gym()
    return _f


def optimize_fixed(train_windows, evals, seed, no3_price):
    """The bar: one open-loop plan maximising mean profit over the training windows."""
    prices = nass(2024)
    dims = ARMS["all"]
    n = N_YEARS * len(dims)
    calls = {"n": 0}

    with FastRunner() as runner:
        def score(free):
            calls["n"] += 1
            vec = arm_vector(free, "all")
            total = 0.0
            for sy in train_windows:
                try:
                    total += evaluate(vec, runner, prices=prices, start_year=sy,
                                      no3_price=no3_price)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train_windows)

        best, _, _ = minimise(score, default_free("all"), evals=evals, seed=seed)
    return best, calls["n"]


def score_fixed(x, windows, no3_price):
    prices = nass(2024)
    vec = arm_vector(x, "all")
    out = []
    with FastRunner() as runner:
        for sy in windows:
            d = evaluate(vec, runner, prices=prices, start_year=sy, no3_price=no3_price)
            out.append({"start_year": sy, "profit": d["profit"],
                        "irrigation_mm": d["irrigation_mm"], "manure_mg": d["manure_mg"],
                        "no3": d["no3_leached_kg"]})
    return out


def score_policy(model, windows, no3_price):
    out = []
    with SwatEnv(stochastic_weather=False, no3_price=no3_price) as env:
        for sy in windows:
            obs, _ = env.reset(start_year=sy)
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, _, info = env.step(action)
            out.append({"start_year": sy, "profit": info["cum_profit"],
                        "irrigation_mm": info["irrigation_mm"],
                        "manure_mg": info["manure_mg"], "no3": info["no3_leached_kg"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=60_000)
    ap.add_argument("--fixed-evals", type=int, default=300)
    ap.add_argument("--fixed-windows", type=int, default=8,
                    help="training windows averaged per fixed-schedule evaluation")
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    t0 = time.time()
    sub = list(np.linspace(0, len(TRAIN_YEARS) - 1, args.fixed_windows).round().astype(int))
    fixed_windows = [TRAIN_YEARS[i] for i in sorted(set(sub))]
    print(f"fixed-schedule training windows: {fixed_windows}", flush=True)

    x, n_calls = optimize_fixed(fixed_windows, args.fixed_evals, args.seed, args.no3_price)
    t_fixed = time.time() - t0
    print(f"fixed schedule optimised: {n_calls} evals in {t_fixed:.0f}s", flush=True)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv

    t1 = time.time()
    venv = SubprocVecEnv([make_env(TRAIN_YEARS, args.seed + i, args.no3_price)
                          for i in range(args.n_envs)])
    # gamma=1.0: the objective is *total* rotation profit over a fixed 7-year horizon, so there
    # is no reason to discount. log_std_init=-1 narrows the initial policy to sigma~0.37 on a
    # unit box; SB3's default sigma=1 explores almost entirely in the clipped region.
    model = PPO("MlpPolicy", venv, seed=args.seed, verbose=1,
                n_steps=N_YEARS * 8, batch_size=N_YEARS * 4, gamma=1.0,
                policy_kwargs={"log_std_init": -1.0})
    model.learn(total_timesteps=args.timesteps)
    venv.close()
    t_rl = time.time() - t1
    model.save(str(args.out.with_suffix("")) + "_ppo")

    fixed_test = score_fixed(x, TEST_YEARS, args.no3_price)
    fixed_train = score_fixed(x, fixed_windows, args.no3_price)
    policy_test = score_policy(model, TEST_YEARS, args.no3_price)
    policy_train = score_policy(model, fixed_windows, args.no3_price)

    def mean(rows):
        return float(np.mean([r["profit"] for r in rows]))

    summary = {
        "train_years": TRAIN_YEARS, "test_years": TEST_YEARS,
        "fixed_windows": fixed_windows,
        "timesteps": args.timesteps, "fixed_evals": n_calls,
        "seconds": {"fixed": round(t_fixed, 1), "rl": round(t_rl, 1),
                    "total": round(time.time() - t0, 1)},
        "mean_profit": {
            "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test),
            "policy_train": mean(policy_train), "policy_test": mean(policy_test),
        },
        "advantage_test": mean(policy_test) - mean(fixed_test),
        "per_window": {"fixed_test": fixed_test, "policy_test": policy_test,
                       "fixed_train": fixed_train, "policy_train": policy_train},
        "fixed_x": list(map(float, x)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    m = summary["mean_profit"]
    print(f"\n{'':<14}{'train':>12}{'held-out':>12}")
    print(f"{'fixed schedule':<14}{m['fixed_train']:>12.0f}{m['fixed_test']:>12.0f}")
    print(f"{'PPO policy':<14}{m['policy_train']:>12.0f}{m['policy_test']:>12.0f}")
    print(f"\nadaptivity advantage on held-out weather: "
          f"{summary['advantage_test']:+.0f} $/ha "
          f"({100 * summary['advantage_test'] / abs(m['fixed_test']):+.1f} %)")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
