"""Experiment 1c -- how fine a nitrogen cadence is actually worth paying for?

This is a **diagnostic, not a headline**. It exists because the plan was about to commit to
monthly decision cadence -- a large refactor plus a ~13 h matched-budget RL run -- on the
assumption that splitting nitrogen finely pays. That assumption is testable in about an hour
with no RL at all, and the paper the idea came from does not support it: CyclesGym 2.0's own
Table 1 puts a 4-way split at **$933.2/acre against $933.8** for one application at planting,
i.e. slightly *worse* on profit, and its §3.2 claim of "8 % yield improvement" is 1.5 % in its
own numbers (200.9 vs 198.0 bu/acre).

So: optimize a *fixed* mineral-N program at each cadence k = 1..7 and read the knee off the
curve. Build RL only at the cadence where splitting has already earned its keep.

Constant dimensionality is the whole design
-------------------------------------------
Every arm is parameterised identically -- **(total N, start month, interval) per year, 21
parameters at every k** -- with the total split into k *equal* doses. The obvious alternative,
a free rate per decision month, would give k=7 a 49-parameter search and k=1 a 14-parameter
one, and CMA-ES under-converging at high k would manufacture the "fine cadence adds nothing"
answer this is supposed to be testing. Equal doses is a restriction, but it is the standard
agronomic program and it is *the same* restriction at every k, so the comparison stays fair.

One honest wrinkle: the *nominal* parameter count is 21 everywhere, but the **effective** count
falls as k rises, because k applications need ``(k-1) * interval`` months of room inside a
7-month window -- at k=7 the interval is forced to 1 and `start` to April, so two of the three
per-year parameters go inert. That biases any residual optimisation difficulty *toward* high k
(a smaller effective space is easier to search), which is the safe direction here: it cannot
manufacture a false "fine cadence does not pay".

Two scoping choices
-------------------
**Manure is pinned at zero.** The cadence question is about splitting *mineral* N; today's
matched-budget run (`runs/exp1_nitrogen.json`) already settled the manure/mineral mix. Leaving
manure free would also eat the entire :data:`MAX_N_LOADING` budget -- 45 Mg/ha of gn2013 is
585 kg N, above the cap on its own -- leaving no headroom for the mineral program to vary in.

**These arms are compared to each other, not to the human bar.** Measured practice is
manure-only, so it is not the right comparator for a mineral-cadence curve. The human number
belongs to Exp 1, where the levers match.

    uv run python -m swat_gym.experiments.exp1c_cadence --evals 4000
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from ..constrainers import MAX_N_LOADING, repair, violations
from ..env import N_YEARS, SPINUP, time_sim
from ..fastrunner import FastRunner
from ..rewarders import Prices, average, profit
from ..schedule import CROPS, YearAction, _doy, _md, build
from ._optimize import minimise

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "exp1c_cadence.json"

#: Months in which an application is agronomically live at this site. April-October: outside
#: it the ground is frozen and there is no crop, so a decision there could only be a no-op.
DECISION_MONTHS = (4, 5, 6, 7, 8, 9, 10)

#: Cadences swept. k is the number of equal mineral-N applications per year.
CADENCES = (1, 2, 3, 4, 5, 6, 7)

#: The measured rotation, held fixed -- this experiment is not about crop choice.
ROTATION = ("corn", "barl", "alfa", "alfa", "alfa", "corn", "barl")

#: Per-year free parameters: total N, first application month, months between applications.
PARAMS_PER_YEAR = 3
_TOTAL_N = (0.0, MAX_N_LOADING)
_START = (float(DECISION_MONTHS[0]), float(DECISION_MONTHS[-1]))
_INTERVAL = (1.0, 3.0)

TRAIN_WINDOWS = (1995, 2000, 2004, 2009)
TEST_WINDOWS = (2012, 2013, 2014, 2015, 2016, 2017, 2018)


def _lerp(x: float, lo: float, hi: float) -> float:
    return lo + float(np.clip(x, 0.0, 1.0)) * (hi - lo)


def decode(flat, k: int, *, max_n: float | None = MAX_N_LOADING) -> list[YearAction]:
    """(21 params, cadence k) -> a feasible 7-year plan with k equal doses per year."""
    a = np.asarray(flat, dtype=float).reshape(N_YEARS, PARAMS_PER_YEAR)
    plan = []
    for i, crop in enumerate(ROTATION):
        total = _lerp(a[i, 0], *_TOTAL_N)
        start = int(round(_lerp(a[i, 1], *_START)))
        interval = int(round(_lerp(a[i, 2], *_INTERVAL)))
        # Fit the program inside the decision window by squeezing the *interval* first and
        # then pulling `start` back -- never by dropping an application, which would change k
        # and make the arms incomparable. k applications need (k-1)*interval months of room,
        # so at k=7 in a 7-month window the only layout is monthly, and `interval` is forced.
        first, last = DECISION_MONTHS[0], DECISION_MONTHS[-1]
        if k > 1:
            interval = max(1, min(interval, (last - first) // (k - 1)))
        start = min(max(start, first), last - (k - 1) * interval)
        months = [start + j * interval for j in range(k)]
        # fert_splits is day-of-year keyed; a monthly program lands on the 1st.
        splits = tuple((_doy(m, 1), total / k) for m in months)
        plan.append(YearAction(crop=crop, manure_mg=0.0, fert_splits=splits,
                               irr_start_doy=130, irr_interval=7, irr_depth=30.0))
    return repair(plan, max_n=max_n)


def _edits(plan, start_year: int) -> dict[str, str]:
    e = build(plan)
    e["time.sim"] = time_sim(start_year, len(plan) + SPINUP)
    return e


def score(plan, windows, runner, prices: Prices) -> dict:
    rows = []
    for sy in windows:
        runner.run(_edits(plan, sy))
        rows.append(profit(runner, prices))
    return {
        "profit": float(np.mean([r["profit"] for r in rows])),
        "n_kg": float(np.mean([r["fert_n_kg"] for r in rows])),
        "events": float(np.mean([r["n_fert_events"] for r in rows])),
        "op_cost": float(np.mean([r["op_cost"] for r in rows])),
        "no3": float(np.mean([r["no3_leached_kg"] for r in rows])),
        "per_window": [{"start_year": sy, "profit": r["profit"]}
                       for sy, r in zip(windows, rows)],
    }


#: Seconds between partial checkpoints. Time-based rather than evaluation-based: throughput
#: per worker ranges from ~4 runs/s idle to under 2 when the machine is swapping, so an
#: eval-count interval gives an unpredictable loss bound. ``--salvage`` turns these into a
#: usable curve.
PARTIAL_SECONDS = 120.0


def run_arm(k: int, evals: int, seed: int, max_n: float | None, fert_op: float,
            partial_path: Path | None = None) -> dict:
    prices = average(fert_op=fert_op)
    t0 = time.time()
    with FastRunner() as runner:
        state = {"n": 0, "best_f": float("inf"), "best_x": None, "flushed": time.time()}

        def objective(free):
            plan = decode(free, k, max_n=max_n)
            total = 0.0
            for sy in TRAIN_WINDOWS:
                try:
                    runner.run(_edits(plan, sy))
                    total += profit(runner, prices)["profit"]
                except Exception:
                    return 1e9
            f = -total / len(TRAIN_WINDOWS)

            state["n"] += 1
            if f < state["best_f"]:
                state["best_f"], state["best_x"] = f, np.asarray(free).copy()
            now = time.time()
            if partial_path is not None and now - state["flushed"] >= PARTIAL_SECONDS:
                state["flushed"] = now
                partial_path.write_text(json.dumps({
                    "k": k, "partial": True, "evals": state["n"],
                    "train_obj": -state["best_f"],
                    "x": list(map(float, state["best_x"])),
                }))
            return f

        x0 = np.full(N_YEARS * PARAMS_PER_YEAR, 0.5)
        best, n_evals, _ = minimise(objective, x0, evals=evals, seed=seed)
        plan = decode(best, k, max_n=max_n)
        train = score(plan, TRAIN_WINDOWS, runner, prices)
        test = score(plan, TEST_WINDOWS, runner, prices)
        runs = runner.n_runs

    return {
        "k": k, "evals": n_evals, "engine_runs": runs, "seconds": round(time.time() - t0, 1),
        "train_profit": train["profit"], "test_profit": test["profit"],
        "n_kg": test["n_kg"], "events": test["events"], "op_cost": test["op_cost"],
        "no3": test["no3"],
        "infeasible": violations(plan, max_n=max_n),
        # Reported as (month, kg) for readability; fert_splits stores day-of-year.
        "plan": [(a.crop, [(_md(d)[0], round(kg, 1)) for d, kg in a.fert_splits])
                 for a in plan],
        "x": list(map(float, best)),
        "per_window_test": test["per_window"],
    }


def _arm_path(out: Path, k: int) -> Path:
    return out.with_name(f"{out.stem}_k{k}.json")


def _partial_path(out: Path, k: int) -> Path:
    return out.with_name(f"{out.stem}_k{k}.partial.json")


def salvage(out: Path, max_n: float | None, fert_op: float) -> list[dict]:
    """Score whatever partial checkpoints exist into a curve, each flagged ``partial``.

    An under-converged curve that says something is worth more than a converged one that was
    never written. Every row carries its own evaluation count so an arm that got half the
    search of its neighbours cannot be read as a like-for-like comparison.
    """
    prices = average(fert_op=fert_op)
    arms = []
    with FastRunner() as runner:
        for k in CADENCES:
            p = _partial_path(out, k)
            if not p.is_file():
                continue
            d = json.loads(p.read_text())
            plan = decode(d["x"], k, max_n=max_n)
            train = score(plan, TRAIN_WINDOWS, runner, prices)
            test = score(plan, TEST_WINDOWS, runner, prices)
            arms.append({
                "k": k, "partial": True, "evals": d["evals"], "engine_runs": None,
                "seconds": None, "train_profit": train["profit"],
                "test_profit": test["profit"], "n_kg": test["n_kg"],
                "events": test["events"], "op_cost": test["op_cost"], "no3": test["no3"],
                "infeasible": violations(plan, max_n=max_n),
                "plan": [(a.crop, [(_md(d)[0], round(kg, 1)) for d, kg in a.fert_splits])
                         for a in plan],
                "x": d["x"], "per_window_test": test["per_window"],
            })
    return arms


def _load_arm(out: Path, k: int, cfg: dict) -> dict | None:
    """A previously completed arm, if one exists **and was run at this configuration**.

    Each arm is checkpointed the moment it finishes, because these runs take an hour and the
    first attempt was interrupted after collecting nothing -- results were only gathered at the
    end. The config is stored alongside and compared so a resumed sweep can never silently mix
    arms optimised under a different cap, pass cost or evaluation budget.
    """
    p = _arm_path(out, k)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if d.get("config") != cfg:
        print(f"  k={k}: ignoring checkpoint, config differs", flush=True)
        return None
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", type=int, default=4000, help="CMA-ES evaluations per arm")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-n", type=float, default=MAX_N_LOADING,
                    help="N loading cap, kg N/ha/yr; pass a huge value to effectively disable")
    ap.add_argument("--fert-op", type=float, default=None,
                    help="$/ha per application pass (default: rewarders.DEFAULT_FERT_OP)")
    ap.add_argument("--workers", type=int, default=len(CADENCES))
    ap.add_argument("--salvage", action="store_true",
                    help="score existing partial checkpoints instead of optimising")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    fert_op = average().fert_op if args.fert_op is None else args.fert_op
    print(f"cadence sweep k={CADENCES}  {args.evals} evals/arm  "
          f"cap={args.max_n:g} kg N/ha  pass cost=${fert_op:g}/ha", flush=True)

    cfg = {"evals": args.evals, "seed": args.seed, "max_n": args.max_n, "fert_op": fert_op}
    # Before the first checkpoint write, not at the end — the whole point is surviving a stop.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    done: dict[int, dict] = {}
    for k in CADENCES:
        cached = _load_arm(args.out, k, cfg)
        if cached is not None:
            done[k] = cached
            print(f"  k={k}: resumed from checkpoint "
                  f"({cached['test_profit']:.0f} $/ha)", flush=True)

    if args.salvage:
        for arm in salvage(args.out, args.max_n, fert_op):
            done[arm["k"]] = arm
            print(f"  k={arm['k']}: salvaged at {arm['evals']} evals "
                  f"({arm['test_profit']:.0f} $/ha)", flush=True)
        if not done:
            raise SystemExit("no checkpoints or partials found to salvage")

    todo = [] if args.salvage else [k for k in CADENCES if k not in done]
    if todo:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_arm, k, args.evals, args.seed, args.max_n, fert_op,
                              _partial_path(args.out, k)): k
                    for k in todo}
            for fut in as_completed(futs):
                k = futs[fut]
                arm = fut.result()
                arm["config"] = cfg
                _arm_path(args.out, k).write_text(json.dumps(arm, indent=2))
                done[k] = arm
                print(f"  k={k}: {arm['test_profit']:.0f} $/ha, "
                      f"{arm['evals']} evals, {arm['seconds']:.0f}s "
                      f"[{len(done)}/{len(CADENCES)}]", flush=True)

    # Tolerant of gaps: a salvaged sweep may be missing arms, and a partial curve that is
    # honest about which arms are absent beats refusing to report one at all.
    arms = [done[k] for k in CADENCES if k in done]
    missing = [k for k in CADENCES if k not in done]
    any_partial = any(a.get("partial") for a in arms)
    best = max(arms, key=lambda a: a["test_profit"])
    # The knee: the smallest cadence within $50/ha of the best. Paying for extra passes to
    # chase less than that is not a result, it is noise with a tractor attached.
    knee = min((a for a in arms if a["test_profit"] >= best["test_profit"] - 50.0),
               key=lambda a: a["k"])

    summary = {
        "cadences": list(CADENCES), "evals_per_arm": args.evals,
        "max_n": args.max_n, "fert_op": fert_op, "prices": average().label,
        "decision_months": list(DECISION_MONTHS), "rotation": list(ROTATION),
        "params_per_arm": N_YEARS * PARAMS_PER_YEAR,
        "train_windows": list(TRAIN_WINDOWS), "test_windows": list(TEST_WINDOWS),
        "seconds_total": round(time.time() - t0, 1),
        "best_k": best["k"], "knee_k": knee["k"],
        "gain_base_to_best": best["test_profit"] - arms[0]["test_profit"],
        "base_k": arms[0]["k"],
        "missing_arms": missing,
        "any_partial": any_partial,
        "arms": arms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    base_k = arms[0]["k"]
    print(f"\n{'k':>3}{'held-out $/ha':>15}{f'vs k={base_k}':>10}{'N kg':>9}"
          f"{'passes':>8}{'pass $':>8}{'NO3':>7}{'evals':>8}  ")
    base = arms[0]["test_profit"]
    for a in arms:
        print(f"{a['k']:>3}{a['test_profit']:>15.0f}{a['test_profit'] - base:>+10.0f}"
              f"{a['n_kg']:>9.0f}{a['events']:>8.1f}{a['op_cost']:>8.0f}"
              f"{a['no3']:>7.1f}{a['evals']:>8}"
              f"{'  PARTIAL' if a.get('partial') else ''}")
    if missing:
        print(f"\nMISSING ARMS: k={missing} — curve is incomplete")
    if any_partial:
        print("PARTIAL arms are under-converged; evaluation counts differ, so the rows "
              "are not strictly like-for-like")
    print(f"\nbest k={best['k']} ({best['test_profit']:.0f} $/ha); "
          f"knee k={knee['k']} (within $50/ha of best)")
    print(f"total gain from k={base_k} to k={best['k']}: "
          f"{summary['gain_base_to_best']:+.0f} $/ha "
          f"({100 * summary['gain_base_to_best'] / abs(base):+.2f} %)")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
