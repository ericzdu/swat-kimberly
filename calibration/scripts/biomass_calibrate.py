#!/usr/bin/env python3
"""Fit biomass and N/P uptake per crop to the collaborator's long-term targets.

Targets: ``data/biomass_targets.csv`` (the collaborator's guide and sheet, 2026-10-22). Per crop,
long-term means of:

* **maximum yearly total biomass** (above + belowground), t/ha -- the engine's ``bioms`` is
  ``pl_mass%tot_com%m`` (``hru_control.f90``), roots included, so its yearly maximum *is* the
  target quantity. **Alfalfa** is scored on yearly total *yield* of the four cuttings instead
  (the sum of ``hru_pw_day.yield``), as the guide says;
* **yearly N uptake**, kg/ha -- the sum of ``hru_nb_day.nuptake``, which is soil uptake *plus*
  fixation (``pl_nup.f90`` adds ``fixn`` before accumulating), so alfalfa's 500 kg includes
  what it fixes;
* **yearly P uptake**, kg/ha -- the sum of ``hru_nb_day.puptake``.

Knobs, per crop, in the order they are fitted:

1. ``bm_e``, ``tmp_opt``, ``tmp_base`` against biomass (decided 2026-10-23: TMP free, ET
   refit afterwards). Three knobs and one target, so the fit is regularised toward the
   workbook the same way ``et_calibrate`` is: ``reg`` is the |miss %| a full-range move of a
   knob must buy back. ``days_mat`` is in the guide but inert here (``calibration.cal``'s
   ``phu_mat`` overrides it), so heat units stay with the ET fit.
2. ``n_scale``: one factor on the workbook's DEFAULT BN1/BN2/BN3 (``data/crop_np_default.csv``)
   to the N target; then ``p_scale`` the same on BP1-3 -- the collaborator's method, verbatim.
   A 1-D bracketed root-find each; uptake is monotone in the factor.
3. Biomass re-checked at the fitted factors and steps 1-2 repeated, warm-started, until all
   three are within ``--tol`` % or ``--rounds`` is spent. N/P can feed back on biomass only
   through stress, which the lifted auto-fert caps (``monoculture.FERT_EVENTS_MAX``) keep near
   zero, so this usually takes one round.

Runs are the ET build exactly (``et_calibrate.CropFit._build`` + ``apply_et_fit``): windowed
irrigation, fitted canopy and PHU, auto-fert to demand. It builds with ``with_biomass=False``
so the anchor is the workbook, never this fit's previous output. Window: 1995-2025 weather,
the first year skipped by ``print.prt``'s ``nyskip``.

``--hold-tmp`` is the touch-up after an ET refit: ``tmp_*`` held at the applied fit, only
``bm_e`` and the two factors re-solved, so the ET timing the refit just settled is not moved.
``--check`` scores the applied ``data/biomass_fitted.json`` on the full run-ready build.

Pinto bean has no target and is not fitted: it runs with DEFAULT N/P (identical to the
workbook's calibrated block for that crop) and workbook ``bm_e``/``tmp_*``.

    uv run python scripts/biomass_calibrate.py               # fit, write runs/biomass_calibration/
    uv run python scripts/biomass_calibrate.py --apply       # ... and data/biomass_fitted.json
    uv run python scripts/biomass_calibrate.py --hold-tmp --apply
    uv run python scripts/biomass_calibrate.py --check
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import et_calibrate as etc  # noqa: E402
import monoculture as mono  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402
from swat_gym.params import get_value  # noqa: E402

TARGETS = ROOT / "data" / "biomass_targets.csv"
OUT = ROOT / "runs" / "biomass_calibration"

#: Weather is 1995-2025; ``print.prt`` skips the first year, so 1996-2025 are scored.
START, YEARS = 1995, 30

#: ``(low, high)`` per biomass knob. ``tmp_base`` spans the workbook's 0 (wheat, barley) to 10
#: (pinto bean) with headroom; ``tmp_opt`` its 18-25. ``bm_e`` is wide on purpose -- corn's
#: site value is 50 and the rotation fit put it at 64.5.
BOUNDS = {"bm_e": (5.0, 80.0), "tmp_opt": (10.0, 35.0), "tmp_base": (0.0, 15.0)}
#: ``tmp_opt`` must stay this far above ``tmp_base``; the engine's temperature-stress curve is
#: symmetric about ``tmp_opt`` and degenerates as the two meet, without complaint.
TMP_GAP = 5.0
SCALE_BOUNDS = (0.2, 5.0)
#: First Nelder-Mead simplex steps; the default 5 % of zero leaves ``tmp_base`` 0 unexplored.
SIMPLEX_STEP = {"bm_e": 5.0, "tmp_opt": 2.0, "tmp_base": 2.0}


def clip(v: dict) -> dict:
    v = {k: float(np.clip(v[k], *BOUNDS[k])) for k in BOUNDS}
    v["tmp_opt"] = max(v["tmp_opt"], v["tmp_base"] + TMP_GAP)
    return v


class CropBio:
    """One crop's runner and scorer."""

    def __init__(self, code: str, target: pd.Series, workroot: Path, *, built: bool = False,
                 reg: float = 10.0) -> None:
        self.code, self.plt = code, mono.CROPS[code][0]
        self.target, self.reg = target, reg
        shared, _ = mono.load_et_fit()
        dest = workroot / f"_tio_{self.plt}"
        # built=True is --check: the run-ready state, biomass fit included.
        tio = etc.CropFit._build(code, START, YEARS, dest, shared["irr_sw_frac"],
                                 with_biomass=built)
        mono.apply_et_fit(tio, self.plt)
        self.runner = FastRunner(txtinout=tio, keep={"hru_pw": {"daily"}, "hru_nb": {"daily"}},
                                 editable=frozenset({"plants.plt"}))
        self._plants = (tio / "plants.plt").read_text()
        #: The regularisation anchor: workbook bm_e/tmp_*, read back from the built file.
        self.start = {k: get_value(self._plants, "plants.plt", self.plt, k) for k in BOUNDS}
        self.alfalfa = target["target_kind"] == "yield"
        self._cache: dict = {}

    def run(self, fit: dict) -> pd.DataFrame:
        """Per-year table at ``fit`` (any subset of knobs + n_scale/p_scale)."""
        key = tuple(round(float(fit.get(k, -1)), 5)
                    for k in (*BOUNDS, "n_scale", "p_scale"))
        if key in self._cache:
            return self._cache[key]
        plants = (mono.biomass_text(self._plants, self.plt, fit) if fit else self._plants)
        self.runner.run({"plants.plt": plants})
        pw, nb = self.runner.read("hru_pw_day.txt"), self.runner.read("hru_nb_day.txt")
        g, gn = pw.groupby("yr"), nb.groupby("yr")
        df = pd.DataFrame({
            "bm_max_t_ha": g["bioms"].max() / 1000.0,
            "yield_t_ha": g["yield"].sum() / 1000.0,
            "n_up_kg_ha": gn["nuptake"].sum(),
            "p_up_kg_ha": gn["puptake"].sum(),
            "fertn_kg_ha": gn["fertn"].sum(),
            "fertp_kg_ha": gn["fertp"].sum(),
            "fixn_kg_ha": gn["fixn"].sum() if "fixn" in nb else np.nan,
            "strsn_days": g["strsn"].apply(lambda s: int((s > 0.1).sum())),
            "strsp_days": g["strsp"].apply(lambda s: int((s > 0.1).sum())),
            "strstmp_days": g["strstmp"].apply(lambda s: int((s > 0.1).sum())),
            "lai_max": g["lai"].max(),
        })
        df.index.name = "yr"
        self._cache[key] = df
        return df

    def biomass_col(self) -> str:
        return "yield_t_ha" if self.alfalfa else "bm_max_t_ha"

    def miss(self, df: pd.DataFrame) -> dict:
        """Percent miss of each long-term mean against its target."""
        return {
            "biomass": 100.0 * (df[self.biomass_col()].mean() / self.target["biomass_t_ha"] - 1),
            "n_up": 100.0 * (df["n_up_kg_ha"].mean() / self.target["n_up_kg_ha"] - 1),
            "p_up": 100.0 * (df["p_up_kg_ha"].mean() / self.target["p_up_kg_ha"] - 1),
        }

    # -- fitting ---------------------------------------------------------------------

    def fit_biomass(self, fit: dict, knobs: tuple[str, ...]) -> dict:
        """Biomass knobs at fixed factors. One knob: root-find. Three: regularised NM."""
        if knobs == ("bm_e",):
            f = lambda b: self.miss(self.run({**fit, "bm_e": b}))["biomass"]  # noqa: E731
            lo, hi = BOUNDS["bm_e"]
            return {**fit, "bm_e": self._root(f, lo, hi)}

        def obj(x):
            v = clip(dict(zip(BOUNDS, x)))
            pen = self.reg * sum(((v[k] - self.start[k]) / (BOUNDS[k][1] - BOUNDS[k][0])) ** 2
                                 for k in BOUNDS)
            return abs(self.miss(self.run({**fit, **v}))["biomass"]) + pen

        # Warm start: bm_e alone onto the target at the current tmp_*, so the simplex begins
        # on the target and only has to trade along it toward the workbook.
        x0 = clip({k: fit.get(k, self.start[k]) for k in BOUNDS})
        x0 = self.fit_biomass({**fit, **x0}, ("bm_e",))
        x0 = np.array([x0[k] for k in BOUNDS])
        simplex = np.array([x0] + [x0 + np.eye(len(BOUNDS))[i] * SIMPLEX_STEP[k]
                                   for i, k in enumerate(BOUNDS)])
        res = minimize(obj, x0, method="Nelder-Mead",
                       options={"initial_simplex": simplex, "xatol": 1e-2, "fatol": 1e-2,
                                "maxfev": 250})
        best = res.x if res.fun <= obj(x0) else x0
        return {**fit, **clip(dict(zip(BOUNDS, best)))}

    def fit_scale(self, fit: dict, key: str, col: str) -> dict:
        f = lambda s: self.miss(self.run({**fit, key: s}))[col]  # noqa: E731
        return {**fit, key: self._root(f, *SCALE_BOUNDS)}

    @staticmethod
    def _root(f, lo: float, hi: float) -> float:
        """Bracketed root of ``f``; the nearer bound when the target lies outside it."""
        flo, fhi = f(lo), f(hi)
        if np.sign(flo) == np.sign(fhi):
            return lo if abs(flo) < abs(fhi) else hi
        return float(brentq(f, lo, hi, xtol=1e-3, rtol=1e-4))

    def close(self) -> None:
        self.runner.close()


