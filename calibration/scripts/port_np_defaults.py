#!/usr/bin/env python3
"""Port the crop workbook's ``DEFAULT`` N/P uptake block to ``data/crop_np_default.csv``.

The ``SWAT Crop Parameters`` sheet carries two blocks per crop: the collaborator's calibrated
values (rows 2-8, already in ``data/crop_params_swat.csv``) and, under a ``DEFAULT`` marker,
the stock SWAT crop-database values (rows 11-17). The collaborator's biomass/nutrient guide
(2026-10-22) says **not** to use the calibrated BN1-3/BP1-3, but to start from the defaults
and scale each crop's three values by one common factor to its uptake target. This file is
that starting point; ``scripts/biomass_calibrate.py`` fits the factor and
``monoculture.apply_biomass_fit`` applies ``default x factor``.

The defaults match the SWAT+ rev-62 ``plants.plt`` shipped database for every crop except
potato, whose BN1 is 0.055 here and 0.035 in ``rev62_template``; the workbook is the
collaborator's own reference, so it wins.

Idempotent; re-run after any workbook update.

    uv run python scripts/port_np_defaults.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = (Path.home() / "Documents" / "Kimberly, Idaho"
            / "Crop Parameters and Plant Harvest dates.xlsx")
SHEET = "SWAT Crop Parameters"
OUT = ROOT / "data" / "crop_np_default.csv"

#: Workbook code -> plants.plt name, as in ``port_dates.NAMES``.
PLANTS = {"ALFA": "alfa", "BARL": "barl", "CSIL": "corn", "POTA": "pota",
          "PTBN": "ptbn", "WWHT": "wwht", "SGBT": "sgbt"}
COLS = ["BN1", "BN2", "BN3", "BP1", "BP2", "BP3"]


def port(workbook: Path) -> pd.DataFrame:
    raw = pd.read_excel(workbook, sheet_name=SHEET, header=0)
    marker = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "DEFAULT"]
    if len(marker) != 1:
        raise SystemExit(f"{SHEET}: expected one DEFAULT marker row, found {len(marker)}")
    block = raw.loc[marker[0] + 1:].dropna(subset=["CPNM"])
    block = block[block["CPNM"].isin(PLANTS)].drop_duplicates("CPNM")
    missing = set(PLANTS) - set(block["CPNM"])
    if missing:
        raise SystemExit(f"{SHEET}: DEFAULT block has no row for {sorted(missing)}")
    df = block[["CPNM", *COLS]].rename(columns={"CPNM": "crop"}).copy()
    df.insert(1, "plants_plt", df["crop"].map(PLANTS))
    df[COLS] = df[COLS].astype(float)
    return df.reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", type=Path, default=WORKBOOK)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not args.workbook.is_file():
        raise SystemExit(f"missing workbook {args.workbook}")
    df = port(args.workbook)
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))
    print(f"\nwrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
