"""Fit the model to the GRACEnet measurements taken on this field.

Everything scored here is **measured on the Kimberly GRACEnet plots**. The ArcSWAT reference
model no longer appears in the objective at all: it was a useful prior while the inputs were
being reconciled, but it is +20.8 % against measured ETos and its yields are its own
simulation, so minimising distance to it was minimising distance to a known bias.

Three tier-1 targets, two scored and one enforced:

**Yield** — GRACEnet dry-matter, all seven rotation years, scored as **per-year** relative
error. Not per-crop PBIAS: barley ran +53 % in 2014 and −32 % in 2019, which a crop-level bias
term scores as +2.3 %, i.e. very nearly perfect. Cancellation of that size is the thing the
objective most needs to see.

**Soil nitrate** — the seven-year April profile trajectory, via the mass-balance
reconstruction in ``scripts/n_trajectory.py``, scored as distance *outside* the bracket that
the unreported ammonium fate allows. Down-weighted, and the reason is structural rather than
evidential: see :data:`WEIGHTS`.

**PET** — a bound, not a minimand. ``pet_co`` is calibrated to measured AgriMet grass-reference
ETos (PROVENANCE §5h) and is deliberately not a free parameter here; the bound catches any
*indirect* drift through the evaporation parameters.

    uv run python scripts/calibrate/optimize.py --maxiter 60
    uv run python scripts/calibrate/optimize.py --apply      # write the fit into TxtInOut
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import EDITABLE, TXTINOUT  # noqa: E402
from swat_gym.params import CALIBRATABLE, Param, apply, read_defaults, set_value  # noqa: E402

from calib_report import collect, pbias  # noqa: E402
from n_trajectory import score as no3_score  # noqa: E402
from n_trajectory import trajectory  # noqa: E402

#: The site's own calibrated SWAT crop table (``data/crop_params_swat.csv``) is a real prior,
#: not a template default, so parameters that *have* a value there are allowed to move only
#: within a stated window around it rather than across a wide engineering range.
WINDOW = 0.30

#: crop -> (bm_e, lai_pot) as the site table gives them. Kept here rather than read from the
#: CSV so the bounds in a saved fit are reproducible from this file alone.
#:
#: ``harv_idx`` is deliberately **not** taken from ``plants.plt``. That column is inert for
#: every crop in this rotation: all three are harvested by ``hvkl`` against a ``harv.ops`` row
#: with ``harv_typ = biomass``, and SWAT+ reads the harvest index from *there*. A full-range
#: sweep of ``plants.plt:corn.harv_idx`` (0.71 -> 1.31) leaves every output bit-identical. An
#: earlier fit spent a dimension on it and parked it at a bound, which looked like a pinned
#: parameter and was really a dead one.
SITE = {"corn": (50.0, 4.0), "barl": (28.0, 4.0), "alfa": (17.0, 5.0)}

#: The operative harvest index, ``harv.ops`` rows referenced by the ``hvkl`` operations. These
#: came from the ArcSWAT reference (the rows are tagged ``reference_HI_override``). Capped at
#: 1.0 because for ``harv_typ = biomass`` this is the harvested *fraction* of standing biomass.
HARVEST = {"gn_corn": 0.98, "gn_barl": 0.54, "gn_alfa": 0.95}


def _windowed() -> list[Param]:
    out = []
    for crop, (bm_e, lai_pot) in SITE.items():
        for column, value in (("bm_e", bm_e), ("lai_pot", lai_pot)):
            out.append(Param("plants.plt", crop, column,
                             round(value * (1 - WINDOW), 4), round(value * (1 + WINDOW), 4)))
    for row, value in HARVEST.items():
        out.append(Param("harv.ops", row, "harv_idx",
                         round(value * (1 - WINDOW), 4), round(min(1.0, value * (1 + WINDOW)), 4)))
    return out


#: Columns with **no value anywhere in the site table** — a10 template defaults that nobody
#: chose. These get engineering-range bounds because there is no prior to stay near.
#:
#: Several are deliberately excluded, and every exclusion was *measured* rather than assumed.
#: ``perco``, ``rsd_decomp``, ``latq_co`` and ``plants.plt:harv_idx`` are **inert** — a
#: full-range sweep of each leaves the output bit-identical, so they only give the optimizer
#: empty dimensions to park in. ``cn3_swf`` moves yield by 0.3 points across its entire range
#: and no measurement here constrains it, so fitting it would be fitting noise. ``pet_co`` is
#: excluded because it is already fitted to a measurement (CLAUDE.md rule 10); letting the
#: yield objective pull on it would undo that silently.
UNSOURCED = [
    # alfalfa's minimum LAI is imposed on the HRU in every year of the rotation — see
    # port_crops.OVERRIDES for why this is a trade-off point rather than a "lower is better" knob.
    Param("plants.plt", "alfa", "lai_min", 0.10, 2.50),
    Param("plants.plt", "corn", "days_mat", 90, 160),
    Param("plants.plt", "barl", "days_mat", 90, 160),
    Param("hydrology.hyd", "hyd1", "epco", 0.10, 1.00),
    # Nitrogen cycling. ``orgn_min`` and ``fr_hum_act`` are the two live mineralisation knobs;
    # together they move humus mineralisation from ~54 to ~220 kg N/ha/yr.
    Param("parameters.bsn", "", "orgn_min", 0.0005, 0.0060),
    Param("nutrients.sol", "soilnut1", "fr_hum_act", 0.010, 0.250),
    Param("parameters.bsn", "", "n_perc", 0.01, 1.00),
]

PARAMS = _windowed() + UNSOURCED

#: Both terms are in percent, so they are directly comparable and the weights mean what they
#: look like.
#:
#: **The nitrate term is down-weighted for a structural reason, and it should not be read as
#: doubt about the measurement.** SWAT computes legume N fixation as the shortfall between
#: demand and soil supply, so alfalfa substitutes soil nitrate for fixation one-for-one: at
#: ``fr_hum_act`` 0.4 mineralisation rises 54 -> 220 kg N/ha/yr and fixation falls 300 -> 0,
#: leaving the soil pool almost exactly where it started. The measurement has the pool *rising*
#: +29 and +117 kg/ha in two alfalfa years, which no parameter setting can reproduce. Those
#: three years therefore carry an irreducible miss, and at unit weight the optimizer would
#: spend the whole crop budget chasing it. The four annual-crop years have no fixation and are
#: genuinely informative.
WEIGHTS = {"yield": 1.0, "no3": 0.25}
FAILED = 1e6

#: kg N/ha the nitrate miss is expressed as a percentage of — the mean measured profile stock
#: over the seven samplings. A fixed scale, for the reason given in :func:`terms`.
NO3_SCALE = 160.0

#: PET may not drift more than this (percent) from measured AgriMet ETos.
PET_TOL = 10.0


def pet_ok(df) -> bool:
    if "pet_meas" not in df:
        return True
    return abs(pbias(df["pet"], df["pet_meas"])) <= PET_TOL


def terms(runner: FastRunner, sources: dict[str, str], values: dict[Param, float]) -> dict:
    runner.run(apply(sources, values))
    df = collect(runner)
    meas = df[df["yld_meas"].notna()]

    # Per-year relative error, RMS. A crop that is high one year and low the next is scored
    # for both, which a per-crop bias term is not.
    err = 100.0 * (meas["yld"] - meas["yld_meas"]) / meas["yld_meas"]
    out = {"yield": float((err ** 2).mean() ** 0.5)}

    traj = trajectory(runner)
    # Bracket miss as a percent of NO3_SCALE, so it shares units with the yield term. The
    # normaliser is *fixed*, not each year's own pool: dividing by ``obs_end`` would make 2015
    # — which happens to have the smallest pool of the seven, 68 kg/ha — count for three times
    # what 2018 does, purely because the denominator is small.
    miss_pct = 100.0 * traj["miss"].abs() / NO3_SCALE
    out["no3"] = float((miss_pct ** 2).mean() ** 0.5)

    # Reported, never minimised — these are the numbers the paper quotes.
    out["_yield_pbias"] = pbias(meas["yld"], meas["yld_meas"])
    for crop, g in meas.groupby("crop"):
        out[f"_{crop}"] = pbias(g["yld"], g["yld_meas"])
    out["_no3_rms_kg"] = no3_score(traj, exact_only=False)
    out["_pet"] = pbias(df["pet"], df["pet_meas"]) if "pet_meas" in df else float("nan")
    out["_pet_ok"] = bool(pet_ok(df))
    return out


def score(t: dict) -> float:
    """Weighted mean squared term, in percent-squared. Rejects any fit that breaks the PET bound."""
    if not t.get("_pet_ok", True):
        return FAILED
    return sum(w * t[k] ** 2 for k, w in WEIGHTS.items()) / sum(WEIGHTS.values())


def _show(label: str, t: dict) -> None:
    print(f"  {label:<10} yield_rms {t['yield']:6.1f} %   no3_rms {t['no3']:7.1f} %   "
          f"| PBIAS all {t['_yield_pbias']:+6.1f}  corn {t['_corn']:+6.1f}  "
          f"alfa {t['_alfa']:+6.1f}  barl {t['_barl']:+6.1f}  "
          f"| PET {t['_pet']:+5.1f}  NO3 {t['_no3_rms_kg']:5.1f} kg/ha  "
          f"| SCORE {score(t):8.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maxiter", type=int, default=60)
    ap.add_argument("--popsize", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--apply", action="store_true",
                    help="write the fitted values into model/TxtInOut (default: report only)")
    ap.add_argument("--hold", nargs="*", default=[], metavar="NAME",
                    help="parameters to leave at their sourced value when applying, by "
                         "Param.name. Use for a parameter the fit moved without earning it.")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "calibration.json")
    ap.add_argument("--from-saved", action="store_true",
                    help="re-score and apply the fit already in --out instead of refitting")
    args = ap.parse_args()

    sources = {f: (TXTINOUT / f).read_text() for f in CALIBRATABLE}
    defaults = read_defaults(TXTINOUT, PARAMS)
    started = time.time()
    calls = {"n": 0, "best": np.inf}

    print(f"{len(PARAMS)} free parameters "
          f"({len(_windowed())} windowed +/-{int(WINDOW * 100)} % around the site table, "
          f"{len(UNSOURCED)} unsourced)\n")

    with FastRunner(editable=EDITABLE | CALIBRATABLE) as runner:
        base = terms(runner, sources, defaults)
        _show("start", base)
        print()

        def objective(x: np.ndarray) -> float:
            calls["n"] += 1
            try:
                s = score(terms(runner, sources, dict(zip(PARAMS, x))))
            except Exception:
                return FAILED
            if not np.isfinite(s):
                return FAILED
            if s < calls["best"]:
                calls["best"] = s
                print(f"  [{calls['n']:>6}] score {s:8.1f}  ({time.time() - started:5.0f}s)")
            return s

        if args.from_saved:
            saved = json.loads(args.out.read_text())["parameters"]
            by_name = {p.name: p for p in PARAMS}
            missing = set(by_name) - set(saved)
            if missing:
                raise SystemExit(
                    f"{args.out.name} predates the current PARAMS list (missing {sorted(missing)}). "
                    "Refit rather than applying a stale set."
                )
            best = {by_name[n]: d["fitted"] for n, d in saved.items() if n in by_name}
        else:
            result = differential_evolution(
                objective, bounds=[(p.low, p.high) for p in PARAMS],
                maxiter=args.maxiter, popsize=args.popsize, seed=args.seed,
                polish=False, init="sobol", tol=0.01,
            )
            best = dict(zip(PARAMS, result.x))
        # What actually gets written is the held-back set, so that is what gets scored.
        applied = {p: (defaults[p] if p.name in args.hold else v) for p, v in best.items()}
        final = terms(runner, sources, applied)

    print(f"\n{calls['n']} evaluations in {time.time() - started:.0f} s\n")
    _show("start", base)
    _show("fitted", final)

    print(f"\n{'parameter':<22} {'default':>10} {'fitted':>10} {'bounds':>18}  at bound?")
    for p in PARAMS:
        span = p.high - p.low
        pinned = "  <-- PINNED" if min(best[p] - p.low, p.high - best[p]) < 0.01 * span else ""
        print(f"{p.name:<22} {defaults[p]:10.4f} {best[p]:10.4f} "
              f"{f'[{p.low}, {p.high}]':>18}{pinned}")

    if args.from_saved:
        # Re-scoring a saved fit must not overwrite the record of the run that produced it —
        # ``evaluations`` would drop to 0 and the search would look like it never happened.
        print(f"\n(--from-saved: {args.out.name} left as written by the fitting run)")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "score": {"before": score(base), "after": score(final)},
            "terms": {"before": base, "after": final},
            "parameters": {p.name: {"file": p.file, "row": p.row, "column": p.column,
                                    "default": defaults[p], "fitted": best[p],
                                    "bounds": [p.low, p.high]} for p in PARAMS},
            "weights": WEIGHTS, "window": WINDOW, "evaluations": calls["n"],
            "held_at_sourced_value": sorted(args.hold),
        }, indent=2))
        print(f"\n-> {args.out}")

    if args.apply:
        unknown = set(args.hold) - {p.name for p in PARAMS}
        if unknown:
            raise SystemExit(f"--hold names no such parameter: {sorted(unknown)}")
        for name in {p.file for p in PARAMS}:
            text = (TXTINOUT / name).read_text()
            for p in PARAMS:
                if p.file == name:
                    text = set_value(text, name, p.row, p.column,
                                     defaults[p] if p.name in args.hold else best[p])
            (TXTINOUT / name).write_text(text)
        print(f"applied to {TXTINOUT}")
        for held in args.hold:
            print(f"  held at sourced value: {held}")
        print("re-run: uv run pytest && uv run python scripts/rebaseline.py --why '...'")


if __name__ == "__main__":
    main()