def summarise(cb: CropBio, fit: dict, df: pd.DataFrame, rounds: int, tol: float) -> dict:
    m = cb.miss(df)
    at_bound = {k: bool(np.isclose(fit[k], BOUNDS[k][0]) or np.isclose(fit[k], BOUNDS[k][1]))
                for k in BOUNDS if k in fit}
    at_bound.update({k: bool(np.isclose(fit[k], SCALE_BOUNDS[0])
                             or np.isclose(fit[k], SCALE_BOUNDS[1]))
                     for k in ("n_scale", "p_scale") if k in fit})
    base = mono.np_defaults(cb.plt)
    return {
        "crop": cb.code, "plants_plt": cb.plt, "target_kind": cb.target["target_kind"],
        "start": {**cb.start, "n_scale": 1.0, "p_scale": 1.0},
        "fit": fit, "at_bound": at_bound, "rounds": rounds,
        "frac_np": {c: base[c] * fit.get("n_scale" if c in mono.N_COLS else "p_scale", 1.0)
                    for c in (*mono.N_COLS, *mono.P_COLS)},
        "target": {"biomass_t_ha": float(cb.target["biomass_t_ha"]),
                   "n_up_kg_ha": float(cb.target["n_up_kg_ha"]),
                   "p_up_kg_ha": float(cb.target["p_up_kg_ha"])},
        "sim_mean": {"biomass_t_ha": float(df[cb.biomass_col()].mean()),
                     "n_up_kg_ha": float(df["n_up_kg_ha"].mean()),
                     "p_up_kg_ha": float(df["p_up_kg_ha"].mean()),
                     "bm_max_t_ha": float(df["bm_max_t_ha"].mean()),
                     "yield_t_ha": float(df["yield_t_ha"].mean()),
                     "fertn_kg_ha": float(df["fertn_kg_ha"].mean()),
                     "fertp_kg_ha": float(df["fertp_kg_ha"].mean())},
        "sim_cv_pct": {"biomass": float(100 * df[cb.biomass_col()].std()
                                        / df[cb.biomass_col()].mean()),
                       "n_up": float(100 * df["n_up_kg_ha"].std() / df["n_up_kg_ha"].mean()),
                       "p_up": float(100 * df["p_up_kg_ha"].std() / df["p_up_kg_ha"].mean())},
        "miss_pct": m, "within_tol": all(abs(v) <= tol for v in m.values()),
        "engine_runs": cb.runner.n_runs,
    }


