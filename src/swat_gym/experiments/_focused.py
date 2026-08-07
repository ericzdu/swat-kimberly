"""One lever, five rows, a human bar inside the experiment. Shared by Exp 1, 2 and 3.

The three focused experiments differ only in which :data:`~swat_gym.env.ARMS` entry is free,
so the machinery lives here once and each ``expN_*.py`` is an entry point that names its arm.

Five rows, and two of them are controls
---------------------------------------
========================  =========================================================
``measured``              the field's own shipped ``management.sch`` — the human bar
``default``               **``DEFAULT_PLAN`` through the same schedule generator**
``fixed``                 best non-adaptive plan for this lever, CMA-ES
``policy``                PPO on the annual-cadence env
``frozen``                **the policy's own plan, replayed as a fixed schedule**
========================  =========================================================

``default`` is the like-for-like baseline and ``measured`` is the realism check; an arm's gain
should be read against the first and sanity-checked against the second. They differ because a
generated fixed-interval schedule is not the shipped irregular one even when both are aimed at
measured practice, and last round that residual was mistaken for the lever: two compounding
defects (:data:`~swat_gym.schedule.IRR_EFF` at 0.85, and an irrigation depth that integrated to
3,060 mm against a measured 3,938.8) meant every optimized row was scored against a *drier*
field than the human bar. Both are fixed, but the row stays: the whole point of a control is
that it is measured rather than assumed to be zero.

``frozen`` exists because last round's headline (+12.9 % for PPO) survived until it was run
and then did not: the policy's own frozen plan scored *higher* than the adaptive policy, so
the advantage was never adaptivity, it was that PPO had found a better constant than CMA-ES
did on 1/30th the budget. Reporting ``policy`` against ``fixed`` alone cannot tell those apart.
It costs one engine run per held-out window.

Budgets are matched in engine runs
----------------------------------
PPO's ``total_timesteps`` and CMA-ES's evaluation count are different units.
:class:`~swat_gym.env.SwatEnv` does exactly one ``runner.run`` per step and ``evaluate`` one
per evaluation, so both convert to engine runs and both are held to ``--budget``. The counts
are then read back off :attr:`FastRunner.n_runs` and reported, so the claim is measured rather
than asserted.

What is held fixed
------------------
Prices are the 2022-24 average vector (:func:`~swat_gym.rewarders.average`), fixed for all
three experiments. Everything outside the arm sits at measured practice via ``DEFAULT_PLAN``.
For Exp 1 and 3 that pins irrigation **against the ``default`` row** — water cost is the same
constant in ``default``, ``fixed``, ``policy`` and ``frozen``, so it cannot move comparisons
among them and the unsourced ``DEFAULT_WATER`` placeholder is neutralised there. It is *not*
the same constant in ``measured``, which irrigates on its own irregular record; that is one of
the reasons ``measured`` is a context row rather than the denominator. Exp 2 has no such
protection and needs a real district rate.

Every row carries its cost decomposition
----------------------------------------
:func:`_row` keeps ``revenue`` and all four cost terms, not just their difference. Profit is
linear in every price, so a stored row can be re-priced for any input **without re-running the
engine** — which is how a contingency like "$1,038 of this headline is the arbitrary $5/Mg
manure haulage price" gets reported as a sensitivity row rather than rediscovered by a rerun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
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

from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage

ROOT = Path(__file__).resolve().parents[3]
assert_no_leakage()


def _row(d: dict, start_year: int) -> dict:
    """One window's outcome, with the profit identity kept separable — see the module docstring.

    ``revenue - water_cost - manure_cost - fert_cost - op_cost`` reconstructs ``profit``
    exactly (leaching is only in it when ``no3_price`` was set), so any of the five prices can
    be varied after the fact on a frozen plan.
    """
    return {"start_year": start_year, "profit": d["profit"],
            "revenue": d["revenue"], "water_cost": d["water_cost"],
            "manure_cost": d["manure_cost"], "fert_cost": d["fert_cost"],
            "op_cost": d["op_cost"], "n_fert_events": d["n_fert_events"],
            "irrigation_mm": d["irrigation_mm"], "manure_mg": d["manure_mg"],
            "fert_n_kg": d["fert_n_kg"], "no3": d["no3_leached_kg"]}


def paired(a: list[dict], b: list[dict]) -> dict:
    """Mean and standard error of the per-window paired difference ``a - b``.

    Paired, because both rows are scored on the **same** weather windows in the same order:
    the window-to-window spread of profit is far larger than the differences between rows, and
    an unpaired comparison would drown every result in it. Without this, a headline was a bare
    mean of 7 windows with no dispersion at all, read against a noise floor that
    :data:`~swat_gym.env.ACTION_DIM` estimates at 200-300 $/ha — so "PPO loses by 696" had no
    way to be checked.
    """
    d = np.array([r["profit"] for r in a]) - np.array([r["profit"] for r in b])
    return {"mean": float(d.mean()),
            "se": float(d.std(ddof=1) / np.sqrt(d.size)) if d.size > 1 else float("nan"),
            "n": int(d.size),
            "per_window": [round(float(v), 1) for v in d]}


# -- row 1: the human bar ------------------------------------------------------------------

def score_measured(windows, prices: Prices, no3_price: float) -> list[dict]:
    """The shipped ``management.sch``, unmodified, on each weather window.

    Only ``time.sim`` is rewritten. Nothing generates a schedule here — the point is to score
    what the growers actually did, so any plan we build would defeat the purpose.
    """
    out = []
    with FastRunner() as runner:
        for sy in windows:
            runner.run({"time.sim": time_sim(sy, N_YEARS + SPINUP)})
            out.append(_row(profit(runner, prices, no3_price=no3_price), sy))
    return out


# -- row 2: the optimized fixed schedule ---------------------------------------------------

#: Seconds between CMA-ES partial checkpoints. **Time-based, not evaluation-based.** An
#: eval-count interval sounds equivalent and is not: engine throughput on this machine swings
#: from 4.0 runs/s idle to under 2 runs/s when swap is full, so a 500-eval interval that means
#: 4 minutes on a quiet box means over half an hour on a loaded one — and a 330 s test run
#: never reached it at all. Flushing on a clock bounds the worst-case loss to this many seconds
#: no matter how slowly the engine is turning.
PARTIAL_SECONDS = 120.0


def _load_partial(path: Path | None, cfg: dict):
    """A mid-search CMA-ES checkpoint, if one exists and was produced at this configuration.

    The config guard is not optional. The partial used to carry no configuration at all, so a
    checkpoint left by a run at a different ``--max-n`` (or different prices, or a different
    arm) would be silently resumed into the current one — a search seeded from the answer to a
    different question, reported as if it were this one's.
    """
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
    """CMA-ES over the arm's free parameters, checkpointing the strategy as it goes.

    ``evals`` is the **total** budget. A resume restores the pickled
    :class:`cma.CMAEvolutionStrategy` — covariance and step size included — so it finishes at
    the same evaluation count, and in the same search state, as an uninterrupted run would.
    Checkpoints are written at generation boundaries, the only points where the strategy is
    internally consistent, and are throttled to :data:`PARTIAL_SECONDS`.
    """
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

        best, n_evals, history = minimise(score, default_free(arm), evals=evals, seed=seed,
                                          state=state, on_generation=checkpoint)
        # Engine runs spent before this process started, at one run per window per evaluation.
        n_runs = runner.n_runs + done * len(train_windows)
    return best, n_evals, n_runs, history


def score_fixed(x, arm, windows, prices, no3_price, max_n) -> list[dict]:
    vec = arm_vector(x, arm)
    with FastRunner() as runner:
        return [_row(evaluate(vec, runner, prices=prices, start_year=sy,
                              no3_price=no3_price, max_n=max_n), sy) for sy in windows]


# -- rows 3 and 4: the policy, and its own plan frozen -------------------------------------

def score_policy(model, arm, windows, prices, no3_price, max_n):
    """Held-out scores plus, per window, the concrete plan the policy chose."""
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
    """Replay one fixed plan across windows — the adaptivity control.

    The plan came out of an adaptive rollout, but here it is applied verbatim to every window
    regardless of what the weather does, so anything it scores is *not* adaptivity.
    """
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
    """Train one PPO policy at ``seed``, resuming if a checkpoint for this exact config exists.

    Every artefact is keyed by seed *and* by the config digest, so replicates never collide and
    a stale policy — one trained at a different cap, or against a different observation width —
    is never found rather than being silently loaded.
    """
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
            # gamma=1.0: the objective is *total* rotation profit over a fixed 7-year horizon,
            # so there is no reason to discount. log_std_init=-1 narrows the initial policy to
            # sigma~0.37 on a unit box; SB3's default sigma=1 explores almost entirely in the
            # clipped region.
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


# -- surviving being killed -----------------------------------------------------------------

def _stage(out: Path, name: str) -> Path:
    return out.with_name(f"{out.stem}_{name}.json")


def _water_breakeven(a: list[dict], b: list[dict], prices: Prices) -> dict:
    """Water price at which ``a``'s profit advantage over ``b`` disappears.

    Profit is linear in the water price, so the advantage at price *p* is
    ``(A - B) - p * (mm_A - mm_B)`` where A, B are profits at the scored price with its water
    term added back. The root is exact arithmetic on stored rows — no engine involved — which
    is the point: it converts a result that depends on the unsourced ``DEFAULT_WATER``
    placeholder into a statement of the form "this holds for any price below X".
    """
    adv = mean(a) - mean(b)
    dmm = float(np.mean([r["irrigation_mm"] for r in a])
                - np.mean([r["irrigation_mm"] for r in b]))
    # Advantage is flat in the water price when both rows apply the same water.
    if abs(dmm) < 1e-9:
        return {"scored_price": prices.water, "delta_mm": dmm, "breakeven": None,
                "note": "advantage does not depend on the water price"}
    return {"scored_price": prices.water, "delta_mm": dmm,
            "breakeven": float(prices.water + adv / dmm),
            "note": "advantage vanishes at this $/mm/ha; sign of delta_mm gives the direction"}


def _cfg_key(cfg: dict) -> str:
    """Short stable digest of a run configuration, for keying artefacts by path."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]


