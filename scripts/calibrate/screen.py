"""Morris screen: which parameters actually move this model's residuals?

Calibrating by intuition on a model this far off invites fitting the wrong knob -- the
``orgn_min`` episode in the README is exactly that failure, where a real defect hid behind a
plausible-sounding structural story. A screen is cheap insurance: at 0.55 s a run, a full
Morris design over ~16 parameters costs a couple of minutes and says which of them can move
barley biomass at all before anyone tries.

Elementary effects are reported per *objective*, not pooled, because the residuals point in
opposite directions -- corn and barley are low, alfalfa is high -- so a parameter that lifts
all three equally is useless here and a pooled score would hide that.

    uv run python scripts/calibrate/screen.py            # r=10, ~170 runs
    uv run python scripts/calibrate/screen.py --r 20     # tighter, ~340 runs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from SALib.analyze import morris as morris_analyze
from SALib.sample import morris as morris_sample

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import EDITABLE, TXTINOUT  # noqa: E402
from swat_gym.params import CALIBRATABLE, Param, apply  # noqa: E402

from calib_report import GRACENET, collect, pbias  # noqa: E402

#: Bounds are agronomic ranges, not arbitrary multiples of the current value. bm_e is
#: radiation-use efficiency (kg/ha per MJ/m2); lai_pot the potential leaf area index;
#: harv_idx the fraction of biomass removed; tmp_opt/tmp_base the growth temperature window.
PARAMS = [
    # --- barley: the crop needing ~2.4x its current biomass ---
    Param("plants.plt", "barl", "bm_e", 20.0, 45.0),
    Param("plants.plt", "barl", "lai_pot", 3.0, 7.0),
    Param("plants.plt", "barl", "days_mat", 90.0, 150.0),
    Param("plants.plt", "barl", "tmp_opt", 15.0, 25.0),
    # --- corn: low by ~40% ---
    Param("plants.plt", "corn", "bm_e", 35.0, 60.0),
    Param("plants.plt", "corn", "lai_pot", 3.0, 7.0),
    Param("plants.plt", "corn", "days_mat", 100.0, 160.0),
    Param("plants.plt", "corn", "tmp_opt", 20.0, 30.0),
    # --- alfalfa: the one crop that is too high ---
    Param("plants.plt", "alfa", "bm_e", 10.0, 25.0),
    Param("plants.plt", "alfa", "lai_pot", 3.0, 6.0),
    # --- water: ET is 11% low, which caps every crop's growth ---
    Param("hydrology.hyd", "hyd1", "esco", 0.5, 1.0),
    Param("hydrology.hyd", "hyd1", "epco", 0.1, 1.0),
    Param("hydrology.hyd", "hyd1", "perco", 0.0, 1.0),
    Param("hydrology.hyd", "hyd1", "can_max", 0.0, 10.0),
    # --- nitrogen: uptake is 21% low, leaching 30% high ---
    Param("parameters.bsn", "", "orgn_min", 0.0005, 0.004),
    Param("parameters.bsn", "", "n_uptake", 5.0, 40.0),
    Param("parameters.bsn", "", "n_perc", 0.05, 1.0),
]

#: What each run is scored on. Signed PBIAS throughout, so a sign flip is visible.
OBJECTIVES = ["corn_meas", "alfa_meas", "barl_ref", "et_ref", "nup_ref", "no3_ref"]


def evaluate(runner: FastRunner, sources: dict[str, str], values: dict[Param, float]) -> dict:
    """One model run under a parameter vector -> the objective vector."""
    runner.run(apply(sources, values))
    df = collect(runner)
    meas = df[df["yld_meas"].notna()]
    out = {}
    for crop in ("corn", "alfa"):
        g = meas[meas["crop"] == crop]
        out[f"{crop}_meas"] = pbias(g["yld"], g["yld_meas"])
    g = df[df["crop"] == "barl"]
    out["barl_ref"] = pbias(g["yld"], g["yld_ref"])
    for var in ("et", "nup", "no3"):
        out[f"{var}_ref"] = pbias(df[var], df[f"{var}_ref"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r", type=int, default=10, help="Morris trajectories")
    ap.add_argument("--levels", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "screen_morris.csv")
    args = ap.parse_args()

    problem = {
        "num_vars": len(PARAMS),
        "names": [p.name for p in PARAMS],
        "bounds": [[p.low, p.high] for p in PARAMS],
    }
    X = morris_sample.sample(problem, N=args.r, num_levels=args.levels)
    print(f"{len(PARAMS)} parameters, {len(X)} runs "
          f"(~{len(X) * 0.55 / 60:.1f} min at 0.55 s/run)\n")

    sources = {f: (TXTINOUT / f).read_text() for f in CALIBRATABLE}
    rows = []
    with FastRunner(editable=EDITABLE | CALIBRATABLE) as runner:
        for i, vector in enumerate(X, 1):
            values = dict(zip(PARAMS, vector))
            try:
                rows.append(evaluate(runner, sources, values))
            except Exception as exc:  # a parameter combination the engine rejects
                print(f"  run {i}: FAILED ({type(exc).__name__}) -- recorded as NaN")
                rows.append({k: np.nan for k in OBJECTIVES})
            if i % 20 == 0 or i == len(X):
                print(f"  {i}/{len(X)}")

    Y = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([pd.DataFrame(X, columns=problem["names"]), Y], axis=1).to_csv(args.out, index=False)
    print(f"\nraw design + responses -> {args.out}")

    print("\nmu* (mean |elementary effect|, in PBIAS points per unit move):")
    table = {}
    for obj in OBJECTIVES:
        y = Y[obj].to_numpy(float)
        ok = np.isfinite(y)
        if ok.sum() < len(y):
            print(f"  ({obj}: {(~ok).sum()} failed runs excluded)")
        res = morris_analyze.analyze(problem, X[ok], y[ok], num_levels=args.levels)
        table[obj] = pd.Series(res["mu_star"], index=res["names"])
    mu = pd.DataFrame(table)
    mu["max"] = mu.max(axis=1)
    print(mu.sort_values("max", ascending=False).round(1).to_string())


if __name__ == "__main__":
    main()
