#!/usr/bin/env python3
"""Rerun the fitted ET calibration setup for every crop and keep the raw files.

``et_calibrate.py`` scores each trial in a scratch copy and deletes it, so the run
directories behind ``runs/et_calibration/et_calibration.json`` never survive. This rebuilds
the identical per-crop setup (same scoring window, same management, same irrigation windows),
overlays the fit from ``data/et_fitted.json``, runs once, and writes to ``runs/et_raw/<plt>/``:

    hru_wb_day.csv   raw daily HRU water balance (et, pet, eplant, esoil, irr, ...)
    plants.plt       input holding the fitted canopy parameters  (SWAT+ text format; no csv form)
    hydrology.hyd    input holding the fitted esco and the held epco / pet_co   (same)
    lum.dtl          input holding this crop's windowed irrigation decision table
    params.csv       the fitted plant knobs and hydrology values, pulled back out of those inputs

plus, at the top level:

    summary.csv           per crop-year: obs/sim ET, PBIAS, irrigation, transpiration fraction
    monthly.csv           monthly obs (eeMetric) vs sim ET, **January-December** — 36 rows/crop
    scorecard.csv         per crop: monthly R2, mean |PBIAS|, and pass/fail on R2>0.8, |PBIAS|<10
    irrigation_check.csv  the audit: every irrigated day must fall inside a sheet window
    fitted_params.csv     one row per crop: start -> fitted value, bounds, at-bound flags
    plant_params.csv      the full plants.plt row every crop actually ran with
    hydrology_params.csv  the full hydrology.hyd row every crop actually ran with
    et_fitted.json        copy of data/et_fitted.json, the source of truth for the fit
    et_days_mat.json      copy of data/et_days_mat.json (days_mat tuned to the sheet's PHU)
    biomass_fitted.json   copy of data/biomass_fitted.json (bm_e/tmp_* and the N/P factors)
    workbook_check.csv    every workbook column vs the value each crop ran with, with a flag

    uv run python scripts/et_raw.py
"""
from __future__ import annotations

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
from swat_gym.params import get_value  # noqa: E402
from swat_gym.printprt import trim  # noqa: E402
import port_crops  # noqa: E402

WORKBOOK = Path.home() / "Documents" / "Kimberly, Idaho" / "Crop Parameters and Plant Harvest dates.xlsx"

OUT = ROOT / "runs" / "et_raw"
KEEP = ("hru_wb_day.csv", "plants.plt", "hydrology.hyd", "lum.dtl", "calibration.cal",
        "mgt_out.txt")
SHEET_PHU = {"BARL": 1800, "CSIL": 1800, "POTA": 2000, "PTBN": 1000, "WWHT": 2000,
             "SGBT": 2300, "ALFA": None}


def _row(text: str, name: str, code: str) -> dict:
    """One named data row of a SWAT+ input as {column: value}, keyed by the header line."""
    lines = text.splitlines()
    header = lines[1].split()
    for line in lines[2:]:
        parts = line.split()
        if parts and parts[0] == name:
            return {"crop": code, **dict(zip(header, parts))}
    raise KeyError(f"row {name!r} not found")