def _load_stage(out: Path, name: str, cfg: dict):
    """A completed stage's payload, if it exists and was produced at this configuration."""
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


# -- the experiment ------------------------------------------------------------------------

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
    ap.add_argument("--max-n", type=float, default=MAX_N_LOADING,
                    help="N loading cap kg N/ha/yr; 0 or negative disables it entirely")
    ap.add_argument("--out", type=Path, default=out_path)
    args = ap.parse_args(argv)

    prices = average()
    # A non-positive cap means "no cap", which is how the {400, uncapped} sweep asks whether
    # MAX_N_LOADING was ever binding rather than just being the number we happened to report.
    max_n = args.max_n if args.max_n > 0 else None
    t0 = time.time()

    if args.fixed_windows <= 0 or args.fixed_windows >= len(TRAIN_YEARS):
        fixed_windows = list(TRAIN_YEARS)
    else:
        sub = list(np.linspace(0, len(TRAIN_YEARS) - 1, args.fixed_windows).round().astype(int))
        fixed_windows = [TRAIN_YEARS[i] for i in sorted(set(sub))]
    # One CMA-ES evaluation costs one engine run per training window, so the budget converts
    # to evaluations by dividing. PPO takes the budget directly, one run per timestep.
    evals = max(1, args.budget // len(fixed_windows))
    print(f"arm={arm}  prices={prices.label}  budget={args.budget} engine runs  "
          f"cap={'none' if max_n is None else f'{max_n:g}'} kg N/ha\n"
          f"fixed-schedule windows: {fixed_windows}  -> {evals} CMA-ES evals", flush=True)

    # Every stage checkpoints. This machine sits at ~85 MB free RAM with swap effectively
    # full, and jetsam has already killed two multi-hour runs outright — so the run is broken
    # into resumable stages rather than one all-or-nothing block.
    # The environment's own semantics are in the key, not just the experiment's arguments. A
    # checkpoint is only reusable if the env that produced it is the env now running, and the
    # three changes this round — the irrigation efficiency, the recalibrated default depth, and
    # the widened observation — are each invisible in the argument list. `obs_dim` in particular
    # must be here: a stale PPO policy with a 7-wide input silently loads against an 11-wide
    # space. Keying on the values themselves means no one has to remember to bump a revision.
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

    # The like-for-like control: DEFAULT_PLAN through the same generator the arms use, so the
    # only thing separating it from `fixed` is the arm's own dimensions. Two engine runs per
    # window, and it is the row the lever's gain should actually be quoted against.
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

    stage = _load_stage(args.out, "fixed", cfg)
    if stage is None:
        # Resume from a partial if a previous attempt was killed mid-search. `evals` is the
        # total, and optimize_fixed subtracts whatever the checkpoint already spent.
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
    # Seeds share one CMA-ES row on purpose. The baseline is a near-deterministic search over a
    # fixed objective; the policy is the stochastic half, and it is the half whose null the
    # experiment reports. Replicating only PPO buys the variance estimate that matters at one
    # PPO stage per seed instead of a whole run per seed.
    seeds = [args.seed + 100 * i for i in range(max(1, args.ppo_seeds))]
    models = {s: train_policy(arm, args, cfg, prices, max_n, s) for s in seeds}
    t_rl = time.time() - t1

    fixed_test = score_fixed(x, arm, TEST_YEARS, prices, args.no3_price, max_n)
    fixed_train = score_fixed(x, arm, fixed_windows, prices, args.no3_price, max_n)

    # Frozen plan is selected on **training** windows, then that single plan is scored on
    # test. Selecting the best of N candidates on the test set itself biased adaptivity
    # negative by construction (expected max of N noisy estimates).
    per_seed = {}
    for s, model in models.items():
        p_test, p_plans = score_policy(model, arm, TEST_YEARS, prices, args.no3_price, max_n)
        p_train, p_plans_train = score_policy(model, arm, fixed_windows, prices,
                                              args.no3_price, max_n)
        # Score each train-emitted plan on the train set; pick the best train mean.
        fz_train = {sy: score_plan(pl, fixed_windows, prices, args.no3_price)
                    for sy, pl in p_plans_train.items()}
        fz_train_means = {sy: mean(rows) for sy, rows in fz_train.items()}
        bf = max(fz_train_means, key=fz_train_means.get)
        # Replay the train-selected plan on test (and keep the full test distribution too).
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
        """Mean and standard error of ``k`` across seeds — the seed-variance estimate."""
        v = np.array([per_seed[s][k] for s in seeds])
        return {"mean": float(v.mean()),
                "se": float(v.std(ddof=1) / np.sqrt(v.size)) if v.size > 1 else float("nan"),
                "by_seed": {str(s): float(per_seed[s][k]) for s in seeds}}

    seed_stats = {k: across(k) for k in
                  ("policy_test", "frozen_best_test", "adv", "adaptivity_value")}

    # The representative seed for the detailed rows is the *median* performer, not the best:
    # reporting the best of N seeds is the selection bias a seed study exists to remove.
    rep = sorted(seeds, key=lambda s: per_seed[s]["policy_test"])[len(seeds) // 2]
    r = per_seed[rep]
    policy_test, policy_train, plans = r["test"], r["train"], r["plans"]
    frozen, frozen_means, best_frozen = r["frozen"], r["frozen_means"], r["best_frozen"]

    adv = mean(policy_test) - mean(fixed_test)
    # What adaptivity is worth, in dollars: the policy against its own plan frozen. Negative
    # means the policy would have done better committing to a constant schedule in advance.
    adaptivity_value = mean(policy_test) - frozen_means[best_frozen]
    # The *share* of the policy's edge attributable to adaptivity — defined only when there is
    # an edge to apportion. Reporting it unconditionally was a sign trap: with the policy
    # 664 $/ha behind CMA-ES and 115 behind its own frozen plan, both numerator and denominator
    # go negative and the ratio comes back "+17 % attributable to adaptivity", which reads as a
    # positive finding about the exact quantity it is refuting. `adaptivity_value` is the
    # number to report; the share is None when the premise for it does not hold.
    adaptivity_share = (adaptivity_value / adv) if adv > 0 else None

    summary = {
        "arm": arm, "prices": prices.label, "budget_engine_runs": args.budget,
        "max_n": max_n, "fert_op": prices.fert_op,
        "train_years": TRAIN_YEARS, "test_years": TEST_YEARS,
        "fixed_windows": fixed_windows,
        "cma_evals": n_evals, "cma_engine_runs": fixed_runs, "ppo_timesteps": args.budget,
        "cma_history": cma_history,
        "frozen_selection": "train",
        "seconds": {"fixed": round(t_fixed, 1), "rl": round(t_rl, 1),
                    "total": round(time.time() - t0, 1)},
        "mean_profit": {
            "measured_train": mean(measured_train), "measured_test": mean(measured_test),
            "default_train": mean(default_train), "default_test": mean(default_test),
            "fixed_train": mean(fixed_train), "fixed_test": mean(fixed_test),
            "policy_train": mean(policy_train), "policy_test": mean(policy_test),
            "frozen_best_test": frozen_means[best_frozen],
        },
        # `vs_default` is the lever's attributable gain — same generator, same irrigation, same
        # everything but the arm. `vs_measured` mixes that with the generator gap and is kept
        # as the realism check, not as the headline.
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
        # Every comparison with its per-window spread, so a difference can be read against the
        # noise instead of being quoted bare.
        "paired_test": {
            "default_vs_measured": paired(default_test, measured_test),
            "fixed_vs_default": paired(fixed_test, default_test),
            "fixed_vs_measured": paired(fixed_test, measured_test),
            "policy_vs_default": paired(policy_test, default_test),
            "policy_vs_fixed": paired(policy_test, fixed_test),
            "frozen_vs_policy": paired(frozen[best_frozen], policy_test),
        },
        "advantage_over_fixed": adv,
        "adaptivity_value": adaptivity_value,
        "adaptivity_share": adaptivity_share,
        "ppo_seeds": seeds, "representative_seed": rep, "across_seeds": seed_stats,
        # Profit is linear in every price, so the water price at which the policy's advantage
        # vanishes is arithmetic on stored rows rather than a rerun. Reporting the breakeven is
        # what lets an unsourced placeholder (DEFAULT_WATER) stop being load-bearing.
        "water_breakeven": _water_breakeven(policy_test, fixed_test, prices),
        "best_frozen_window": best_frozen,
        "frozen_means": {str(k): v for k, v in frozen_means.items()},
        "per_window": {"measured_test": measured_test, "default_test": default_test,
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
    print(f"{'measured practice':<26}{m['measured_train']:>10.0f}{m['measured_test']:>11.0f}"
          f"{'—':>12}{'—':>11}")
    print(f"{'DEFAULT_PLAN baseline':<26}{m['default_train']:>10.0f}{m['default_test']:>11.0f}"
          f"{'—':>12}{v['default']:>+11.0f}")
    print(f"{'CMA-ES fixed schedule':<26}{m['fixed_train']:>10.0f}{m['fixed_test']:>11.0f}"
          f"{vd['fixed']:>+12.0f}{v['fixed']:>+11.0f}")
    print(f"{'PPO policy':<26}{m['policy_train']:>10.0f}{m['policy_test']:>11.0f}"
          f"{vd['policy']:>+12.0f}{v['policy']:>+11.0f}")
    print(f"{'  its own plan, frozen':<26}{'':>10}{m['frozen_best_test']:>11.0f}"
          f"{vd['frozen']:>+12.0f}{v['frozen']:>+11.0f}")

    # Paired across the same held-out windows, so these standard errors are the ones that
    # decide whether any of the differences above are real.
    print(f"\n{'paired held-out differences':<30}{'mean':>10}{'± s.e.':>10}")
    for name, p in summary["paired_test"].items():
        print(f"{name:<30}{p['mean']:>+10.0f}{p['se']:>10.0f}")
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
