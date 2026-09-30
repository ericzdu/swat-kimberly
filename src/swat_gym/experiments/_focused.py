"""Shared focused-experiment runner: one free arm, scored against controls.

Rows: measured (shipped schedule replayed), grower (fitted rule), default (DEFAULT_PLAN via
generator; quote gains vs this), fixed (CMA-ES), policy (PPO), frozen (policy's plan replayed
fixed; separates adaptivity from better search). Budgets matched in engine runs. Prices fixed
at rewarders.average(). Rows keep cost terms so they can be re-priced without rerunning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

from ..env import (ARMS, DEFAULT_ACTION, N_YEARS, OBS_DIM, SPINUP, SwatEnv, _edits, arm_vector,
                   default_free, evaluate, time_sim)
from ..schedule import IRR_EFF
from ..fastrunner import FastRunner
from ..constrainers import MAX_N_LOADING
from ..rewarders import Prices, average, profit
from ..schedule import YearAction
from ._optimize import minimise

from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage, effective_n

ROOT = Path(__file__).resolve().parents[3]
assert_no_leakage()


def _row(d: dict, start_year: int, *, yield_mg: float | None = None) -> dict:
    """One window's outcome with separable cost terms."""
    return {"start_year": start_year, "profit": d["profit"],
            "revenue": d["revenue"], "water_cost": d["water_cost"],
            "manure_cost": d["manure_cost"], "fert_cost": d["fert_cost"],
            "op_cost": d["op_cost"], "n_fert_events": d["n_fert_events"],
            "irrigation_mm": d["irrigation_mm"], "manure_mg": d["manure_mg"],
            "fert_n_kg": d["fert_n_kg"], "no3": d["no3_leached_kg"],
            "n2o_kg": d.get("n2o_kg"), "yield_mg": yield_mg}


#: Fixed bootstrap size and seed for reproducible intervals.
N_BOOT = 10_000
BOOT_SEED = 0


