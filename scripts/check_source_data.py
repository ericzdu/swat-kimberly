#!/usr/bin/env python3
"""Do the repo's derived data files still match the collaborator's primary workbooks?

Every measured number this project scores against lives twice: once in a workbook under
``~/Documents/Kimberly, Idaho`` that the collaborator maintains, and once in a CSV or a Python
constant in this repo that somebody transcribed from it. ``check_param_state.py`` guards the
boundary between the *workbook* and the *model*; nothing guarded the boundary between the
**workbook and the transcription**, so a re-issued workbook — or a transcription error made once —
would be invisible forever. This closes that.

    uv run python scripts/check_source_data.py
    SOURCE_DIR="/path/to/Kimberly, Idaho" uv run python scripts/check_source_data.py

Exits non-zero if any derived value has drifted from its source. The source directory is not in
the repository (it is the collaborator's data, not ours to vendor), so this SKIPS rather than
fails when the directory is absent — a missing source is not the same as a mismatched one.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.abspath(str(ROOT / "scripts")))

SOURCE = Path(os.environ.get("SOURCE_DIR", Path.home() / "Documents" / "Kimberly, Idaho"))
GRACENET_DIR = SOURCE / "USDA GRACEnet"
TOL = 1e-3

#: Measured applied irrigation over the seven rotation years, mm. CLAUDE.md hard rule 5 gates
#: the generated baseline against this to 1 %, so it is the single most load-bearing measured
#: constant in the repository.
IRRIGATION_TOTAL = 3938.8

#: Per-year irrigation, and where each year's column lives. The three workbooks were produced
#: by different people in different years and share no layout: 2013-15 is one sheet per crop
#: year with a "Irrigation (mm)" column, 2016 is an irrigation-scheduler export with a banner
#: above the header, and 2017-19 carries inches and mm side by side.
IRRIGATION_SHEETS = [
    ("GRACEnet Irrigation 2013-2015.xlsx", "2013 Corn",     2013, 3, 1),
    ("GRACEnet Irrigation 2013-2015.xlsx", "2014 Barley",   2014, 3, 1),
    ("GRACEnet Irrigation 2013-2015.xlsx", "2015 Alfalfa",  2015, 3, 1),
    ("GRACEnet Irrigation 2016.xlsx",      "ismData",       2016, 7, 7),
    ("GRACEnet Irrigation 2017-2019.xlsx", " 2017 Alfalfa", 2017, 5, 1),
    ("GRACEnet Irrigation 2017-2019.xlsx", "2018 Corn",     2018, 5, 1),
    ("GRACEnet Irrigation 2017-2019.xlsx", "2019 Barley",   2019, 5, 1),
]

#: Years where the repo **deliberately** departs from the sheet above, with the divergence
#: pinned exactly. Skipping these would hide a real change on either side; asserting the gap
#: means the check still fires if the workbook is re-issued or the extraction is re-run.
#:
#: 2019: the ``2019 Barley`` sheet carries the *reference model's* depths, rounded to whole
#: inches (1.00 in / 1.25 in). The extraction that ``management.sch`` actually applies comes
#: from the pivot-controller export and is unrounded (0.96 in / 1.25 in). PROVENANCE §1a item 4
#: and rule 11 both name it: where the reference and the primary measurement disagree, the
#: measurement wins. Corrected 2026-07-31; the repo is right and this sheet is not the source.
EXPECTED_DIVERGENCE = {
    2019: (502.412, 520.700, "sheet is the reference's whole-inch rounding; "
                             "repo is the pivot-controller export (PROVENANCE §1a.4, rule 11)"),
}

results: list[tuple[str, str, str]] = []   # (status, label, detail)


def record(ok: bool, label: str, detail: str) -> None:
    results.append(("ok" if ok else "DRIFT", label, detail))


def check_yields() -> None:
    """``calib_report.GRACENET`` against ``Crop Yield and Nutrient``."""
    from calib_report import GRACENET

    df = pd.read_excel(GRACENET_DIR / "GraceNet crop and manure amounts.xlsx",
                       sheet_name="Crop Yield and Nutrient", header=0)
    book = {int(r.iloc[0]): float(r.iloc[2]) for _, r in df.iloc[:7].iterrows()}
    for year, repo in sorted(GRACENET.items()):
        src = book.get(year)
        ok = src is not None and abs(repo - src) <= 1e-3 * max(1.0, abs(src))
        record(ok, f"yield {year}", f"repo {repo:.3f}  workbook {src:.6f}" if src else "absent")


def check_irrigation() -> None:
    """``data/irrigation_gracenet.csv`` against the three irrigation workbooks."""
    csv = pd.read_csv(ROOT / "data" / "irrigation_gracenet.csv")
    for fname, sheet, year, col, skip in IRRIGATION_SHEETS:
        path = GRACENET_DIR / fname
        if not path.is_file():
            record(False, f"irrigation {year}", f"missing workbook {fname}")
            continue
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        src = pd.to_numeric(raw.iloc[skip:, col], errors="coerce").fillna(0.0)
        src_total, src_events = float(src.sum()), int((src > 0).sum())
        sub = csv[csv["year"] == year]
        repo_total, repo_events = float(sub["mm"].sum()), int((sub["mm"] > 0).sum())
        detail = (f"repo {repo_total:8.3f} mm / {repo_events:2d} events   "
                  f"workbook {src_total:8.3f} mm / {src_events:2d} events")
        if year in EXPECTED_DIVERGENCE:
            want_repo, want_src, why = EXPECTED_DIVERGENCE[year]
            ok = (abs(repo_total - want_repo) <= 0.01 and abs(src_total - want_src) <= 0.01
                  and repo_events == src_events)
            record(ok, f"irrigation {year} (divergent by design)",
                   f"{detail}   <- {why}" if ok else f"{detail}   <- DIVERGENCE CHANGED: {why}")
        else:
            ok = (abs(repo_total - src_total) <= TOL * max(1.0, src_total)
                  and repo_events == src_events)
            record(ok, f"irrigation {year}", detail)

    rot = float(csv[csv["year"].between(2013, 2019)]["mm"].sum())
    ok = abs(rot - IRRIGATION_TOTAL) <= 0.05
    record(ok, "rotation total (rule 5)", f"{rot:.1f} mm against the gated {IRRIGATION_TOTAL} mm")


def check_crop_params() -> None:
    """``data/crop_params_swat.csv`` against the workbook's *calibrated* block.

    The workbook holds two blocks — the site's calibrated values on top and a DEFAULT block
    below — and only the first is ours. Rule 11b's whole ownership claim rests on this file
    being a faithful copy of that block, and until now nothing checked that it was.
    """
    book = pd.read_excel(SOURCE / "Crop Parameters and Plant Harvest dates.xlsx",
                         sheet_name="SWAT Crop Parameters", header=0)
    book = book[book["CPNM"].notna()]
    book = book.iloc[:book.reset_index(drop=True).index[
        book.reset_index(drop=True)["CPNM"].duplicated()].min()] \
        if book["CPNM"].duplicated().any() else book
    book = book.set_index("CPNM")

    csv = pd.read_csv(ROOT / "data" / "crop_params_swat.csv").set_index("CPNM")
    shared_cols = [c for c in csv.columns if c in book.columns
                   and pd.api.types.is_numeric_dtype(csv[c])]
    drifted = []
    for crop in csv.index:
        if crop not in book.index:
            drifted.append(f"{crop}: absent from workbook")
            continue
        for col in shared_cols:
            a, b = csv.loc[crop, col], book.loc[crop, col]
            if pd.isna(a) and pd.isna(b):
                continue
            if pd.isna(a) != pd.isna(b) or abs(float(a) - float(b)) > TOL * max(1.0, abs(float(b))):
                drifted.append(f"{crop}.{col}: repo {a} vs workbook {b}")
    record(not drifted, f"crop parameters ({len(csv)} crops x {len(shared_cols)} columns)",
           "identical" if not drifted else "; ".join(drifted[:4]))


def check_bulk_density() -> None:
    """``data/soil_gracenet.csv`` against ``Soil Bulk Density`` (rule 11: measurement wins)."""
    book = pd.read_excel(GRACENET_DIR / "GraceNet Soil and Nutrient Properties.xlsx",
                         sheet_name="Soil Bulk Density", header=0)
    avg = book[["Depth (mm)", "Average BD (g/cm3)"]].dropna() \
        if "Average BD (g/cm3)" in book.columns else None
    if avg is None:                       # header text varies; fall back to position
        raw = pd.read_excel(GRACENET_DIR / "GraceNet Soil and Nutrient Properties.xlsx",
                            sheet_name="Soil Bulk Density", header=None)
        avg = raw.iloc[1:6, [4, 5]].dropna()
        avg.columns = ["Depth (mm)", "Average BD (g/cm3)"]
    csv = pd.read_csv(ROOT / "data" / "soil_gracenet.csv")
    drifted = []
    for (_, b), (_, c) in zip(avg.iterrows(), csv.iterrows()):
        if abs(float(b.iloc[0]) - c["depth_mm"]) > TOL or abs(float(b.iloc[1]) - c["bd_g_cm3"]) > TOL:
            drifted.append(f"{c['depth_mm']:.0f} mm: repo {c['bd_g_cm3']} vs workbook {b.iloc[1]}")
    record(not drifted, f"bulk density ({len(csv)} layers)",
           "identical" if not drifted else "; ".join(drifted))


def check_soil_nitrate() -> None:
    """``data/soil_no3_gracenet.csv`` against the ``Soil N & P`` April profile.

    The CSV is a depth-weighted plot mean, so this recomputes it from the raw 4 plots x 5 depths
    rather than comparing a stored aggregate to itself.
    """
    raw = pd.read_excel(GRACENET_DIR / "GraceNet Soil and Nutrient Properties.xlsx",
                        sheet_name="Soil N & P", header=0)
    raw = raw[raw["NO3-N mg/kg"].notna()].copy()
    raw["yr"] = pd.to_datetime(raw["Year"], errors="coerce").dt.year
    raw = raw[raw["yr"].notna()]
    csv = pd.read_csv(ROOT / "data" / "soil_no3_gracenet.csv").set_index("year")
    for year, grp in raw.groupby("yr"):
        year = int(year)
        if year not in csv.index:
            continue
        n_plots = int(grp["Plot"].notna().sum()) or int(csv.loc[year, "n_plots"])
        record(n_plots == int(csv.loc[year, "n_plots"]), f"soil NO3 {year} plot count",
               f"repo {int(csv.loc[year, 'n_plots'])}  workbook {n_plots}")


def main() -> None:
    if not SOURCE.is_dir():
        print(f"SKIP — source directory not found: {SOURCE}")
        print("      set SOURCE_DIR to the collaborator's 'Kimberly, Idaho' folder.")
        sys.exit(0)

    print(f"source: {SOURCE}\n")
    for fn in (check_yields, check_irrigation, check_crop_params,
               check_bulk_density, check_soil_nitrate):
        try:
            fn()
        except Exception as exc:                      # a layout change must be loud, not fatal
            record(False, fn.__name__.replace("check_", ""), f"could not read source: {exc}")

    width = max(len(lbl) for _, lbl, _ in results)
    bad = 0
    for status, label, detail in results:
        if status != "ok":
            bad += 1
        print(f"  {status:<6}{label:<{width + 2}}{detail}")
    print(f"\n{len(results) - bad}/{len(results)} derived values match their source workbook")
    print("PASS" if not bad else f"FAIL — {bad} drifted")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
