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
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..env import DEFAULT_PLAN
from ..obsnorm import ObsNorm, apply as apply_obsnorm
from ..fastrunner import FastRunner
from ..monthly import (default_monthly_i_free, evaluate_monthly_i)
from ..monthly_env import EPISODE_STEPS, MonthlySwatEnv
from ..rewarders import average
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import (ROOT, _cfg_key, _load_stage, _row, _save_stage, _stage,
                       _water_breakeven, mean, paired, score_measured)
from ._optimize import minimise

OUT = ROOT / "runs" / "exp1_irrigation.json"

#: Normalise observations before PPO sees them. Without this the policy learns an **exactly
#: constant** schedule: measured 2026-08-07, std of applied depth across held-out windows is
#: 0.000 mm raw vs 6.4 mm normalised, with return +1,320 $/ha and water 6,116 -> 5,352 mm.
#: The 13 channels carry order-of-magnitude divisors, not statistics, and several sit near zero.
NORMALISE_OBS = True
CLIP_OBS = 10.0

#: sigma ~ 0.14 on the unit action box. At the previous -1.0 (sigma ~ 0.37) the policy applied
#: 6,116 mm against a measured 3,939; at -2.0 it applied 4,533 mm, earned more, and saturated
#: 2 % of actions against 10 %.
LOG_STD_INIT = -2.0


def score_monthly(x, windows, prices, no3_price, max_n):
    """Open-loop score. ``max_n`` is **required**: it must match the policy path's cap.

    A silent ``max_n=MAX_N_LOADING`` default here once scored every open-loop row under a
    400 kg N/ha cap while :class:`MonthlySwatEnv` ran uncapped, which inverted the sign of
    ``policy - fixed``. Never give this a default again.
    """
    with FastRunner() as runner:
        return [_row(evaluate_monthly_i(x, runner, prices=prices, start_year=sy,
                                        no3_price=no3_price, max_n=max_n), sy)
                for sy in windows]


def score_policy_monthly(model, windows, prices, no3_price, max_n, obsnorm):
    """Roll out the deterministic policy on each window.

    ``obsnorm`` is **required**: a policy trained on normalised observations scored on raw ones
    is not a degraded policy, it is a different objective. Pass ``None`` only to state that this
    policy was trained on raw observations.
    """
    rows, plans = [], {}
    with MonthlySwatEnv(stochastic_weather=False, prices=prices, no3_price=no3_price,
                        arm="I", max_n=max_n) as env:
        for sy in windows:
            obs, _ = env.reset(start_year=sy)
            done = False
            while not done:
                action, _ = model.predict(apply_obsnorm(obsnorm, obs), deterministic=True)
                obs, _, done, _, info = env.step(action)
            y = env.runner.yields()
            rows.append(_row(info, sy,
                             yield_mg=float(y["yld(t)"].sum()) if len(y) else 0.0))
            plans[sy] = env.month_mm.copy()
    return rows, plans


def score_month_plan(month_mm, windows, prices, no3_price, max_n):
    from ..monthly import encode_monthly_depths
    x = encode_monthly_depths(month_mm)
    return score_monthly(x, windows, prices, no3_price, max_n)


