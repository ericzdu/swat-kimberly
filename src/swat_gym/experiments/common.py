"""Shared experiment machinery: stats, parallel CMA-ES, PPO, and the lever experiment.

Rows per lever: measured (shipped schedule replayed), default (measured practice via the
plan generator; quote gains vs this), fixed (CMA-ES open-loop), policy (PPO), frozen (the
policy's train-selected plan replayed open-loop). Budgets are matched in engine runs.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import multiprocessing as mp
import os
import pickle
import time
from pathlib import Path

import numpy as np

from ..env import SwatEnv, rollout
from ..fastrunner import TXTINOUT, FastRunner
from ..params import CALIBRATABLE
from ..plan import N_YEARS, SPINUP, default_x, evaluate, time_sim
from ..rewarders import Prices, average, profit
from ..windows import TEST_YEARS, TRAIN_YEARS, effective_n

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "runs"


# -- stats ----------------------------------------------------------------------------

def row(d: dict, start_year: int) -> dict:
    """One window's outcome with separable cost terms."""
    keys = ("profit", "revenue", "water_cost", "manure_cost", "fert_cost", "op_cost",
            "n_fert_events", "irrigation_mm", "manure_mg", "fert_n_kg", "n2o_kg")
    return {"start_year": start_year, "no3": d["no3_leached_kg"], **{k: d[k] for k in keys}}


def mean(rows) -> float:
    return float(np.mean([r["profit"] for r in rows]))


def paired(a: list[dict], b: list[dict], *, n_boot: int = 10_000, seed: int = 0) -> dict:
    """Paired per-window difference a - b. Quote se_ess (windows overlap; rule 7).

    No ``se`` key on purpose; se_naive is kept only to show the ratio.
    """
    d = np.array([r["profit"] for r in a]) - np.array([r["profit"] for r in b])
    n = int(d.size)
    ess = effective_n([r["start_year"] for r in a]) if n > 1 else float(n)
    sd = float(d.std(ddof=1)) if n > 1 else float("nan")
    se_naive = sd / np.sqrt(n) if n > 1 else float("nan")
    se_ess = sd / np.sqrt(ess) if n > 1 else float("nan")
    if n > 1:
        means = d[np.random.default_rng(seed).integers(0, n, size=(n_boot, n))].mean(axis=1)
        ci_boot = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
        ci_ess = [float(d.mean() - 1.96 * se_ess), float(d.mean() + 1.96 * se_ess)]
    else:
        ci_boot = ci_ess = [float("nan"), float("nan")]
    return {"mean": float(d.mean()), "n": n, "ess": float(ess), "sd": sd,
            "se_naive": float(se_naive), "se_ess": float(se_ess),
            "ci95_boot": ci_boot, "ci95_ess": ci_ess,
            "resolvable": bool(n > 1 and ci_ess[0] * ci_ess[1] > 0),
            "per_window": [round(float(v), 1) for v in d]}


# -- engine access, per process ---------------------------------------------------------

_RUNNER: FastRunner | None = None


