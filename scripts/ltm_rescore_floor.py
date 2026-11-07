"""Rescore the sustainability strategy with a per-window yield floor (user decision 2026-11-05).

The experiments' floor is default practice's train-mean relative yield (score.FLOOR_PENALTY).
On the v7 windows the test years (2003-2017) yield ~7 % less than the train years (1979-2001)
under every practice, so that floor binds on test even for measured practice and the penalty
dominates the score. Here an episode's floor is default practice's relative yield in the SAME
weather window (default never pays a penalty); everything else in the score is unchanged.

Not retrained: ES and the CMA-ES fixed plans were optimised on train under the train-mean
floor; this rescores their test episodes. Exp 1's fixed rotation is reselected on train under
the new floor (its candidates' train episodes are stored). Fixed and frozen plans are
re-simulated on test (the experiment reports do not store those episodes).

    uv run python scripts/ltm_rescore_floor.py        # -> runs/ltm_exp<n>[_effNN]_floorwin.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swat_gym.experiments import ltm as L  # noqa: E402
from swat_gym.ltm import econ, practice  # noqa: E402
from swat_gym.ltm.env import plan_from_x  # noqa: E402
from swat_gym.ltm.render import EpisodePlan  # noqa: E402
from swat_gym.ltm.score import FLOOR_PENALTY, STRATEGIES, TERMS, Reference, relative_yield  # noqa: E402
from swat_gym.ltm.windows import TEST, TRAIN  # noqa: E402

OUT = ROOT / "runs"
JOBS = (("ltm_exp1", "R", 0.80), ("ltm_exp2", "N", 0.80), ("ltm_exp3", "I", 0.80),
        ("ltm_exp3_eff55", "I", 0.55), ("ltm_exp3_eff90", "I", 0.90))
S = "sustainability"
W = STRATEGIES[S]


class WindowFloorRef(Reference):
    """Reference whose sustainability floor is default practice's ry in the episode's window."""

    def __init__(self, key: dict, floors: dict[int, float]):
        super().__init__(key["ry"], key["terms"], key["crop_ref"], None)
        self.floors = floors

    def score(self, ep: dict, w: float) -> float:
        s = super().score(ep, w)
        ry, fl = self.ry_of(ep), self.floors[int(ep["start"])]
        if w == 0.0 and ry < fl:
            s -= FLOOR_PENALTY * (fl - ry) / self.ry
        return s

    def penalty(self, ep: dict) -> float:
        return max(0.0, FLOOR_PENALTY * (self.floors[int(ep["start"])] - self.ry_of(ep)) / self.ry)


def stage(tag: str, name: str) -> dict:
    return json.loads((OUT / tag / name).read_text())["result"]


def parts(eps: list[dict], ref: WindowFloorRef) -> dict:
    """Mean environmental part and floor penalty (score = -env - penalty at w = 0)."""
    return {"env": float(np.mean([np.mean([e[k] / ref.terms[k] for k in TERMS]) for e in eps])),
            "penalty": float(np.mean([ref.penalty(e) for e in eps]))}


def rescore(tag: str, lever: str, eff: float, prices) -> dict:
    practice.set_irr_eff(eff)
    report = json.loads((OUT / f"{tag}.json").read_text())
    key = report["config"]["reference"]
    ref_stage = stage(tag, "reference.json")
    floors = {int(e["start"]): relative_yield(e, key["crop_ref"]) for e in ref_stage["default"]}
    ref = WindowFloorRef(key, floors)
    n_tr = len(TRAIN)
    assert [e["start"] for e in ref_stage["default"][n_tr:]] == TEST

    if lever == "R":
        cyc = stage(tag, "cycles.json")
        means = [float(np.mean([ref.score(e, W) for e in row])) for row in cyc["train"]]
        order = np.argsort(means)[::-1]
        fixed = {"crops": cyc["crops"][int(order[0])], "n_candidates": len(means),
                 "train_score": means[int(order[0])],
                 "top10": [[cyc["crops"][int(i)], means[int(i)]] for i in order[:10]],
                 "train_mean_floor_pick": report["strategies"][S]["fixed"]["crops"]}
        fixed_plan = EpisodePlan(crops=tuple(fixed["crops"]), irr_auto=True)
    else:
        fixed = {k: v for k, v in stage(tag, f"fixed_{S}.json").items() if k != "history"}
        fixed_plan = plan_from_x(lever, np.asarray(fixed["x"]))

    seeds = [int(s) for s in report["strategies"][S]["es"]]
    es = {sd: stage(tag, f"es_{S}_s{sd}.json") for sd in seeds}
    fz_plans = [L.frozen_plan(lever, es[sd]["train"]) for sd in seeds]
    sims = L.run_plans([fixed_plan] + fz_plans, TEST, prices)

    sc = lambda eps: L._with_score(eps, ref, W)  # noqa: E731
    meas, dflt = sc(ref_stage["measured"][n_tr:]), sc(ref_stage["default"][n_tr:])
    auto = sc(ref_stage["auto"][n_tr:]) if lever == "I" else None
    fixed_test = sc(sims[0])
    per_seed = {}
    for sd, fz_eps, fz_plan in zip(seeds, sims[1:], fz_plans):
        pol, fz = sc(es[sd]["test"]), sc(fz_eps)
        per_seed[str(sd)] = {
            "policy_vs_measured": L.compare(pol, meas),
            "policy_vs_default": L.compare(pol, dflt),
            "policy_vs_fixed": L.compare(pol, fixed_test),
            **({"policy_vs_auto": L.compare(pol, auto)} if auto else {}),
            "adaptivity_value": L.compare(pol, fz),
            "frozen_crops": list(fz_plan.crops) if lever == "R" else None,
            "test_means": {k: float(np.mean([e[k] for e in pol])) for k in L.REPORTED},
            "parts": parts(pol, ref), "frozen_parts": parts(fz, ref),
        }
    arms = (("measured", meas), ("default", dflt), ("fixed", fixed_test)) + \
        ((("auto", auto),) if auto else ())
    out = {
        "w": W,
        "floor": "per window: default practice's relative yield in the same weather window",
        "test_means": {n: {k: float(np.mean([e[k] for e in eps])) for k in L.REPORTED}
                       for n, eps in arms},
        "parts": {n: parts(eps, ref) for n, eps in arms},
        "fixed": fixed,
        "fixed_vs_measured": L.compare(fixed_test, meas),
        "fixed_vs_default": L.compare(fixed_test, dflt),
        "default_vs_measured": L.compare(dflt, meas),
        "es": per_seed,
        "resolvable": {k: L.sign_label([v[k]["score"]["mean"] for v in per_seed.values()])
                       for k in ("policy_vs_measured", "policy_vs_default",
                                 "policy_vs_fixed", "adaptivity_value")},
    }
    res = {"config": {**report["config"], "floor": "per_window_default_ry",
                      "window_floors": {str(k): v for k, v in floors.items()},
                      "train_mean_floor": key.get("floor"),
                      "note": "rescored, not retrained: optimisers saw the train-mean floor"},
           "strategies": {S: out}}
    (OUT / f"{tag}_floorwin.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    return res


def main() -> None:
    prices = econ.prices()
    f = lambda c: f"{c['mean']:+.3f} [{c['ci95_boot'][0]:+.3f}, {c['ci95_boot'][1]:+.3f}]"  # noqa: E731
    for tag, lever, eff in JOBS:
        s = rescore(tag, lever, eff, prices)["strategies"][S]
        tm, p = s["test_means"], s["parts"]
        print(f"== {tag} (eff {eff})")
        for arm in tm:
            print(f"   {arm:9s} score {tm[arm]['score']:+.3f}  env {p[arm]['env']:.3f}  "
                  f"penalty {p[arm]['penalty']:.3f}  ry {tm[arm]['ry']:.3f}  "
                  f"water {tm[arm]['water']:.0f}  no3 {tm[arm]['no3']:.1f}")
        if lever == "R":
            print(f"   fixed rotation {s['fixed']['crops']} (train-mean floor picked "
                  f"{s['fixed']['train_mean_floor_pick']})")
        print(f"   fixed - measured {f(s['fixed_vs_measured']['score'])}   "
              f"fixed - default {f(s['fixed_vs_default']['score'])}")
        for sd, r in s["es"].items():
            print(f"   ES s{sd}: score {r['test_means']['score']:+.3f} (pen {r['parts']['penalty']:.3f})  "
                  f"vs fixed {f(r['policy_vs_fixed']['score'])}  adapt {f(r['adaptivity_value']['score'])}")
        print(f"   {s['resolvable']}")
        print(f"wrote runs/{tag}_floorwin.json", flush=True)


if __name__ == "__main__":
    main()
