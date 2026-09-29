#!/usr/bin/env python3
"""Re-derive every number the 2026-09-10 refit is reported on, from the model as it sits on disk.

This exists so that the refit's claims can be **checked rather than trusted**. Everything below is
computed from ``model/TxtInOut`` at the moment of the run; nothing is read back from an artefact,
so a stale ``runs/*.json`` cannot make this agree with a report that has drifted from the model.

    uv run python scripts/verify_model_state.py
    uv run python scripts/verify_model_state.py --sweeps   # adds the identifiability evidence

The plain run is fast (a handful of engine runs). ``--sweeps`` re-measures the four parameters
removed from the free set and takes a couple of minutes.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.abspath(str(ROOT / "scripts")))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import EDITABLE, TXTINOUT  # noqa: E402
from swat_gym.params import CALIBRATABLE, Param, get_value, read_defaults  # noqa: E402

from calib_report import GRACENET, collect  # noqa: E402
from calibrate.optimize import PARAMS, terms, score  # noqa: E402
from n_trajectory import trajectory  # noqa: E402

#: Every parameter the refit touched, with the provenance that decides its value. ``source`` is
#: what the value must be; ``None`` means "fitted, no source, reported not asserted".
OWNERSHIP = [
    # file,             row,        column,      expected, provenance
    ("plants.plt",      "alfa",     "lai_min",   1.75,     "sourced; inert under rev 62 (PARAMS-excluded)"),
    ("plants.plt",      "corn",     "days_mat",  120.0,    "engine stock; unidentified (score flat 120-140)"),
    ("plants.plt",      "barl",     "days_mat",  105.0,    "engine stock; pinned at floor when free"),
    ("hydrology.hyd",   "hyd1",     "epco",      0.50,     "REF 000140001.hru; unidentified (monotone)"),
    ("hydrology.hyd",   "hyd1",     "pet_co",    0.964,    "closed-form fit to measured AgriMet ETos"),
    ("parameters.bsn",  "",         "n_perc",    0.20,     "REF; held (buys NO3, costs yield)"),
    ("nutrients.sol",   "soilnut1", "fr_hum_act", 0.02,    "REF; held (buys NO3, costs yield)"),
    ("parameters.bsn",  "",         "orgn_min",  None,     "FITTED — the only free parameter"),
]

#: Measured buried-bag net N mineralisation, 0-60 cm, kg N/ha/yr (PROVENANCE 5e).
MINERALISATION_MEASURED = 209.8


def ownership() -> int:
    print("PARAMETER OWNERSHIP  (expected value <- provenance)")
    print(f"  {'parameter':<34}{'on disk':>12}{'expected':>12}  provenance")
    bad = 0
    for f, row, col, want, why in OWNERSHIP:
        cur = get_value((TXTINOUT / f).read_text(), f, row, col)
        if want is None:
            mark = "  (fitted)"
        elif abs(cur - want) > 1e-4 * max(1.0, abs(want)):
            mark, bad = "  <-- DRIFTED", bad + 1
        else:
            mark = "  ok"
        shown = "—" if want is None else f"{want:.5g}"
        print(f"  {f + ':' + (row + '.' if row else '') + col:<34}{cur:>12.5g}{shown:>12}{mark}  {why}")
    return bad


def state(runner: FastRunner) -> None:
    sources = {f: (TXTINOUT / f).read_text() for f in CALIBRATABLE}
    t = terms(runner, sources, read_defaults(TXTINOUT, PARAMS))
    df = collect(runner)
    meas = df[df["yld_meas"].notna()]

    print("\nYIELD, PER YEAR  (the aggregate cancels; this does not)")
    print(f"  {'year':<6}{'crop':<9}{'measured':>10}{'sim':>9}{'err %':>9}")
    for yr, r in meas.iterrows():
        print(f"  {int(yr):<6}{r['crop']:<9}{r['yld_meas']:>10.2f}{r['yld']:>9.2f}"
              f"{100.0 * (r['yld'] - r['yld_meas']) / r['yld_meas']:>+9.1f}")
    print(f"\n  per-year RMS        {t['yield']:>8.1f} %")
    print(f"  PBIAS, all crops    {t['_yield_pbias']:>+8.1f} %")
    for c, label in (("_corn", "corn"), ("_alfa", "alfalfa"), ("_barl", "barley")):
        print(f"  PBIAS, {label:<13}{t[c]:>+8.1f} %")
    print(f"  PET vs measured     {t['_pet']:>+8.1f} %   (bound +/-10, "
          f"{'OK' if t['_pet_ok'] else 'VIOLATED'})")
    print(f"  soil-NO3 miss RMS   {t['_no3_rms_kg']:>8.1f} kg/ha")
    print(f"  calibration SCORE   {score(t):>8.1f}")

    print("\nWATER AND NITROGEN, mean over simulated years")
    for c, unit in (("et", "mm/yr"), ("pet", "mm/yr"), ("perc", "mm/yr"), ("no3", "kg/ha/yr")):
        print(f"  {c:<20}{df[c].mean():>8.2f} {unit}")
    nb = runner.read("basin_nb_yr.txt")
    print(f"  {'mineralised':<20}{nb['act_nit_n'].mean():>8.1f} kg/ha/yr   "
          f"(measured {MINERALISATION_MEASURED}; unreachable — rules 12/13)")
    print(f"  {'fixed':<20}{nb['fixn'].mean():>8.1f} kg/ha/yr   "
          "(substitutes for mineralised N — PROVENANCE 5i)")

    traj = trajectory(runner)
    print(f"\n  soil-nitrate trajectory rows outside the ammonium bracket: "
          f"{int((traj['miss'].abs() > 0).sum())} of {len(traj)}")


def sweeps(runner: FastRunner) -> None:
    """The identifiability evidence for the four parameters removed from the free set."""
    sources = {f: (TXTINOUT / f).read_text() for f in CALIBRATABLE}
    disk = read_defaults(TXTINOUT, PARAMS)

    def at(file: str, row: str, col: str, values: list[float]) -> None:
        # The swept column must be handed to ``terms`` as a Param, not pre-edited into
        # ``sources``: ``params.apply`` returns only the files PARAMS touches, so an edit to a
        # file no longer in the free set is silently dropped and every row comes back identical.
        # That is precisely the failure this script exists to catch, so it must not commit it.
        knob = Param(file, row, col, min(values), max(values))
        print(f"\n  {file}:{row + '.' if row else ''}{col}")
        print(f"    {'value':>10}{'SCORE':>9}{'yld_rms':>9}{'corn':>8}{'alfa':>8}{'barl':>8}{'perc':>8}")
        for v in values:
            t = terms(runner, sources, {**disk, knob: v})
            df = collect(runner)
            print(f"    {v:>10.5g}{score(t):>9.1f}{t['yield']:>9.2f}{t['_corn']:>+8.1f}"
                  f"{t['_alfa']:>+8.1f}{t['_barl']:>+8.1f}{df['perc'].mean():>8.2f}")

    print("\nIDENTIFIABILITY OF THE PARAMETERS REMOVED FROM THE FREE SET")
    print("  epco: monotone to the smallest value tested — a compensator, not a parameter.")
    at("hydrology.hyd", "hyd1", "epco", [0.01, 0.05, 0.10, 0.50, 1.00])
    print("\n  corn.days_mat: flat 120-140, so the fitted 124 is indistinguishable from stock 120.")
    at("plants.plt", "corn", "days_mat", [97, 110, 120, 130, 140])
    print("\n  barl.days_mat: best score at its floor, but per-crop barley bias is worse there.")
    at("plants.plt", "barl", "days_mat", [90, 95, 105, 110])
    print("\n  alfa.lai_min: inert — the score does not move at all.")
    at("plants.plt", "alfa", "lai_min", [0.45, 1.01216, 1.75, 2.50])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweeps", action="store_true", help="also re-measure the identifiability evidence")
    args = ap.parse_args()

    bad = ownership()
    with FastRunner(editable=EDITABLE | CALIBRATABLE) as runner:
        runner.run()
        state(runner)
        if args.sweeps:
            sweeps(runner)

    print(f"\n{'PASS' if bad == 0 else f'FAIL — {bad} parameter(s) drifted from provenance'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