def runner() -> FastRunner:
    """This process's FastRunner (one per worker)."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = FastRunner()
    return _RUNNER


def score(lever: str, x, windows, prices: Prices, no3_price: float) -> list[dict]:
    return [row(evaluate(lever, x, runner(), prices=prices, start_year=sy,
                         no3_price=no3_price), sy) for sy in windows]


def score_measured(windows, prices: Prices, no3_price: float) -> list[dict]:
    """Shipped management.sch replayed on each window (only time.sim changes)."""
    out = []
    for sy in windows:
        runner().run({"time.sim": time_sim(sy, N_YEARS + SPINUP)})
        out.append(row(profit(runner(), prices, no3_price=no3_price), sy))
    return out


def neg_mean_profit(x, lever, windows, prices, no3_price) -> float:
    """CMA-ES objective: -mean profit of an open-loop plan over windows."""
    try:
        return -mean(score(lever, x, windows, prices, no3_price))
    except Exception:
        return 1e9


# -- CMA-ES ---------------------------------------------------------------------------

def minimise(fn, x0, *, evals: int, seed: int = 0, workers: int = 1, sigma0: float = 0.25,
             label: str = "CMA-ES"):
    """Minimise a picklable ``fn`` over [0, 1]^n, evaluating each generation in parallel.

    Returns (best_x, n_evals, history of {evals, best_f}). Deterministic given seed.
    """
    import warnings
    warnings.filterwarnings("ignore", message="Could not import matplotlib")
    import cma

    x0 = np.clip(np.asarray(x0, dtype=float), 0.0, 1.0)
    es = cma.CMAEvolutionStrategy(list(x0), sigma0, {"bounds": [0.0, 1.0], "maxfevals": evals,
                                                     "seed": seed + 1, "verbose": -9})
    best_x, best_f, history = x0, float("inf"), []
    pool = mp.get_context("spawn").Pool(workers) if workers > 1 else None
    t0 = time.time()
    try:
        while not es.stop():
            xs = es.ask()
            fs = [float(f) for f in (pool.map(fn, xs) if pool else map(fn, xs))]
            for x, f in zip(xs, fs):
                if f < best_f:
                    best_f, best_x = f, np.asarray(x).copy()
            es.tell(xs, fs)
            history.append({"evals": int(es.countevals), "best_f": best_f})
            print(f"  {label}: {es.countevals}/{evals} evals  best objective {best_f:.6g}  "
                  f"{time.time() - t0:.0f}s", flush=True)
    finally:
        if pool:
            pool.close()
    return best_x, int(es.countevals), history


# -- stage reuse ------------------------------------------------------------------------

def model_hash() -> str:
    """Hash of the calibratable model files; part of every stage config."""
    h = hashlib.sha256()
    for name in sorted(CALIBRATABLE):
        p = TXTINOUT / name
        h.update(name.encode() + (p.read_bytes() if p.is_file() else b""))
    return h.hexdigest()[:10]


def load_stage(path: Path, cfg: dict):
    """Stage result if ``path`` exists and was produced with the same config."""
    if path.is_file():
        d = json.loads(path.read_text())
        if d.get("config") == cfg:
            print(f"  reusing {path.name}", flush=True)
            return d["result"]
        print(f"  {path.name} has a different config; recomputing", flush=True)
    return None


def save_stage(path: Path, cfg: dict, result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"config": cfg, "result": result}, indent=2))


# -- PPO ------------------------------------------------------------------------------

def _make_env(lever, prices, no3_price, seed):
    return SwatEnv(lever, prices=prices, no3_price=no3_price, seed=seed).to_gym()


def train_ppo(lever: str, prices: Prices, no3_price: float, budget: int, seed: int,
              n_envs: int, ckpt_dir: Path):
    """Train (or resume) one PPO policy; returns (model, VecNormalize stats)."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

    final, stats = ckpt_dir / "final.zip", ckpt_dir / "vecnormalize.pkl"
    if final.is_file() and stats.is_file():
        print(f"  seed {seed}: already trained", flush=True)
        return PPO.load(str(final)), pickle.loads(stats.read_bytes())

    venv = SubprocVecEnv([functools.partial(_make_env, lever, prices, no3_price, seed + i)
                          for i in range(n_envs)])
    ckpts = sorted(ckpt_dir.glob("ppo_*_steps.zip"), key=lambda p: int(p.stem.split("_")[1]))
    try:
        if ckpts:
            steps = ckpts[-1].stem.split("_")[1]
            venv = VecNormalize.load(str(ckpt_dir / f"ppo_vecnormalize_{steps}_steps.pkl"),
                                     venv)
            model = PPO.load(str(ckpts[-1]), env=venv)
            print(f"  seed {seed}: resuming at {model.num_timesteps} steps", flush=True)
        else:
            venv = VecNormalize(venv, norm_obs=True, norm_reward=False, clip_obs=10.0)
            ep = 42 if lever == "I" else 24  # steps per episode
            model = PPO("MlpPolicy", venv, seed=seed, verbose=0, n_steps=4 * ep,
                        batch_size=2 * ep, gamma=1.0, policy_kwargs={"log_std_init": -2.0})
        remaining = budget - int(model.num_timesteps)
        if remaining > 0:
            cb = CheckpointCallback(save_freq=max(1, budget // (20 * n_envs)),
                                    save_path=str(ckpt_dir), name_prefix="ppo",
                                    save_vecnormalize=True)
            model.learn(total_timesteps=remaining, reset_num_timesteps=False, callback=cb)
        model.save(str(final))
        venv.save(str(stats))
        venv.training = False
        return model, pickle.loads(stats.read_bytes())
    finally:
        venv.close()


def policy_fn(model, vecnorm):
    def act(env, obs):
        action, _ = model.predict(vecnorm.normalize_obs(obs), deterministic=True)
        return action
    return act


# -- the lever experiment -------------------------------------------------------------

def run(lever: str, out: Path, argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=300_000,
                    help="engine runs per method (CMA-ES and each PPO seed)")
    ap.add_argument("--ppo-seeds", type=int, default=3)
    ap.add_argument("--skip-ppo", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                    help="parallel processes for CMA-ES")
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="$/kg N leached; one frontier point (report the whole sweep)")
    ap.add_argument("--water-price", type=float, default=None)
    ap.add_argument("--out", type=Path, default=out)
    args = ap.parse_args(argv)

    prices = average()
    if args.water_price is not None:
        from dataclasses import replace
        prices = replace(prices, water=args.water_price,
                         label=f"{prices.label}@w={args.water_price:g}")
    train, test, no3 = list(TRAIN_YEARS), list(TEST_YEARS), args.no3_price
    cfg = {"lever": lever, "budget": args.budget, "seed": args.seed, "no3_price": no3,
           "prices": prices.label, "water": prices.water, "model": model_hash()}
    t0 = time.time()

    measured_test = score_measured(test, prices, no3)
    default_test = score(lever, default_x(lever), test, prices, no3)
    print(f"measured {mean(measured_test):.0f}  default {mean(default_test):.0f} $/ha",
          flush=True)

    fixed_path = args.out.with_name(f"{args.out.stem}_fixed.json")
    fixed = load_stage(fixed_path, cfg)
    if fixed is None:
        fn = functools.partial(neg_mean_profit, lever=lever, windows=train, prices=prices,
                               no3_price=no3)
        x, n_evals, history = minimise(fn, default_x(lever), evals=args.budget // len(train),
                                       seed=args.seed, workers=args.workers, label="fixed")
        fixed = {"x": list(map(float, x)), "n_evals": n_evals, "history": history}
        save_stage(fixed_path, cfg, fixed)
    fixed_test = score(lever, fixed["x"], test, prices, no3)
    fixed_train = score(lever, fixed["x"], train, prices, no3)
    print(f"fixed {mean(fixed_test):.0f} $/ha", flush=True)

    summary = {
        "lever": lever, "config": cfg, "train_years": train, "test_years": test,
        "fixed_x": fixed["x"], "cma_evals": fixed["n_evals"], "cma_history": fixed["history"],
        "mean_profit": {"measured_test": mean(measured_test),
                        "default_test": mean(default_test),
                        "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test)},
        "paired_test": {"default_vs_measured": paired(default_test, measured_test),
                        "fixed_vs_default": paired(fixed_test, default_test)},
        "per_window": {"measured_test": measured_test, "default_test": default_test,
                       "fixed_test": fixed_test},
    }

    if not args.skip_ppo:
        seeds = [args.seed + 100 * i for i in range(args.ppo_seeds)]
        per_seed = {}
        for s in seeds:
            seed_path = args.out.with_name(f"{args.out.stem}_ppo_s{s}.json")
            res = load_stage(seed_path, {**cfg, "ppo_seed": s})
            if res is None:
                key = hashlib.sha256(json.dumps({**cfg, "ppo_seed": s},
                                                sort_keys=True).encode()).hexdigest()[:10]
                ckpt = args.out.parent / f"{args.out.stem}_ppo_s{s}_{key}"
                model, vn = train_ppo(lever, prices, no3, args.budget, s, args.n_envs, ckpt)
                act = policy_fn(model, vn)
                with SwatEnv(lever, prices=prices, no3_price=no3) as env:
                    pol_test = [rollout(env, act, sy) for sy in test]
                    pol_train = [rollout(env, act, sy) for sy in train]
                # Frozen: pick the policy's best train-window plan on train, replay on test.
                cand = {sy: mean(score(lever, r["x"], train, prices, no3))
                        for sy, r in zip(train, pol_train)}
                best = max(cand, key=cand.get)
                frozen_x = pol_train[train.index(best)]["x"]
                res = {"policy_test": [row(r, sy) for r, sy in zip(pol_test, test)],
                       "frozen_test": score(lever, frozen_x, test, prices, no3),
                       "frozen_from": best, "frozen_x": list(map(float, frozen_x))}
                save_stage(seed_path, {**cfg, "ppo_seed": s}, res)
            per_seed[s] = res
            print(f"seed {s}: policy {mean(res['policy_test']):.0f}  "
                  f"frozen {mean(res['frozen_test']):.0f} $/ha", flush=True)

        def by_seed(f):
            return {str(s): f(per_seed[s]) for s in seeds}

        adv = by_seed(lambda r: mean(r["policy_test"]) - mean(fixed_test))
        adapt = by_seed(lambda r: mean(r["policy_test"]) - mean(r["frozen_test"]))
        rep = sorted(seeds, key=lambda s: mean(per_seed[s]["policy_test"]))[len(seeds) // 2]
        r = per_seed[rep]
        summary["mean_profit"].update(policy_test=mean(r["policy_test"]),
                                      frozen_test=mean(r["frozen_test"]))
        summary["paired_test"].update(policy_vs_fixed=paired(r["policy_test"], fixed_test),
                                      frozen_vs_policy=paired(r["frozen_test"],
                                                              r["policy_test"]))
        summary.update(ppo_seeds=seeds, representative_seed=rep,
                       advantage_over_fixed=adv, adaptivity_value=adapt,
                       sign_consistent={"advantage_over_fixed": len({v > 0 for v in adv.values()}) == 1,
                                        "adaptivity_value": len({v > 0 for v in adapt.values()}) == 1})

    summary["seconds"] = round(time.time() - t0, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"-> {args.out}")
    return summary