def train_monthly_ppo(args, cfg, prices, max_n, seed: int):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

    from ._progress import ppo_callbacks, ppo_progress_bar

    scfg = {**cfg, "ppo_seed": seed}
    tag = f"ppo_s{seed}"
    ppo_path = args.out.with_name(f"{args.out.stem}_{tag}.zip")
    # The observation filter is part of the policy: scored raw, a normalised policy is solving a
    # different problem. Kept beside the weights and reloaded with them.
    norm_path = args.out.with_name(f"{args.out.stem}_{tag}_obsnorm.npz")
    # Config-keyed, as in _focused.py: the λ sweep trains one policy per nitrate price, and an
    # unkeyed directory would let a λ=0 checkpoint resume into a λ=40 run.
    ckpt_dir = args.out.parent / f"{args.out.stem}_{tag}_ckpt_{_cfg_key(scfg)}"

    def make(i):
        def _f():
            return MonthlySwatEnv(stochastic_weather=True, train_years=TRAIN_YEARS,
                                  prices=prices, no3_price=args.no3_price, seed=seed + i,
                                  arm="I", max_n=max_n).to_gym()
        return _f

    venv = SubprocVecEnv([make(i) for i in range(args.n_envs)])
    if NORMALISE_OBS:
        venv = VecNormalize(venv, norm_obs=True, norm_reward=False, clip_obs=CLIP_OBS)
    try:
        if ppo_path.is_file() and _load_stage(args.out, tag, scfg) is not None:
            model = PPO.load(str(ppo_path), env=venv)
            print(f"  seed {seed}: already trained to {model.num_timesteps} steps", flush=True)
            if not NORMALISE_OBS:
                return model, None
            if not norm_path.is_file():
                raise FileNotFoundError(
                    f"{ppo_path.name} was trained with observation normalisation but "
                    f"{norm_path.name} is missing. Scoring it on raw observations would be a "
                    "different objective — refusing. Delete the policy and retrain.")
            return model, ObsNorm.load(norm_path)
        resume = sorted(ckpt_dir.glob("*.zip"), key=lambda q: q.stat().st_mtime)
        if resume:
            model = PPO.load(str(resume[-1]), env=venv)
            print(f"  seed {seed}: resuming from {resume[-1].name} at "
                  f"{model.num_timesteps} steps", flush=True)
        else:
            print(f"  seed {seed}: training {args.budget} timesteps "
                  f"(episode={EPISODE_STEPS})", flush=True)
            model = PPO("MlpPolicy", venv, seed=seed, verbose=0,
                        n_steps=EPISODE_STEPS * 4, batch_size=EPISODE_STEPS * 2,
                        gamma=1.0, policy_kwargs={"log_std_init": LOG_STD_INIT})
        remaining = args.budget - int(model.num_timesteps)
        if remaining > 0:
            ckpt = CheckpointCallback(save_freq=max(1, args.budget // 20),
                                      save_path=str(ckpt_dir), name_prefix="ppo")
            model.learn(total_timesteps=remaining, reset_num_timesteps=False,
                        callback=ppo_callbacks(ckpt),
                        progress_bar=ppo_progress_bar())
        model.save(str(ppo_path.with_suffix("")))
        obsnorm = ObsNorm.from_vecnormalize(venv) if NORMALISE_OBS else None
        if obsnorm is not None:
            obsnorm.save(norm_path)
        _save_stage(args.out, tag, scfg, {"num_timesteps": int(model.num_timesteps)})
        return model, obsnorm
    finally:
        venv.close()


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=300_000)
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ppo-seeds", type=int, default=3)
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="$/kg N on leached nitrate. A swept axis, not a shadow price: "
                         "report the whole frontier with the 0 arm alongside")
    ap.add_argument("--water-price", type=float, default=None,
                    help="$/mm/ha override for the placeholder DEFAULT_WATER")
    ap.add_argument("--skip-ppo", action="store_true",
                    help="open-loop CMA only (use after a failed ceiling gate)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    if args.water_price is not None:
        # Label carries the override so an artefact identifies its own price vector.
        prices = replace(prices, water=args.water_price,
                         label=f"{prices.label}@w={args.water_price:g}")
    max_n = None
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    evals = max(1, args.budget // len(train))
    t0 = time.time()
    # Everything the training objective depends on must key the artefacts, or a stale policy
    # resumes into a different question. ``no3_price``/``max_n`` because they are the reward;
    # ``default_plan`` because every arm inherits its pinned levers (crop, manure, mineral N)
    # from it — correcting its manure to the measured per-year masses changed the objective for
    # every arm, and without this digest the previous policies would have been silently reused.
    cfg = {"arm": "I_monthly", "budget": args.budget, "seed": args.seed,
           "prices": prices.label, "train": train, "test": test,
           "no3_price": args.no3_price, "max_n": max_n,
           # The observation filter and exploration scale change what is learned, so they key
           # the artefacts too — a raw-observation policy must not resume into a normalised run.
           "normalise_obs": NORMALISE_OBS, "log_std_init": LOG_STD_INIT,
           "default_plan": _cfg_key({"p": DEFAULT_PLAN.round(6).tolist()})}

    print(f"Exp1 irrigation monthly  budget={args.budget}  "
          f"CMA evals={evals} × {len(train)} windows", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_name(f"{args.out.stem}_openloop.json")
    resumed_openloop = False
    if partial.is_file():
        try:
            prev = json.loads(partial.read_text())
        except (OSError, json.JSONDecodeError):
            prev = None
        # The guard must cover everything the CMA-ES objective depends on. It once checked only
        # arm and budget, so a schedule optimised under the 400 kg N/ha cap would silently
        # resume into an uncapped run and be reported as that run's optimum.
        if (isinstance(prev, dict) and prev.get("arm") == "I_monthly"
                and prev.get("budget") == args.budget and prev.get("fixed_x")
                and prev.get("no3_price", 0.0) == args.no3_price
                and prev.get("max_n", "missing") == max_n):
            print(f"resuming open-loop from {partial}", flush=True)
            summary = prev
            x = np.asarray(prev["fixed_x"], dtype=float)
            measured_test = score_measured(test, prices, args.no3_price)
            default_x = default_monthly_i_free()
            default_test = score_monthly(default_x, test, prices, args.no3_price, max_n)
            fixed_test = score_monthly(x, test, prices, args.no3_price, max_n)
            fixed_train = score_monthly(x, train, prices, args.no3_price, max_n)
            resumed_openloop = True

    if not resumed_openloop:
        measured_test = score_measured(test, prices, args.no3_price)
        default_x = default_monthly_i_free()
        default_test = score_monthly(default_x, test, prices, args.no3_price, max_n)
        print(f"measured {mean(measured_test):.0f}  monthly-default {mean(default_test):.0f} "
              f"({mean(default_test) - mean(measured_test):+.0f})", flush=True)

        # Nesting gate: monthly default irrigation vs measured total within 1%.
        with FastRunner() as runner:
            d0 = evaluate_monthly_i(default_x, runner, prices=prices, start_year=2013,
                                    max_n=max_n)
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
                                                    start_year=sy,
                                                    max_n=max_n)["profit"]
                    except Exception:
                        return 1e9
                return -total / len(train)
            x, n_evals, history = minimise(obj, x0, evals=evals, seed=args.seed,
                                           desc="CMA open-loop")

        fixed_test = score_monthly(x, test, prices, args.no3_price, max_n)
        fixed_train = score_monthly(x, train, prices, args.no3_price, max_n)
        print(f"CMA fixed test {mean(fixed_test):.0f}  "
              f"(+{mean(fixed_test) - mean(default_test):.0f} vs default)", flush=True)

        summary = {
            "arm": "I_monthly", "budget": args.budget,
            # Part of the CMA-ES objective; the resume guard above checks both.
            "no3_price": args.no3_price, "max_n": max_n,
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
        # Persist open-loop before PPO so a progress-bar / env crash does not discard CMA.
        partial.write_text(json.dumps(summary, indent=2, default=str))
        print(f"-> {partial}", flush=True)
    else:
        print(f"measured {mean(measured_test):.0f}  monthly-default {mean(default_test):.0f} "
              f"({mean(default_test) - mean(measured_test):+.0f})", flush=True)
        print(f"CMA fixed test {mean(fixed_test):.0f}  "
              f"(+{mean(fixed_test) - mean(default_test):.0f} vs default) [re-scored]",
              flush=True)
        summary["mean_profit"]["measured_test"] = mean(measured_test)
        summary["mean_profit"]["default_test"] = mean(default_test)
        summary["mean_profit"]["fixed_train"] = mean(fixed_train)
        summary["mean_profit"]["fixed_test"] = mean(fixed_test)
        summary["paired_test"]["default_vs_measured"] = paired(default_test, measured_test)
        summary["paired_test"]["fixed_vs_default"] = paired(fixed_test, default_test)

    if not args.skip_ppo:
        seeds = [args.seed + 100 * i for i in range(max(1, args.ppo_seeds))]
        per_seed = {}
        for s in seeds:
            model, obsnorm = train_monthly_ppo(args, cfg, prices, max_n, s)
            p_test, p_plans = score_policy_monthly(model, test, prices, args.no3_price,
                                                   max_n, obsnorm)
            p_train, p_plans_tr = score_policy_monthly(model, train, prices,
                                                       args.no3_price, max_n, obsnorm)
            fz_tr = {sy: score_month_plan(mm, train, prices, args.no3_price, max_n)
                     for sy, mm in p_plans_tr.items()}
            bf = max(fz_tr, key=lambda sy: mean(fz_tr[sy]))
            frozen_test = score_month_plan(p_plans_tr[bf], test, prices, args.no3_price,
                                           max_n)
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