def calibrate_crop(code: str, target: dict, workroot: str, hold_tmp: bool, check: bool,
                   rounds: int, tol: float, reg: float) -> tuple[dict, pd.DataFrame]:
    """One crop end to end; a top-level function so it can run in a worker process."""
    target = pd.Series(target)
    cb = CropBio(code, target, Path(workroot), built=check, reg=reg)
    try:
        if check:
            fit = mono.load_biomass_fit().get(cb.plt, {})
            df = cb.run({})
            return summarise(cb, fit, df, 0, tol), df
        applied = mono.load_biomass_fit().get(cb.plt, {})
        if hold_tmp:
            if not applied:
                raise SystemExit(f"--hold-tmp: no applied fit for {cb.plt} in "
                                 f"{mono.BIOMASS_FITTED.name}")
            fit = dict(applied)
            knobs: tuple[str, ...] = ("bm_e",)
        else:
            fit = {**cb.start, "n_scale": 1.0, "p_scale": 1.0}
            knobs = tuple(BOUNDS)
        n = 0
        for n in range(1, rounds + 1):
            fit = cb.fit_biomass(fit, knobs)
            fit = cb.fit_scale(fit, "n_scale", "n_up")
            fit = cb.fit_scale(fit, "p_scale", "p_up")
            df = cb.run(fit)
            if all(abs(v) <= tol for v in cb.miss(df).values()):
                break
            knobs = ("bm_e",) if hold_tmp else knobs
        return summarise(cb, fit, df, n, tol), df
    finally:
        cb.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops", nargs="*", default=None)
    ap.add_argument("--apply", action="store_true", help="write data/biomass_fitted.json")
    ap.add_argument("--hold-tmp", action="store_true",
                    help="hold tmp_* at the applied fit; re-solve bm_e and the factors only")
    ap.add_argument("--check", action="store_true",
                    help="score the applied fit on the run-ready build; fit nothing")
    ap.add_argument("--tol", type=float, default=3.0, help="|miss| %% each target must meet")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--reg", type=float, default=10.0,
                    help="|biomass miss| %% a full-range knob move must buy back")
    ap.add_argument("--outdir", type=Path, default=OUT)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.check and (args.apply or args.hold_tmp):
        raise SystemExit("--check fits nothing; it cannot be combined with --apply/--hold-tmp")

    targets = pd.read_csv(TARGETS, comment="#").set_index("crop")
    codes = args.crops or list(targets.index)
    bad = [c for c in codes if c not in targets.index]
    if bad:
        raise SystemExit(f"no target for {bad}; have {list(targets.index)}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    work = args.outdir / "_work"
    mode = "check" if args.check else ("hold-tmp" if args.hold_tmp else "full")
    print(f"mode {mode}, window {START + 1}-{START + YEARS}, tol {args.tol} %, "
          f"reg {args.reg}, fert caps {mono.FERT_EVENTS_MAX} events/yr\n", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {c: ex.submit(calibrate_crop, c, targets.loc[c].to_dict(), str(work),
                             args.hold_tmp, args.check, args.rounds, args.tol, args.reg)
                for c in codes}
        results, per_year = [], []
        for c, fut in futs.items():
            res, df = fut.result()
            results.append(res)
            per_year.append(df.reset_index().assign(crop=c))
    shutil.rmtree(work, ignore_errors=True)

    rows = []
    for r in results:
        f, s, t, m = r["fit"], r["sim_mean"], r["target"], r["miss_pct"]
        rows.append({"crop": r["crop"], "kind": r["target_kind"],
                     **{k: round(f[k], 3) for k in (*BOUNDS, "n_scale", "p_scale") if k in f},
                     "biomass": f"{s['biomass_t_ha']:.2f}/{t['biomass_t_ha']:g}",
                     "n_up": f"{s['n_up_kg_ha']:.0f}/{t['n_up_kg_ha']:g}",
                     "p_up": f"{s['p_up_kg_ha']:.1f}/{t['p_up_kg_ha']:g}",
                     **{f"miss_{k}": round(v, 2) for k, v in m.items()},
                     "fertn": round(s["fertn_kg_ha"]), "fertp": round(s["fertp_kg_ha"]),
                     "ok": r["within_tol"],
                     "at_bound": ",".join(k for k, v in r["at_bound"].items() if v) or "-"})
    card = pd.DataFrame(rows)
    print(card.to_string(index=False))

    stem = "check" if args.check else "biomass_calibration"
    card.to_csv(args.outdir / f"{stem}_scorecard.csv", index=False)
    pd.concat(per_year).to_csv(args.outdir / f"{stem}_per_year.csv", index=False)
    record = {"mode": mode, "window": [START + 1, START + YEARS], "tol_pct": args.tol,
              "reg": args.reg, "bounds": BOUNDS, "scale_bounds": SCALE_BOUNDS,
              "tmp_gap": TMP_GAP, "fert_events_max": mono.FERT_EVENTS_MAX,
              "targets": str(TARGETS.relative_to(ROOT)),
              "np_defaults": str(mono.NP_DEFAULT.relative_to(ROOT)),
              "runtime_s": round(time.time() - t0, 1), "applied": bool(args.apply),
              "results": results}
    (args.outdir / f"{stem}.json").write_text(json.dumps(record, indent=2))
    print(f"\nwrote {etc._rel(args.outdir / stem)}.json/_scorecard.csv/_per_year.csv"
          f"  ({record['runtime_s']:.0f} s)")

    if args.apply:
        crops = mono.load_biomass_fit()
        crops.update({r["plants_plt"]: r["fit"] for r in results})
        mono.BIOMASS_FITTED.write_text(json.dumps(
            {"source": "scripts/biomass_calibrate.py", "mode": mode,
             "window": record["window"], "targets": record["targets"],
             "np_defaults": record["np_defaults"],
             "note": "n_scale/p_scale multiply the DEFAULT BN1-3/BP1-3 in np_defaults",
             "crops": crops}, indent=2))
        print(f"wrote {mono.BIOMASS_FITTED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
