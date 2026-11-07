"""Algorithm comparison on Exp 3 (irrigation), one strategy, one efficiency case
(swat_gym.ltm.algos): ES, GA, PPO and SAC closed loop; CMA-ES, GA and random search open loop;
``--seeds`` seeds each at ``--budget`` HRU-episode steps, selected on train, scored on test.

Per algorithm and seed, on the test windows: the strategy score, ry, profit and every term;
paired differences (stats.paired, ESS intervals; rule 7) against measured practice, default,
auto-irrigation and the same-seed CMA-ES plan; for closed-loop policies also against their
own frozen plan (adaptivity) and the spread of their schedules across test windows.

    uv run python -m swat_gym.experiments.ltm_algos                     # balanced, 0.80, 300k x 4
    SMOKE=1 uv run python -m swat_gym.experiments.ltm_algos             # tiny budgets, 1 seed
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time

import numpy as np

from ..fastrunner import model_hash
from ..ltm import algos as A
from ..ltm import econ, practice
from ..ltm.env import plan_from_x
from ..ltm.es import ES
from ..ltm.practice import BASE_IRR_EFF, TXTINOUT, decisions, measured_x
from ..ltm.render import EpisodePlan
from ..ltm.score import STRATEGIES, Reference, relative_yield
from ..ltm.windows import TEST, TEST_ESS, TRAIN, TRAIN_ESS
from . import ltm as L
from .common import load_stage, save_stage

LEVER = "I"
#: rough cost order, longest first, so the last jobs to start are short
ORDER = ("sac", "ppo", "es", "ga", "cma", "ga_open", "random")


def references(prices, tag: str):
    """The Exp 3 measured / default / auto runs (reused from runs/<tag>/reference.json when its
    config matches experiments.ltm's) and the strategy Reference."""
    base_cfg = {"lever": LEVER, "ltm_version": L.LTM_VERSION, "model": model_hash(TXTINOUT),
                "prices": prices.key(), "train": TRAIN, "test": TEST,
                "decisions": len(decisions(LEVER)), "es": ES, "practice": L.practice_key(LEVER)}
    cfg = {**base_cfg, "stage": "reference"}
    path = L.OUT / tag / "reference.json"
    rs = load_stage(path, cfg)
    if rs is None:
        both = TRAIN + TEST
        rs = {"measured": L.run_plans([EpisodePlan()], both, prices)[0],
              "default": L.run_plans([plan_from_x(LEVER, measured_x(LEVER))], both, prices)[0],
              "auto": L.run_plans([EpisodePlan(irr_auto=True)], both, prices)[0]}
        save_stage(path, cfg, rs)
    n = len(TRAIN)
    crop_ref = L.crop_reference(prices)
    floor = float(np.mean([relative_yield(e, crop_ref) for e in rs["default"][:n]]))
    return base_cfg, rs, Reference.from_episodes(rs["measured"][:n], crop_ref, floor=floor)


def main(argv=None) -> dict:
    smoke = os.environ.get("SMOKE") == "1"
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=13_000 if smoke else 645_000)  # 300k x 15/7 train windows (2026-11-04)
    ap.add_argument("--seeds", type=int, default=1 if smoke else 4)
    ap.add_argument("--algos", nargs="*", default=list(ORDER))
    ap.add_argument("--strategy", default="balanced", choices=list(STRATEGIES))
    ap.add_argument("--irr-eff", type=float, default=BASE_IRR_EFF)
    ap.add_argument("--procs", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args(argv)
    practice.set_irr_eff(args.irr_eff)
    eff_tag = "" if abs(args.irr_eff - BASE_IRR_EFF) < 1e-9 else f"_eff{round(args.irr_eff * 100):02d}"
    tag = f"ltm_algos{eff_tag}_{args.strategy}" + ("_smoke" if smoke else "")
    stage_dir = L.OUT / tag
    stage_dir.mkdir(parents=True, exist_ok=True)
    prices = econ.prices()
    w = STRATEGIES[args.strategy]
    t0 = time.time()
    base_cfg, rs, ref = references(prices, f"ltm_exp3{eff_tag}")

    seeds = [100 * i for i in range(args.seeds)]
    records, todo = {}, []
    for algo in sorted(args.algos, key=ORDER.index):
        for sd in seeds:
            cfg = {**base_cfg, "stage": "algo", "algo": algo, "budget": args.budget, "seed": sd,
                   "strategy": args.strategy, "algos": A.CONFIG, "reference": ref.key()}
            path = stage_dir / f"{algo}_s{sd}.json"
            done = load_stage(path, cfg)
            if done is None:
                todo.append(((algo, LEVER, w, prices, ref.key(), args.budget, sd), cfg, path))
            else:
                records[(algo, sd)] = done
    failed = {}
    if todo:
        print(f"{len(todo)} jobs on {min(args.procs, len(todo))} processes", flush=True)
        with mp.get_context("spawn").Pool(min(args.procs, len(todo)), maxtasksperchild=1) as pool:
            for (job, cfg, path), rec in zip(todo, pool.imap(A.run_job, [t[0] for t in todo])):
                key = (job[0], job[-1])
                if "error" in rec:
                    failed[f"{key[0]}_s{key[1]}"] = rec["error"]
                    print(f"  FAILED {key}:\n{rec['error']}", flush=True)
                    continue
                save_stage(path, cfg, rec)
                records[key] = rec
                print(f"  {key[0]} seed {key[1]}: train {rec['picked_train_score']:.3f}, "
                      f"{rec['hru_runs']:,} HRU runs, {rec['seconds'] / 60:.0f} min "
                      f"({time.strftime('%H:%M')})", flush=True)
            pool.close()
            pool.join()

    # -- comparisons on test ----------------------------------------------------------------
    n = len(TRAIN)
    arms = {k: L._with_score(rs[k][n:], ref, w) for k in ("measured", "default", "auto")}
    out = {"config": {**base_cfg, "budget": args.budget, "seeds": seeds, "strategy": args.strategy,
                      "w": w, "irr_eff": args.irr_eff, "algos": A.CONFIG, "train_ess": TRAIN_ESS,
                      "test_ess": TEST_ESS, "reference": ref.key()},
           "baselines": {k: {m: float(np.mean([e[m] for e in v])) for m in L.REPORTED}
                         for k, v in arms.items()},
           "baseline_x": list(map(float, measured_x(LEVER))), "algos": {}, "failed": failed}
    cma = {sd: L._with_score(records[("cma", sd)]["test"], ref, w)
           for sd in seeds if ("cma", sd) in records}
    frozen_runs = []
    for (algo, sd), rec in records.items():
        if algo in A.CLOSED:
            frozen_runs.append((algo, sd, L.frozen_plan(LEVER, rec["train"])))
    frozen_eps = dict(zip([(a, s) for a, s, _ in frozen_runs],
                          L.run_plans([p for _, _, p in frozen_runs], TEST, prices))) if frozen_runs else {}
    for (algo, sd), rec in sorted(records.items(), key=lambda kv: (ORDER.index(kv[0][0]), kv[0][1])):
        test = L._with_score(rec["test"], ref, w)
        row = {"seed": sd, "seconds": rec["seconds"], "hru_runs": rec["hru_runs"],
               "picked_train_score": rec["picked_train_score"], "curve": rec["curve"],
               "test_means": {m: float(np.mean([e[m] for e in test])) for m in L.REPORTED},
               "test_x": {str(e["start"]): e["x"] for e in rec["test"]},
               "vs_measured": L.compare(test, arms["measured"]),
               "vs_default": L.compare(test, arms["default"]),
               "vs_auto": L.compare(test, arms["auto"])}
        if sd in cma and algo != "cma":
            row["vs_cma_same_seed"] = L.compare(test, cma[sd])
        if (algo, sd) in frozen_eps:
            fz = L._with_score(frozen_eps[(algo, sd)], ref, w)
            row["adaptivity"] = L.compare(test, fz)
            row["frozen_test_means"] = {m: float(np.mean([e[m] for e in fz])) for m in L.REPORTED}
            xs = np.array([e["x"] for e in rec["test"]])
            row["x_spread_across_test_windows"] = float(xs.std(0).mean())
        for k in ("generations", "evals", "episode_curve"):
            if k in rec:
                row[k] = rec[k]
        out["algos"].setdefault(algo, []).append(row)
    out["wall_s"] = time.time() - t0
    (L.OUT / f"{tag}.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(f"wrote runs/{tag}.json ({out['wall_s'] / 60:.1f} min)", flush=True)
    return out


if __name__ == "__main__":
    main()
