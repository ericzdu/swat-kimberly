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

#: **Crop coefficients are not fitted here — CLAUDE.md rule 11b.** ``bm_e``, ``lai_pot``, the
#: canopy curve and the ``harv.ops`` harvest indices are the collaborator's calibrated workbook
#: values and are applied *exactly* (`scripts/port_crops.py`, `scripts/port_management.py`).
#: This module used to open a +/-30 % window around each of them. Measured before removing it
#: (2026-08-07): fitting those nine parameters bought 2.3 points of mean |PBIAS| — 37.1 % ->
#: 34.8 % — and paid for it by making every alfalfa year 14-17 points *worse*, while producing
#: a ``corn.bm_e`` of 64.5 that absorbed the resident-perennial artefact and so hid a structural
#: error inside a parameter. The workbook values leave that bias visible, which is the point.
#: Domain ownership sits with the collaborator; we own the protocol, not the agronomy.
#:
#: ``plants.plt:harv_idx`` would be a dead dimension regardless: all three crops are harvested
#: by ``hvkl`` against a ``harv.ops`` row with ``harv_typ = biomass``, so SWAT+ reads the
#: harvest index from *there* and a full-range sweep of the ``plants.plt`` column (0.71 -> 1.31)
#: leaves every output bit-identical.
#:
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
#: ``alfa.lai_min`` was **dropped from this list 2026-09-10** and pinned in
#: ``port_crops.OVERRIDES`` at its sourced 1.75. It is inert on the workbook crops: 1.01216 ->
#: 1.75 moves the score by zero to five significant figures, and a free refit parked it at
#: 0.4501 for the same zero. Under rev 62 the resident-perennial PAR-theft pathway it acted
#: through is gone. Leaving it free gives the optimizer a dead dimension to park in and
#: produces a number that reads as tuned, which is the ``corn.harv_idx`` failure of §5j.
#: **Three more came out 2026-09-10, on measurement.** The 2026-07-31 fit left five parameters
#: on disk whose only justification was that fit — and that fit was run against the pre-rule-11b
#: crop coefficients, so they were orphans of a model that no longer exists. Refitting them
#: against the workbook crops showed that four should never have been free:
#:
#: * ``hydrology.hyd:epco`` — **it has a source value.** PROVENANCE §5 records that ``esco``
#:   0.95 and ``epco`` 0.50 "already match REF ``000140001.hru`` exactly"; §6's claim that epco
#:   "had no source value at all" is simply wrong, and is corrected there. Under rule 11 the
#:   sourced value wins. It is also *unidentified* by this objective and improves monotonically
#:   to the smallest value tested — 0.50 -> 0.10 -> 0.01 takes the score 1824.9 -> 1563.8 ->
#:   1323.6 and alfalfa +48.9 -> +39.0 -> +24.7 — because it is absorbing alfalfa's workbook
#:   over-prediction, which rule 11b exists to keep visible. Fitting it is fitting ``alfa.bm_e``
#:   through a side door. It also manufactures the leaching column: percolation is 19.9 mm/yr at
#:   epco 0.10 against 1.9 at the sourced 0.50, so an unidentified parameter would be setting
#:   the sustainability channel. Held at 0.50.
#: * ``corn.days_mat`` — unidentified. The score is flat from 120 to 140 (1566.7 / 1565.8 /
#:   1564.0 / 1566.0), so the fit's 124 is indistinguishable from the engine stock 120. Left at
#:   stock. Note the *stale* 97 was worth 11 points of corn bias on its own: reverting 97 -> 120
#:   takes corn -24.6 % -> -13.0 %, which is most of what this whole refit recovered.
#: * ``barl.days_mat`` — pins at its 90-day floor, which is short for spring barley on a site
#:   documented at a 124-day season, and it makes *per-crop* barley bias worse (+1.2 at the
#:   stock 105 against -7.0 at 90). It is chasing 2014's over-prediction, not maturity. Left at
#:   stock 105.
#: * ``alfa.lai_min`` — inert; see the note above.
#:
#: What is left is the nitrogen cycle, which rule 12 requires to stay fittable against the
#: measurement rather than carried across from SWAT2012.
PARAMS = [
    # Nitrogen cycling. ``orgn_min`` and ``fr_hum_act`` are the two live mineralisation knobs;
    # together they move humus mineralisation from ~54 to ~220 kg N/ha/yr.
    Param("parameters.bsn", "", "orgn_min", 0.0005, 0.0060),
    Param("nutrients.sol", "soilnut1", "fr_hum_act", 0.010, 0.250),
    Param("parameters.bsn", "", "n_perc", 0.01, 1.00),
]

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
                    help="parameters to fix at their sourced value, by Param.name. They are "
                         "excluded from the search, not merely from the write — see below.")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "calibration.json")
    ap.add_argument("--from-saved", action="store_true",
                    help="re-score and apply the fit already in --out instead of refitting")
    args = ap.parse_args()

    # Validate --hold *before* the search, not inside ``if args.apply``. A name that matches no
    # Param was silently ignored on the scoring path — ``p.name in args.hold`` just never fired —
    # so a report-only run would print numbers for a parameter the operator believed was held,
    # and only a later --apply would reveal it. ``fr_hum_act`` is the live example: its Param.name
    # is ``soilnut1.fr_hum_act``. That is the hard-rule-2 failure class exactly: a difference
    # between what was simulated and what the artefact says was simulated, invisible in the score.
    unknown = set(args.hold) - {p.name for p in PARAMS}
    if unknown:
        raise SystemExit(f"--hold names no such parameter: {sorted(unknown)}  "
                         f"(known: {sorted(p.name for p in PARAMS)})")

    sources = {f: (TXTINOUT / f).read_text() for f in CALIBRATABLE}
    defaults = read_defaults(TXTINOUT, PARAMS)
    started = time.time()
    calls = {"n": 0, "best": np.inf}

    # ``--hold`` **excludes from the search**, not just from the write. It used to fit every
    # parameter freely and substitute the sourced value only at --apply time, which optimises a
    # different problem from the one applied: the free parameters land on an optimum conditional
    # on a held parameter's *fitted* value, and the applied model can then score worse than the
    # start. Measured 2026-09-10 — holding n_perc and fr_hum_act after a free search gave 1999.2
    # against a start of 1995.5, while the true conditional optimum is 1992.6.
    free = [p for p in PARAMS if p.name not in args.hold]
    print(f"{len(free)} free parameters, {len(PARAMS) - len(free)} held at sourced value "
          "(all unsourced; crop coefficients are the collaborator's, not fitted)\n")

    with FastRunner(editable=EDITABLE | CALIBRATABLE) as runner:
        base = terms(runner, sources, defaults)
        _show("start", base)
        print()

        def expand(x: np.ndarray) -> dict:
            """Search vector over the free parameters -> a full parameter set."""
            v = dict(zip(free, x))
            return {p: v.get(p, defaults[p]) for p in PARAMS}

        def objective(x: np.ndarray) -> float:
            calls["n"] += 1
            try:
                s = score(terms(runner, sources, expand(x)))
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
            best = {p: (defaults[p] if p.name in args.hold else v) for p, v in best.items()}
        else:
            result = differential_evolution(
                objective, bounds=[(p.low, p.high) for p in free],
                maxiter=args.maxiter, popsize=args.popsize, seed=args.seed,
                polish=False, init="sobol", tol=0.01,
            )
            best = expand(result.x)
        # ``best`` already carries the sourced value for anything held, so what is scored here
        # is exactly what --apply writes.
        final = terms(runner, sources, best)

    print(f"\n{calls['n']} evaluations in {time.time() - started:.0f} s\n")
    _show("start", base)
    _show("fitted", final)

    print(f"\n{'parameter':<22} {'default':>10} {'fitted':>10} {'bounds':>18}  at bound?")
    for p in PARAMS:
        span = p.high - p.low
        if p.name in args.hold:
            pinned = "  <-- HELD (not searched)"
        else:
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
            "weights": WEIGHTS, "evaluations": calls["n"],
            "held_at_sourced_value": sorted(args.hold),
        }, indent=2))
        print(f"\n-> {args.out}")

    if args.apply:
        for name in {p.file for p in PARAMS}:
            text = (TXTINOUT / name).read_text()
            for p in PARAMS:
                if p.file == name:
                    text = set_value(text, name, p.row, p.column, best[p])
            (TXTINOUT / name).write_text(text)
        print(f"applied to {TXTINOUT}")
        for held in args.hold:
            print(f"  held at sourced value: {held}")
        print("re-run: uv run pytest && uv run python scripts/rebaseline.py --why '...'")


if __name__ == "__main__":
    main()