def main() -> int:
    calib = json.loads((etc.OUT / "et_calibration.json").read_text())
    start, end = calib["calib_window"]
    window = calib.get("window", "full-year")
    shared, _ = mono.load_et_fit()
    sw_frac = shared.get("irr_sw_frac", mono.IRR_SW_FRAC)
    ref = pd.read_csv(etc.REF, parse_dates=["date"])
    work = OUT / "_work"
    rows, fitted, plant_rows, hyd_rows, check, monthly, scorecard, irrchk = (
        [], [], [], [], [], [], [], [])
    header = (etc.TIO / "plants.plt").read_text().splitlines()[1].split()
    sheet = pd.read_excel(WORKBOOK, sheet_name="SWAT Crop Parameters", nrows=7).set_index("CPNM")
    for code in etc.ORDER:
        plt = mono.CROPS[code][0]
        # Same builder and the same fitted irrigation trigger the calibration scored.
        tio = etc.CropFit._build(code, start, end - start, work / f"_tio_{plt}", sw_frac)
        mono.apply_et_fit(tio, plt)  # overlay data/et_fitted.json
        runner = FastRunner(txtinout=tio, keep={"hru_wb": {"daily"}}, editable=frozenset())
        # FastRunner trims csvout off; turn it back on so the engine writes hru_wb_day.csv.
        pp = runner.workdir / "print.prt"
        # mgt_out too: the harvest audit below reads the engine's own HARVEST records.
        pp.write_text(trim(pp.read_text(), {"hru_wb": {"daily"}}, csvout=True, mgtout=True))
        runner._pristine["print.prt"] = pp.read_bytes()
        runner.run()
        dest = OUT / plt
        dest.mkdir(parents=True, exist_ok=True)
        for name in KEEP:
            shutil.copy2(runner.workdir / name, dest / name)

        # Recompute the scored totals from the kept file, the same way the fit did.
        fit = etc.CropFit.__new__(etc.CropFit)
        fit.code, fit.plt = code, plt
        fit.ref = ref[ref["crop"] == plt].copy()
        fit.ref["yr"] = fit.ref["date"].dt.year
        fit.years = tuple(int(y) for y in sorted(fit.ref["yr"].unique()))
        fit.window = etc.scoring_window(code, window)
        fit.ref["mon"] = fit.ref["date"].dt.month
        fit.ref["md"] = etc._md(fit.ref["date"].dt.month, fit.ref["date"].dt.day)
        wb = runner.read("hru_wb_day.txt")
        sim = fit._totals(wb, "et")
        obs = fit._totals(fit.ref, "et_mm")
        m = fit._mask(wb)
        plants, hyd = (dest / "plants.plt").read_text(), (dest / "hydrology.hyd").read_text()
        params = {k: get_value(plants, "plants.plt", plt, k) for k in etc.PLANT_KNOBS}
        # phu_mat is not a plants.plt column; read back what calibration.cal actually set.
        params[mono.ET_PHU_KNOB] = float((dest / "calibration.cal").read_text()
                                         .splitlines()[3].split()[2])
        params.update({k: get_value(hyd, "hydrology.hyd", "hyd1", k)
                       for k in ("esco", "epco", "pet_co")})
        params["irr_sw_frac"] = sw_frac
        pd.DataFrame([{"crop": code, "plants_plt": plt, **params}]).to_csv(
            dest / "params.csv", index=False)

        # --- the irrigation audit: every irrigated day inside a sheet window, and, for
        # --- alfalfa, none in the week before a cutting. This is the item the collaborator
        # --- asked for, so it is checked against the engine's own output, not assumed.
        wins = mono.irrigation_windows(code)
        irr_days = wb[m & (wb["irr"] > 0)]
        outside = [(int(r.yr), int(r.jday)) for r in irr_days.itertuples()
                   if not any(a <= r.jday <= b for a, b in wins)]
        # The blackout is the seven days *ending on* the cutting, so the last irrigated day is
        # `cut - STOP_BEFORE_CUT_DAYS` and that day is legitimately inside the window. Starting
        # the blackout one day earlier double-counts each window's final day and reports four
        # violations for a run that has none.
        blackouts = ([(mono._doy(h) - mono.STOP_BEFORE_CUT_DAYS + 1, mono._doy(h))
                      for h in mono.CROPS[code][2]] if plt == "alfa" else [])
        in_blackout = [(int(r.yr), int(r.jday)) for r in irr_days.itertuples()
                       if any(a <= r.jday <= b for a, b in blackouts)]
        # The collaborator's second question (2026-09-25): is the cut actually taken while
        # irrigation is off? Each HARVEST the engine logged must be the last day of a blackout,
        # and every blackout in the scored years must carry exactly one.
        cuts_off, cuts_missing = [], []
        if plt == "alfa":
            ops = [ln.split() for ln in
                   (runner.workdir / "mgt_out.txt").read_text().splitlines()[3:]]
            cut_days = {(int(o[1]), pd.Timestamp(int(o[1]), int(o[2]), int(o[3])).dayofyear)
                        for o in ops if len(o) > 5 and o[5] == "HARVEST"}
            ends = {b for _, b in blackouts}
            cuts_off = sorted(c for c in cut_days if c[0] in fit.years and c[1] not in ends)
            cuts_missing = sorted((y, b) for y in fit.years for b in ends
                                  if (y, b) not in cut_days)
        irrchk.append({
            "crop": code, "plants_plt": plt,
            "windows": "; ".join(f"{mono._md_str(a)}-{mono._md_str(b)}" for a, b in wins),
            "blackouts": "; ".join(f"{mono._md_str(a)}-{mono._md_str(b)}"
                                  for a, b in blackouts) or "n/a (annual)",
            "irr_sw_frac": sw_frac,
            "irrigated_days_per_yr": round(len(irr_days) / len(fit.years), 1),
            "irr_mm_yr": round(float(wb[m]["irr"].sum()) / len(fit.years), 1),
            "days_outside_windows": len(outside),
            "days_in_cutting_blackout": len(in_blackout),
            "cuts_not_on_blackout_end": len(cuts_off),
            "blackouts_without_cut": len(cuts_missing),
            "status": ("ok" if not (outside or in_blackout or cuts_off or cuts_missing)
                       else "VIOLATION"),
        })

        cal = [r for r in calib["results"] if r["crop"] == code][0]
        fitted.append({"crop": code, "plants_plt": plt,
                       **{f"{k}_start": cal["start"][k] for k in etc.KNOBS},
                       **{f"{k}_fit": params[k] for k in etc.KNOBS},
                       **{f"{k}_at_bound": cal["at_bound"][k] for k in etc.KNOBS},
                       **{f"{k}_bounds": f"{lo:g}-{hi:g}"
                          for k, (lo, hi) in cal["bounds"].items()},
                       "esco_shared": params["esco"], "irr_sw_frac_shared": sw_frac,
                       "epco_fixed": params["epco"], "pet_co_fixed": params["pet_co"]})
        prow = _row(plants, plt, code)
        plant_rows.append(prow)
        hyd_rows.append(_row(hyd, "hyd1", code))
        # Since 2026-10-23 the N/P uptake columns run at the workbook's DEFAULT block x the
        # biomass fit's factor (collaborator's guide), and bm_e/tmp_* at the biomass fit.
        bfit = mono.load_biomass_fit().get(plt, {})
        np_expect = mono.biomass_text(plants, plt, bfit)
        for idx, (col, _) in sorted(port_crops.COLMAP.items()):
            wv, rv = float(sheet.loc[code, col]), float(prow[header[idx]])
            plt_col = header[idx]
            if plt_col in etc.KNOBS:
                status = f"fitted ({plt_col})"
            elif plt_col in mono.BIOMASS_KNOBS and plt_col in bfit:
                status = (f"biomass fit ({plt_col})" if abs(bfit[plt_col] - rv) < 1e-4
                          else "MISMATCH")
            elif plt_col in mono.N_COLS + mono.P_COLS:
                key = "n_scale" if plt_col in mono.N_COLS else "p_scale"
                ok = abs(get_value(np_expect, "plants.plt", plt, plt_col) - rv) < 1e-4
                status = (f"DEFAULT x {key} {bfit.get(key, 1.0):.3f}" if ok else "MISMATCH")
            else:
                status = "match" if abs(wv - rv) < 1e-4 else "MISMATCH"
            check.append({"crop": code, "sheet_col": col, "plants_plt_col": plt_col,
                          "sheet": wv, "ran_with": rv, "status": status})
        check.append({"crop": code, "sheet_col": "heat_units",
                      "plants_plt_col": "phu_mat (calibration.cal)",
                      "sheet": SHEET_PHU.get(code), "ran_with": params[mono.ET_PHU_KNOB],
                      "status": ("fitted (phu_mat)" if code != "ALFA"
                                 else "fitted (phu_mat; sheet 'default' = engine default)")})

        # --- monthly, January-December: 12 months x 3 years = 36 points per crop
        s_m = wb[m].groupby(["yr", "mon"])["et"].sum()
        o_m = fit.ref[fit._mask(fit.ref)].groupby(["yr", "mon"])["et_mm"].sum()
        idx = s_m.index.intersection(o_m.index)
        for (yy, mm) in sorted(idx):
            monthly.append({"crop": code, "plants_plt": plt, "yr": yy, "mon": mm,
                            "obs_mm": o_m.loc[(yy, mm)], "sim_mm": s_m.loc[(yy, mm)]})
        r2 = etc.r_squared(s_m.loc[idx].to_numpy(), o_m.loc[idx].to_numpy())
        pbias = {y: 100.0 * (sim[y] - obs[y]) / obs[y] for y in fit.years}
        mean_abs = float(np.mean([abs(v) for v in pbias.values()]))
        et_tot = float(wb[m]["et"].sum())
        scorecard.append({
            "crop": code, "plants_plt": plt, "n_monthly": int(len(idx)),
            "r2_monthly": round(r2, 4), "mean_abs_pbias_pct": round(mean_abs, 2),
            "meets_r2_gt_0.8": bool(r2 > 0.8), "meets_abs_pbias_lt_10": bool(mean_abs < 10.0),
            "irr_mm_yr": round(float(wb[m]["irr"].sum()) / len(fit.years), 1),
            "irr_within_measured_ceiling": bool(
                float(wb[m]["irr"].sum()) / len(fit.years)
                <= (calib.get("irr_ceiling_mm_yr") or np.inf)),
            "frac_eplant": round(float(wb[m]["eplant"].sum()) / et_tot, 3) if et_tot else None,
            "obs_mm_yr": round(float(np.mean(list(obs.values()))), 1),
            "sim_mm_yr": round(float(np.mean(list(sim.values()))), 1),
        })
        for y in fit.years:
            yr_mask = m & (wb["yr"] == y)
            rows.append({"crop": code, "plants_plt": plt, "year": y,
                         "obs_mm": obs[y], "sim_mm": sim[y], "pbias_pct": pbias[y],
                         "irr_mm": float(wb[yr_mask]["irr"].sum()),
                         "pet_mm": float(wb[yr_mask]["pet"].sum()),
                         "eplant_mm": float(wb[yr_mask]["eplant"].sum()),
                         "esoil_mm": float(wb[yr_mask]["esoil"].sum()), **params})
        print(f"{code:5s} -> {dest.relative_to(ROOT)}  R2 {r2:5.3f}  "
              f"|PBIAS| {mean_abs:5.1f} %  irr {scorecard[-1]['irr_mm_yr']:4.0f} mm/yr  "
              + "  ".join(f"{y}:{pbias[y]:+6.1f}%" for y in fit.years))

    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False, float_format="%.4f")
    monthly_df = pd.DataFrame(monthly)
    monthly_df.to_csv(OUT / "monthly.csv", index=False, float_format="%.3f")
    # 12 months x 3 years x 7 crops. Asserted because this file is what et_plots.py draws and
    # what the collaborator's 36-points-per-crop request is delivered as: when the write was
    # accidentally dropped (2026-09-24) the stale season-window file was left in place and the
    # page rendered 4-8 months per crop while the scorecard beside it correctly said n = 36.
    if window == "full-year":
        per_crop = monthly_df.groupby("crop").size()
        if not (per_crop == 36).all():
            raise RuntimeError(f"monthly.csv must hold 36 rows per crop, got "
                               f"{per_crop.to_dict()}")
    pd.DataFrame(scorecard).to_csv(OUT / "scorecard.csv", index=False)
    pd.DataFrame(irrchk).to_csv(OUT / "irrigation_check.csv", index=False)
    pd.DataFrame(fitted).to_csv(OUT / "fitted_params.csv", index=False)
    pd.DataFrame(plant_rows).to_csv(OUT / "plant_params.csv", index=False)
    pd.DataFrame(hyd_rows).to_csv(OUT / "hydrology_params.csv", index=False)
    shutil.copy2(etc.FITTED, OUT / "et_fitted.json")
    if mono.ET_DAYS_MAT.is_file():
        shutil.copy2(mono.ET_DAYS_MAT, OUT / "et_days_mat.json")
    if mono.BIOMASS_FITTED.is_file():
        shutil.copy2(mono.BIOMASS_FITTED, OUT / "biomass_fitted.json")
    pd.DataFrame(check).to_csv(OUT / "workbook_check.csv", index=False)

    bad = [c for c in check if c["status"] == "MISMATCH"]
    print(f"\nworkbook check: {len(bad)} mismatches" + (f" -> {bad}" if bad else "")
          + f" ({sum(1 for c in check if str(c['status']).startswith('fitted'))} ET-fitted, "
          f"{sum(1 for c in check if str(c['status']).startswith(('biomass', 'DEFAULT')))} "
          f"biomass/N-P columns)")
    viol = [r["crop"] for r in irrchk if r["status"] == "VIOLATION"]
    print(f"irrigation window audit: {'ok for all 7 crops' if not viol else f'VIOLATION {viol}'}")
    passed = [r["crop"] for r in scorecard
              if r["meets_r2_gt_0.8"] and r["meets_abs_pbias_lt_10"]]
    print(f"meets R2>0.8 and |PBIAS|<10 %: {', '.join(passed) or 'none'} "
          f"({len(passed)}/{len(scorecard)})")
    shutil.rmtree(work, ignore_errors=True)
    print(f"wrote {(OUT / 'scorecard.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
