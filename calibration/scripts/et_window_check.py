#!/usr/bin/env python3
"""What is actually limiting the ET fit: the irrigation *trigger*, or the irrigation *calendar*?

Runs every crop twice at the fitted parameters and compares:

``sheet``
    The calibrated setup — irrigate inside the workbook's ``irrigation start``/``end`` window
    (alfalfa: its four cutting windows) when soil water is below the fitted fraction of field
    capacity.
``year-round``
    The same soil-water trigger with **the dates removed** — irrigate whenever the soil is dry,
    any day of the year, growing or not. Physically unrealistic; it is the counterfactual that
    measures how much of the remaining gap lives *outside* the sheet's irrigation season.

and decomposes each crop's annual obs-sim ET gap into the part inside the irrigation window and
the part outside it.

Why this exists: the 2026-09-24 fit bottoms out near 18 % mean |PBIAS| whatever the trigger is
set to (the full 0.20-0.95 range of ``irr_sw_frac`` moves it about one point). That says the
binding constraint is no longer how wet the soil is kept, but the months in which the model is
allowed to irrigate at all — and eeMetric reports substantial ET on these fields after harvest
and before planting, when the sheet says irrigation is off and the model therefore has bare,
dry soil and no canopy. This script is the evidence for that claim, and the number to put in
front of the collaborator when asking what those fields were doing out of season.

    uv run python scripts/et_window_check.py     # -> runs/et_calibration/window_counterfactual.csv
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import et_calibrate as etc  # noqa: E402
import monoculture as mono  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402

#: The counterfactual table: the fitted soil-water trigger with no jday condition at all.
NO_WINDOW = """
name                     conds      alts      acts       !counterfactual: no date window
irr_nowin                    1         1         1
var                        obj   obj_num           lim_var            lim_op     lim_const      alt1
soil_water                 hru         0                fc                 -{sw:>14.5f}         <
act_typ                    obj   obj_num              name            option         const        const2                fp  outcome
irr_demand                 hru         0         sprinkler     sprinkler_ilm{mm:>14.5f}      20.00000             unlim  y
"""


def no_window_dtl(base: str, sw_frac: float) -> tuple[str, str]:
    lines = base.splitlines(keepends=True)
    lines[1] = f"{int(lines[1].strip()) + 1}\n"
    return ("".join(lines).rstrip("\n") + "\n"
            + NO_WINDOW.format(sw=sw_frac, mm=mono.IRR_MM)), "irr_nowin"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", type=Path, default=etc.OUT)
    args = ap.parse_args()

    calib = json.loads((etc.OUT / "et_calibration.json").read_text())
    start, end = calib["calib_window"]
    window = calib.get("window", "full-year")
    shared, crops_fit = mono.load_et_fit()
    sw_frac = shared.get("irr_sw_frac", mono.IRR_SW_FRAC)
    ref = pd.read_csv(etc.REF, parse_dates=["date"])
    work = args.outdir / "_work_win"
    work.mkdir(parents=True, exist_ok=True)

    rows = []
    hdr = (f"{'crop':<6}{'variant':<12}{'R2':>7}{'|PBIAS|':>9}{'irr':>7}"
           f"{'gap in win':>12}{'gap out':>9}")
    print(hdr)
    print("-" * len(hdr))
    for code in etc.ORDER:
        plt = mono.CROPS[code][0]
        tio = etc.CropFit._build(code, start, end - start, work / f"_tio_{plt}", sw_frac)
        mono.apply_et_fit(tio, plt)
        # Must mirror CropFit._dtl_base exactly: prepare_dtl -> with_cutting_dtl ->
        # build_irrigation_dtl. Leaving with_cutting_dtl out writes a lum.dtl that lacks
        # the cutting table while management.sch still names it, and the engine segfaults
        # in year 1 with a backtrace that says nothing (hit 2026-10-02).
        base = mono.with_cutting_dtl(
            mono.prepare_dtl((etc.TIO / "lum.dtl").read_text()), code)
        sheet_dtl, _ = mono.build_irrigation_dtl(base, code, sw_frac)
        nowin_dtl, nowin_name = no_window_dtl(base, sw_frac)
        sch = (tio / "management.sch").read_text()
        sch_nowin = sch.replace(f"irr_win_{plt}", nowin_name)
        assert nowin_name in sch_nowin

        fit = etc.CropFit.__new__(etc.CropFit)
        fit.code, fit.plt = code, plt
        fit.ref = ref[ref["crop"] == plt].copy()
        fit.ref["yr"] = fit.ref["date"].dt.year
        fit.ref["mon"] = fit.ref["date"].dt.month
        fit.ref["md"] = etc._md(fit.ref["date"].dt.month, fit.ref["date"].dt.day)
        fit.years = tuple(int(y) for y in sorted(fit.ref["yr"].unique()))
        fit.window = etc.scoring_window(code, window)
        obs = fit._totals(fit.ref, "et_mm")

        wins = mono.irrigation_windows(code)
        runner = FastRunner(txtinout=tio, keep={"hru_wb": {"daily"}},
                            editable=frozenset({"management.sch", "lum.dtl"}))
        for variant, files in (("sheet", {"management.sch": sch, "lum.dtl": sheet_dtl}),
                               ("year-round", {"management.sch": sch_nowin,
                                               "lum.dtl": nowin_dtl})):
            runner.run(files)
            wb = runner.read("hru_wb_day.txt")
            m = fit._mask(wb)
            sim = fit._totals(wb, "et")
            s = wb[m].groupby(["yr", "mon"])["et"].sum()
            o = fit.ref[fit._mask(fit.ref)].groupby(["yr", "mon"])["et_mm"].sum()
            idx = s.index.intersection(o.index)
            r2 = etc.r_squared(s.loc[idx].to_numpy(), o.loc[idx].to_numpy())
            pbias = [abs(100.0 * (sim[y] - obs[y]) / obs[y]) for y in fit.years]

            # Split the daily obs-sim gap by whether the day falls in an irrigation window.
            in_win = wb[m]["jday"].isin(
                [j for a, b in wins for j in range(a, b + 1)])
            ref_d = fit.ref[fit._mask(fit.ref)].copy()
            ref_d["jday"] = ref_d["date"].dt.dayofyear
            ref_in = ref_d["jday"].isin([j for a, b in wins for j in range(a, b + 1)])
            n_yr = len(fit.years)
            gap_in = (ref_d[ref_in]["et_mm"].sum() - wb[m][in_win]["et"].sum()) / n_yr
            gap_out = (ref_d[~ref_in]["et_mm"].sum() - wb[m][~in_win]["et"].sum()) / n_yr

            rows.append({"crop": code, "plants_plt": plt, "variant": variant,
                         "r2_monthly": round(r2, 4),
                         "mean_abs_pbias_pct": round(float(np.mean(pbias)), 2),
                         "irr_mm_yr": round(float(wb[m]["irr"].sum()) / n_yr, 1),
                         "obs_mm_yr": round(float(np.mean(list(obs.values()))), 1),
                         "sim_mm_yr": round(float(np.mean(list(sim.values()))), 1),
                         "gap_inside_window_mm_yr": round(float(gap_in), 1),
                         "gap_outside_window_mm_yr": round(float(gap_out), 1)})
            print(f"{code:<6}{variant:<12}{r2:>7.3f}{np.mean(pbias):>9.1f}"
                  f"{rows[-1]['irr_mm_yr']:>7.0f}{gap_in:>12.0f}{gap_out:>9.0f}", flush=True)
        runner.close()

    df = pd.DataFrame(rows)
    out = args.outdir / "window_counterfactual.csv"
    df.to_csv(out, index=False)
    sheet_r = df[df.variant == "sheet"]
    nowin_r = df[df.variant == "year-round"]
    print(f"\nmean |PBIAS|: sheet windows {sheet_r.mean_abs_pbias_pct.mean():.1f} %, "
          f"year-round {nowin_r.mean_abs_pbias_pct.mean():.1f} %")
    print(f"mean irrigation: sheet {sheet_r.irr_mm_yr.mean():.0f} mm/yr, "
          f"year-round {nowin_r.irr_mm_yr.mean():.0f} mm/yr "
          f"(measured practice 418-758)")
    # Not a share: the per-crop gaps carry both signs (several crops over-predict inside the
    # window and under-predict outside it), so summing them and dividing cancels real error
    # against real error and can exceed 100 %. Report the magnitudes and the worst crop instead.
    worst = sheet_r.loc[sheet_r.gap_outside_window_mm_yr.abs().idxmax()]
    print(f"mean |obs-sim| gap, sheet windows: {sheet_r.gap_inside_window_mm_yr.abs().mean():.0f} "
          f"mm/yr inside the irrigation window, "
          f"{sheet_r.gap_outside_window_mm_yr.abs().mean():.0f} mm/yr outside it")
    print(f"largest out-of-window gap: {worst.crop} {worst.gap_outside_window_mm_yr:+.0f} mm/yr "
          f"(its |PBIAS| falls {worst.mean_abs_pbias_pct:.1f} -> "
          f"{nowin_r.set_index('crop').loc[worst.crop, 'mean_abs_pbias_pct']:.1f} % and R2 rises "
          f"{worst.r2_monthly:.3f} -> "
          f"{nowin_r.set_index('crop').loc[worst.crop, 'r2_monthly']:.3f} when the dates are "
          f"removed, so its shortfall is out-of-season ET the sheet's calendar forbids)")
    shutil.rmtree(work, ignore_errors=True)
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