def paired(a: list[dict], b: list[dict], *, n_boot: int = N_BOOT,
           seed: int = BOOT_SEED) -> dict:
    """Paired per-window difference a - b. Quote se_ess (windows overlap; rule 7).

    No ``se`` key on purpose; se_naive is kept only to show the ratio.
    """
    d = np.array([r["profit"] for r in a]) - np.array([r["profit"] for r in b])
    n = int(d.size)
    starts = [r.get("start_year") for r in a]
    known = [s for s in starts if s is not None]
    ess = effective_n(known) if len(known) == n and n > 1 else float(n)
    sd = float(d.std(ddof=1)) if n > 1 else float("nan")
    se_naive = sd / np.sqrt(n) if n > 1 else float("nan")
    se_ess = sd / np.sqrt(ess) if n > 1 and ess > 0 else float("nan")
    if n > 1:
        rng = np.random.default_rng(seed)
        means = d[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
        ci_boot = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
        ci_ess = [float(d.mean() - 1.96 * se_ess), float(d.mean() + 1.96 * se_ess)]
    else:
        ci_boot = ci_ess = [float("nan"), float("nan")]
    return {"mean": float(d.mean()),
            "n": n, "ess": float(ess), "sd": sd,
            "se_naive": float(se_naive), "se_ess": float(se_ess),
            "ci95_boot": ci_boot, "ci95_ess": ci_ess,
            "resolvable": bool(n > 1 and ci_ess[0] * ci_ess[1] > 0),
            "per_window": [round(float(v), 1) for v in d]}


def score_measured(windows, prices: Prices, no3_price: float) -> list[dict]:
    """Shipped management.sch replayed on each window (only time.sim changes)."""
    out = []
    with FastRunner() as runner:
        for sy in windows:
            runner.run({"time.sim": time_sim(sy, N_YEARS + SPINUP)})
            out.append(_row(profit(runner, prices, no3_price=no3_price), sy))
    return out


#: Output of exp1_grower_rule; reused by Exp 2.
GROWER_FIT = ROOT / "runs" / "exp1_grower_rule.json"


def score_grower(windows, prices: Prices, no3_price: float, max_n) -> list[dict]:
    """Fitted grower irrigation rule on each window; N at DEFAULT_PLAN."""
    from .exp1_controller import rollout_controller   # avoid circular import

    if not GROWER_FIT.is_file():
        raise SystemExit(f"{GROWER_FIT.name} missing: run `python -m "
                         "swat_gym.experiments.exp1_grower_rule` first (it is Exp 1's, and "
                         "run order is paper order)")
    fit = json.loads(GROWER_FIT.read_text())
    if not fit.get("fit", {}).get("gate_pass"):
        raise SystemExit(f"{GROWER_FIT.name} failed its rule 5 gate; refusing to score it")
    out = []
    with FastRunner() as runner:
        for sy in windows:
            out.append(_row(rollout_controller(fit["abc"], runner, start_year=sy,
                                               prices=prices, no3_price=no3_price,
                                               max_n=max_n), sy))
    return out


#: CMA-ES checkpoint interval in seconds (time-based; engine throughput varies).
PARTIAL_SECONDS = 120.0


def _load_partial(path: Path | None, cfg: dict):
    """CMA-ES checkpoint, only if its config matches."""
    if path is None or not path.is_file():
        return None
    try:
        d = pickle.loads(path.read_bytes())
    except Exception:
        return None
    if d.get("cfg") != cfg:
        print("  partial: ignoring checkpoint, config differs", flush=True)
        return None
    return d


def optimize_fixed(arm, train_windows, evals, seed, prices, no3_price, max_n,
                   partial_path: Path | None = None, cfg: dict | None = None):
    """CMA-ES from default_free(arm). ``evals`` is the total budget; resumes full CMA state."""
    prev = _load_partial(partial_path, cfg)
    state, done = (prev["state"], prev["evals"]) if prev else (None, 0)
    if prev:
        print(f"  resuming CMA-ES from partial at {done} evals "
              f"(covariance and step size restored)", flush=True)
    clock = {"flushed": time.time()}

    with FastRunner() as runner:
        def score(free):
            vec = arm_vector(free, arm)
            total = 0.0
            for sy in train_windows:
                try:
                    total += evaluate(vec, runner, prices=prices, start_year=sy,
                                      no3_price=no3_price, max_n=max_n)["profit"]
                except Exception:
                    return 1e9
            return -total / len(train_windows)

        def checkpoint(blob, n, best_x, best_f):
            now = time.time()
            if partial_path is None or now - clock["flushed"] < PARTIAL_SECONDS:
                return
            clock["flushed"] = now
            partial_path.write_bytes(pickle.dumps({
                "cfg": cfg, "state": blob, "evals": n,
                "train_obj": -best_f, "x": list(map(float, best_x)),
            }))

        start = default_free(arm)
        best, n_evals, history = minimise(score, start, evals=evals, seed=seed,
                                          state=state, on_generation=checkpoint)
        # Include runs spent before a resume.
        n_runs = runner.n_runs + done * len(train_windows)
    return best, n_evals, n_runs, history


def score_fixed(x, arm, windows, prices, no3_price, max_n) -> list[dict]:
    vec = arm_vector(x, arm)
    with FastRunner() as runner:
        return [_row(evaluate(vec, runner, prices=prices, start_year=sy,
                              no3_price=no3_price, max_n=max_n), sy) for sy in windows]


def score_policy(model, arm, windows, prices, no3_price, max_n):
    """Policy scores and the plan it chose per window."""
    rows, plans = [], {}
    with SwatEnv(stochastic_weather=False, prices=prices, no3_price=no3_price, arm=arm,
                 max_n=max_n) as env:
        for sy in windows:
            obs, _ = env.reset(start_year=sy)
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, _, info = env.step(action)
            rows.append(_row(info, sy))
            plans[sy] = list(env.plan)
    return rows, plans


def score_plan(plan: list[YearAction], windows, prices, no3_price) -> list[dict]:
    """Replay one fixed plan on every window (adaptivity control)."""
    with FastRunner() as runner:
        out = []
        for sy in windows:
            runner.run(_edits(plan, sy))
            out.append(_row(profit(runner, prices, no3_price=no3_price), sy))
    return out


def make_env(arm, train_years, prices, seed, no3_price, max_n):
    def _f():
        return SwatEnv(stochastic_weather=True, train_years=train_years, prices=prices,
                       no3_price=no3_price, seed=seed, arm=arm, max_n=max_n).to_gym()
    return _f


def train_policy(arm, args, cfg, prices, max_n, seed: int):
    """Train PPO at ``seed``; resume only from checkpoints keyed by seed + config digest."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv

    from ._progress import ppo_callbacks

    scfg = {**cfg, "ppo_seed": seed}
    tag = f"ppo_s{seed}"
    ppo_path = args.out.with_name(f"{args.out.stem}_{tag}.zip")
    ckpt_dir = args.out.parent / f"{args.out.stem}_{tag}_ckpt_{_cfg_key(scfg)}"

    venv = SubprocVecEnv([make_env(arm, TRAIN_YEARS, prices, seed + i, args.no3_price, max_n)
                          for i in range(args.n_envs)])
    try:
        if ppo_path.is_file() and _load_stage(args.out, tag, scfg) is not None:
            model = PPO.load(str(ppo_path), env=venv)
            print(f"  seed {seed}: already trained to {model.num_timesteps} steps", flush=True)
            return model
        resume = sorted(ckpt_dir.glob("*.zip"), key=lambda q: q.stat().st_mtime)
        if resume:
            model = PPO.load(str(resume[-1]), env=venv)
            print(f"  seed {seed}: resuming from {resume[-1].name} at "
                  f"{model.num_timesteps} steps", flush=True)
        else:
            # gamma=1: undiscounted rotation total. log_std_init=-1: sigma~0.37 on unit box.
            print(f"  seed {seed}: training {args.budget} timesteps", flush=True)
            model = PPO("MlpPolicy", venv, seed=seed, verbose=0,
                        n_steps=max(64, N_YEARS * 8), batch_size=max(32, N_YEARS * 4),
                        gamma=1.0, policy_kwargs={"log_std_init": -1.0})
        remaining = args.budget - model.num_timesteps
        if remaining > 0:
            ckpt = CheckpointCallback(save_freq=max(1, args.budget // 20),
                                      save_path=str(ckpt_dir), name_prefix="ppo")
            from ._progress import ppo_progress_bar
            model.learn(
                total_timesteps=remaining, reset_num_timesteps=False,
                callback=ppo_callbacks(ckpt),
                progress_bar=ppo_progress_bar(),
            )
        model.save(str(ppo_path.with_suffix("")))
        _save_stage(args.out, tag, scfg, {"num_timesteps": int(model.num_timesteps)})
        return model
    finally:
        venv.close()


def mean(rows) -> float:
    return float(np.mean([r["profit"] for r in rows]))


def _stage(out: Path, name: str) -> Path:
    return out.with_name(f"{out.stem}_{name}.json")


def _water_breakeven(a: list[dict], b: list[dict], prices: Prices) -> dict:
    """Water price at which a's advantage over b vanishes (profit is linear in price)."""
    adv = mean(a) - mean(b)
    dmm = float(np.mean([r["irrigation_mm"] for r in a])
                - np.mean([r["irrigation_mm"] for r in b]))
    if abs(dmm) < 1e-9:
        return {"scored_price": prices.water, "delta_mm": dmm, "breakeven": None,
                "note": "advantage does not depend on the water price"}
    return {"scored_price": prices.water, "delta_mm": dmm,
            "breakeven": float(prices.water + adv / dmm),
            "note": "advantage vanishes at this $/mm/ha; sign of delta_mm gives the direction"}


def model_digest() -> str:
    """Hash of CALIBRATABLE model files, so checkpoints never resume across a recalibration."""
    from swat_gym.fastrunner import TXTINOUT
    from swat_gym.params import CALIBRATABLE

    h = hashlib.sha256()
    for name in sorted(CALIBRATABLE):
        path = TXTINOUT / name
        h.update(name.encode())
        h.update(path.read_bytes() if path.is_file() else b"<absent>")
    return h.hexdigest()[:10]


def _cfg_key(cfg: dict) -> str:
    """Short stable digest of a run config."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]


def _load_stage(out: Path, name: str, cfg: dict):
    """Completed stage payload if config matches."""
    p = _stage(out, name)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if d.get("config") != cfg:
        print(f"  stage {name}: ignoring checkpoint, config differs", flush=True)
        return None
    print(f"  stage {name}: resumed from checkpoint", flush=True)
    return d["payload"]


def _save_stage(out: Path, name: str, cfg: dict, payload) -> None:
    _stage(out, name).write_text(json.dumps({"config": cfg, "payload": payload}, indent=2))


def _max_n_arg(text: str) -> float | None:
    """Parse --max-n: number or none/off. No default on purpose (rule 2)."""
    t = text.strip().lower()
    if t in {"none", "off", "uncapped"}:
        return None
    try:
        v = float(t)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--max-n expects a number or 'none', got {text!r}") from None
    return v if v > 0 else None


def run(arm: str, out_path: Path, argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=300_000,
                    help="engine runs, matched across PPO and CMA-ES "
                         "(raised from 50k: monthly episodes are ~6× longer)")
    ap.add_argument("--fixed-windows", type=int, default=0,
                    help="training windows for CMA-ES; 0 = use every TRAIN_YEARS window "
                         "(matched set with PPO)")
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ppo-seeds", type=int, default=1,
                    help="PPO replicates (seed, seed+100, ...). The CMA-ES row is shared: the "
                         "policy is the stochastic half and the one whose null is reported.")
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--max-n", type=_max_n_arg, default=None, metavar="KG|none",
                    help=f"REQUIRED. N loading cap kg N/ha/yr (the paper's value is "
                         f"{MAX_N_LOADING:g}), or 'none' for an uncapped run. Deliberately has "
                         f"no default: it must match across every experiment whose results are "
                         f"composed or compared (rule 2)")
    ap.add_argument("--out", type=Path, default=out_path)
    args = ap.parse_args(argv)

    tokens = list(argv) if argv is not None else sys.argv[1:]
    if not any(t == "--max-n" or t.startswith("--max-n=") for t in tokens):
        ap.error("--max-n is required: pass '--max-n 400' for the capped world or "
                 "'--max-n none' for the uncapped one. Exp 1 runs uncapped, so composing or "
                 "comparing against it needs 'none' here (rule 2).")
    prices = average()
    max_n = args.max_n
    t0 = time.time()

    if args.fixed_windows <= 0 or args.fixed_windows >= len(TRAIN_YEARS):
        fixed_windows = list(TRAIN_YEARS)
    else:
        sub = list(np.linspace(0, len(TRAIN_YEARS) - 1, args.fixed_windows).round().astype(int))
        fixed_windows = [TRAIN_YEARS[i] for i in sorted(set(sub))]
    # CMA eval = one run per window; PPO = one run per timestep.
    evals = max(1, args.budget // len(fixed_windows))
    print(f"arm={arm}  prices={prices.label}  budget={args.budget} engine runs  "
          f"cap={'none' if max_n is None else f'{max_n:g}'} kg N/ha\n"
          f"fixed-schedule windows: {fixed_windows}  -> {evals} CMA-ES evals", flush=True)

    # Resumable stages; key includes env semantics (obs_dim, irr_eff, defaults).
    cfg = {"arm": arm, "budget": args.budget, "seed": args.seed, "max_n": max_n,
           "no3_price": args.no3_price, "fixed_windows": fixed_windows,
           "prices": prices.label, "fert_op": prices.fert_op, "manure": prices.manure,
           "obs_dim": OBS_DIM, "irr_eff": IRR_EFF,
           "default_action": [round(float(v), 6) for v in DEFAULT_ACTION]}

    stage = _load_stage(args.out, "measured", cfg)
    if stage is None:
        measured_test = score_measured(TEST_YEARS, prices, args.no3_price)
        measured_train = score_measured(fixed_windows, prices, args.no3_price)
        _save_stage(args.out, "measured", cfg,
                    {"test": measured_test, "train": measured_train})
    else:
        measured_test, measured_train = stage["test"], stage["train"]
    print(f"measured practice (human bar): held-out {mean(measured_test):.0f} $/ha", flush=True)

    # Like-for-like control: quote lever gains against this.
    stage = _load_stage(args.out, "default", cfg)
    if stage is None:
        default_test = score_fixed(np.zeros(0), "baseline", TEST_YEARS, prices,
                                   args.no3_price, max_n)
        default_train = score_fixed(np.zeros(0), "baseline", fixed_windows, prices,
                                    args.no3_price, max_n)
        _save_stage(args.out, "default", cfg,
                    {"test": default_test, "train": default_train})
    else:
        default_test, default_train = stage["test"], stage["train"]
    print(f"DEFAULT_PLAN baseline (like-for-like): held-out {mean(default_test):.0f} $/ha "
          f"({mean(default_test) - mean(measured_test):+.0f} vs human)", flush=True)

    # Keyed on fitted params so a refit can't resume a stale row.
    grower_abc = json.loads(GROWER_FIT.read_text())["abc"] if GROWER_FIT.is_file() else None
    gcfg = {**cfg, "grower_abc": grower_abc}
    stage = _load_stage(args.out, "grower", gcfg)
    if stage is None:
        grower_test = score_grower(TEST_YEARS, prices, args.no3_price, max_n)
        grower_train = score_grower(fixed_windows, prices, args.no3_price, max_n)
        _save_stage(args.out, "grower", gcfg, {"test": grower_test, "train": grower_train})
    else:
        grower_test, grower_train = stage["test"], stage["train"]
    print(f"grower rule (fitted to the logs): held-out {mean(grower_test):.0f} $/ha "
          f"({mean(grower_test) - mean(measured_test):+.0f} vs replayed log)", flush=True)

    stage = _load_stage(args.out, "fixed", cfg)
    if stage is None:
        pp = _stage(args.out, "fixed").with_suffix(".partial.pkl")
        x, n_evals, fixed_runs, cma_history = optimize_fixed(
            arm, fixed_windows, evals, args.seed, prices, args.no3_price,
            max_n, partial_path=pp, cfg=cfg)
        _save_stage(args.out, "fixed", cfg,
                    {"x": list(map(float, x)), "n_evals": n_evals,
                     "engine_runs": fixed_runs, "seconds": time.time() - t0,
                     "history": cma_history})
    else:
        x, n_evals, fixed_runs = stage["x"], stage["n_evals"], stage["engine_runs"]
        cma_history = stage.get("history", [])
    t_fixed = time.time() - t0
    print(f"fixed schedule: {n_evals} evals / {fixed_runs} engine runs in {t_fixed:.0f}s",
          flush=True)

    t1 = time.time()
    # One shared CMA-ES row; only PPO is replicated across seeds.
    seeds = [args.seed + 100 * i for i in range(max(1, args.ppo_seeds))]
    models = {s: train_policy(arm, args, cfg, prices, max_n, s) for s in seeds}
    t_rl = time.time() - t1

    fixed_test = score_fixed(x, arm, TEST_YEARS, prices, args.no3_price, max_n)
    fixed_train = score_fixed(x, arm, fixed_windows, prices, args.no3_price, max_n)

    # Frozen plan selected on train, scored on test (rule 6).
    per_seed = {}
    for s, model in models.items():
        p_test, p_plans = score_policy(model, arm, TEST_YEARS, prices, args.no3_price, max_n)
        p_train, p_plans_train = score_policy(model, arm, fixed_windows, prices,
                                              args.no3_price, max_n)
        fz_train = {sy: score_plan(pl, fixed_windows, prices, args.no3_price)
                    for sy, pl in p_plans_train.items()}
        fz_train_means = {sy: mean(rows) for sy, rows in fz_train.items()}
        bf = max(fz_train_means, key=fz_train_means.get)
        frozen_test = score_plan(p_plans_train[bf], TEST_YEARS, prices, args.no3_price)
        fz_test_dist = {sy: score_plan(pl, TEST_YEARS, prices, args.no3_price)
                        for sy, pl in p_plans.items()}
        fz_test_means = {sy: mean(rows) for sy, rows in fz_test_dist.items()}
        per_seed[s] = {"test": p_test, "train": p_train, "plans": p_plans,
                       "frozen": {bf: frozen_test}, "frozen_means": {bf: mean(frozen_test)},
                       "frozen_test_dist_means": fz_test_means,
                       "best_frozen": bf,
                       "policy_test": mean(p_test), "frozen_best_test": mean(frozen_test),
                       "adv": mean(p_test) - mean(fixed_test),
                       "adaptivity_value": mean(p_test) - mean(frozen_test)}

    def across(k):
        """Mean and SE across seeds (seeds are independent, so plain ``se`` is correct)."""
        v = np.array([per_seed[s][k] for s in seeds])
        return {"mean": float(v.mean()),
                "se": float(v.std(ddof=1) / np.sqrt(v.size)) if v.size > 1 else float("nan"),
                "by_seed": {str(s): float(per_seed[s][k]) for s in seeds}}

    seed_stats = {k: across(k) for k in
                  ("policy_test", "frozen_best_test", "adv", "adaptivity_value")}

    # Representative seed = median, not best.
    rep = sorted(seeds, key=lambda s: per_seed[s]["policy_test"])[len(seeds) // 2]
    r = per_seed[rep]
    policy_test, policy_train, plans = r["test"], r["train"], r["plans"]
    frozen, frozen_means, best_frozen = r["frozen"], r["frozen_means"], r["best_frozen"]

    adv = mean(policy_test) - mean(fixed_test)
    # Policy minus its own frozen plan.
    adaptivity_value = mean(policy_test) - frozen_means[best_frozen]
    # Share only defined when adv > 0 (else sign trap).
    adaptivity_share = (adaptivity_value / adv) if adv > 0 else None

    summary = {
        "arm": arm, "prices": prices.label, "budget_engine_runs": args.budget,
        "max_n": max_n, "no3_price": args.no3_price, "fert_op": prices.fert_op,
        "train_years": TRAIN_YEARS, "test_years": TEST_YEARS,
        "fixed_windows": fixed_windows,
        "cma_evals": n_evals, "cma_engine_runs": fixed_runs, "ppo_timesteps": args.budget,
        "cma_history": cma_history,
        "frozen_selection": "train",
        "seconds": {"fixed": round(t_fixed, 1), "rl": round(t_rl, 1),
                    "total": round(time.time() - t0, 1)},
        "mean_profit": {
            "measured_train": mean(measured_train), "measured_test": mean(measured_test),
            "grower_train": mean(grower_train), "grower_test": mean(grower_test),
            "default_train": mean(default_train), "default_test": mean(default_test),
            "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test),
            "policy_train": mean(policy_train), "policy_test": mean(policy_test),
            "frozen_best_test": frozen_means[best_frozen],
        },
        # vs_default = attributable gain; vs_measured = realism check.
        "vs_default": {
            "fixed": mean(fixed_test) - mean(default_test),
            "policy": mean(policy_test) - mean(default_test),
            "frozen": frozen_means[best_frozen] - mean(default_test),
        },
        "vs_measured": {
            "default": mean(default_test) - mean(measured_test),
            "fixed": mean(fixed_test) - mean(measured_test),
            "policy": mean(policy_test) - mean(measured_test),
            "frozen": frozen_means[best_frozen] - mean(measured_test),
        },
        "vs_grower": {
            "default": mean(default_test) - mean(grower_test),
            "fixed": mean(fixed_test) - mean(grower_test),
            "policy": mean(policy_test) - mean(grower_test),
        },
        "grower_fit": {"abc": grower_abc, "source": GROWER_FIT.name,
                       "note": "fitted to 2013-2019 logged behaviour; a reference row, "
                               "not a learned arm"},
        "paired_test": {
            "default_vs_measured": paired(default_test, measured_test),
            "fixed_vs_default": paired(fixed_test, default_test),
            "fixed_vs_measured": paired(fixed_test, measured_test),
            "grower_vs_measured": paired(grower_test, measured_test),
            "fixed_vs_grower": paired(fixed_test, grower_test),
            "policy_vs_default": paired(policy_test, default_test),
            "policy_vs_fixed": paired(policy_test, fixed_test),
            "frozen_vs_policy": paired(frozen[best_frozen], policy_test),
        },
        "advantage_over_fixed": adv,
        "adaptivity_value": adaptivity_value,
        "adaptivity_share": adaptivity_share,
        "ppo_seeds": seeds, "representative_seed": rep, "across_seeds": seed_stats,
        "water_breakeven": _water_breakeven(policy_test, fixed_test, prices),
        "best_frozen_window": best_frozen,
        "frozen_means": {str(k): v for k, v in frozen_means.items()},
        "per_window": {"measured_test": measured_test, "grower_test": grower_test,
                       "default_test": default_test,
                       "fixed_test": fixed_test, "policy_test": policy_test},
        "policy_plan": {str(sy): [(a.crop, round(a.manure_mg, 1),
                                   [(d, round(kg, 1)) for d, kg in a.fert_splits],
                                   round(a.irr_depth, 1)) for a in p]
                        for sy, p in plans.items()},
        "fixed_x": list(map(float, x)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    m, v, vd = summary["mean_profit"], summary["vs_measured"], summary["vs_default"]
    print(f"\narm {arm}   prices {prices.label}   budget {args.budget} engine runs")
    print(f"{'':<26}{'train':>10}{'held-out':>11}{'vs default':>12}{'vs human':>11}")
    print(f"{'logged schedule, replayed':<26}{m['measured_train']:>10.0f}"
          f"{m['measured_test']:>11.0f}{'—':>12}{'—':>11}")
    print(f"{'grower rule (fitted)':<26}{m['grower_train']:>10.0f}{m['grower_test']:>11.0f}"
          f"{'—':>12}{m['grower_test'] - m['measured_test']:>+11.0f}")
    print(f"{'DEFAULT_PLAN baseline':<26}{m['default_train']:>10.0f}{m['default_test']:>11.0f}"
          f"{'—':>12}{v['default']:>+11.0f}")
    print(f"{'CMA-ES fixed schedule':<26}{m['fixed_train']:>10.0f}{m['fixed_test']:>11.0f}"
          f"{vd['fixed']:>+12.0f}{v['fixed']:>+11.0f}")
    print(f"{'PPO policy':<26}{m['policy_train']:>10.0f}{m['policy_test']:>11.0f}"
          f"{vd['policy']:>+12.0f}{v['policy']:>+11.0f}")
    print(f"{'  its own plan, frozen':<26}{'':>10}{m['frozen_best_test']:>11.0f}"
          f"{vd['frozen']:>+12.0f}{v['frozen']:>+11.0f}")

    # ESS interval is the one that counts.
    ess = summary["paired_test"]["fixed_vs_default"]["ess"]
    print(f"\n{'paired held-out differences':<30}{'mean':>10}{'se(ESS)':>10}{'se(naive)':>11}"
          f"{'95% CI (ESS)':>24}")
    for name, p in summary["paired_test"].items():
        lo, hi = p["ci95_ess"]
        print(f"{name:<30}{p['mean']:>+10.0f}{p['se_ess']:>10.0f}{p['se_naive']:>11.0f}"
              f"{f'[{lo:+.0f}, {hi:+.0f}]':>24}")
    print(f"  n = {len(TEST_YEARS)} held-out windows, effective sample size {ess:.2f} "
          f"(rule 7: quote se(ESS), never se(naive))")
    share = ("n/a — the policy has no edge over the fixed schedule to apportion"
             if adaptivity_share is None else f"{100 * adaptivity_share:+.0f} % of it")
    print(f"\npolicy over fixed: {adv:+.0f} $/ha")
    print(f"adaptivity worth:  {adaptivity_value:+.0f} $/ha (policy vs its own frozen plan); "
          f"share: {share}")

    if len(seeds) > 1:
        a, v = seed_stats["adv"], seed_stats["adaptivity_value"]
        print(f"\nacross {len(seeds)} PPO seeds (representative = median seed {rep}):")
        print(f"{'  policy over fixed':<26}{a['mean']:>+10.0f} +/- {a['se']:<8.0f}"
              f"{list(map(round, a['by_seed'].values()))}")
        print(f"{'  adaptivity worth':<26}{v['mean']:>+10.0f} +/- {v['se']:<8.0f}"
              f"{list(map(round, v['by_seed'].values()))}")

    wb = summary["water_breakeven"]
    if wb["breakeven"] is None:
        print(f"\nwater price: {wb['note']} (both rows apply the same water)")
    else:
        print(f"\nwater price scored at {wb['scored_price']:.2f} $/mm/ha; policy applies "
              f"{wb['delta_mm']:+.0f} mm vs fixed, advantage vanishes at "
              f"{wb['breakeven']:.2f} $/mm/ha")
    print(f"-> {args.out}")
    return summary
