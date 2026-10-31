#!/usr/bin/env python3
"""Extract the OpenET (eeMetric) ET reference into one tidy CSV.

Source: ``~/Documents/Kimberly, Idaho/ET Calibration/<Crop>_metric_rev693fixed.xlsx``, one
workbook per crop, each carrying sheets ``OpenET 2020`` / ``2021`` / ``2022``. Every sheet has
the same five columns::

    Date | eeMetric ET | ETmm | Ensemble cumulative | SWAT cumulative

``eeMetric ET`` is the **measurement** (remote-sensing ET, mm/day). ``ETmm`` is whatever SWAT
run the collaborator had loaded when the workbook was saved — it is *not* our model and is
deliberately not carried over here, so a stale column can never be mistaken for a target.

Each crop-year sits at a **different field location** (the sheets record lat/lon in a trailing
column, and no two years share one). So a crop's reference is three independent crop-years,
not a three-year time series at one site. That is why the fit in ``et_calibrate.py`` scores the
mean absolute bias *across* years rather than pooling all days into one regression.

    uv run python scripts/et_reference.py            # -> data/et_reference.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ET_DIR = Path.home() / "Documents" / "Kimberly, Idaho" / "ET Calibration"
OUT = ROOT / "data" / "et_reference.csv"

#: Workbook basename -> plants.plt name, matching ``monoculture.CROPS``.
WORKBOOK = {
    "Alfalfa": "alfa",
    "Barley": "barl",
    "Corn": "corn",
    "Potato": "pota",
    "Beans": "ptbn",
    "Wheat": "wwht",
    "Sugarbeet": "sgbt",
}

YEARS = (2020, 2021, 2022)


def _location(df: pd.DataFrame) -> str:
    """Pull 'Field location: 42.5444, -114.3182' out of the trailing annotation column."""
    for col in df.columns:
        if "Field location" in str(col):
            return str(col).split(":", 1)[1].strip()
    return ""


def read_crop(path: Path, crop: str) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    frames = []
    for yr in YEARS:
        sheet = next((s for s in xl.sheet_names if s.strip().lower() == f"openet {yr}"), None)
        if sheet is None:
            raise KeyError(f"{path.name}: no 'OpenET {yr}' sheet (have {xl.sheet_names})")
        df = xl.parse(sheet)
        loc = _location(df)
        out = pd.DataFrame({
            "date": pd.to_datetime(df["Date"], errors="coerce"),
            "et_mm": pd.to_numeric(df["eeMetric ET"], errors="coerce"),
        }).dropna()
        # Guard against a sheet that silently carries another year's dates.
        if not (out["date"].dt.year == yr).all():
            bad = sorted(set(out["date"].dt.year) - {yr})
            raise ValueError(f"{path.name} '{sheet}' contains years {bad}, expected {yr}")
        out.insert(0, "crop", crop)
        out.insert(1, "year", yr)
        out["location"] = re.sub(r"\s+", " ", loc)
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--et-dir", type=Path, default=ET_DIR)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not args.et_dir.is_dir():
        print(f"ET reference folder not found: {args.et_dir}", file=sys.stderr)
        return 1

    frames = []
    for book, crop in WORKBOOK.items():
        hits = list(args.et_dir.glob(f"{book}_*.xlsx"))
        if not hits:
            print(f"  ! no workbook for {book}", file=sys.stderr)
            continue
        df = read_crop(hits[0], crop)
        frames.append(df)
        gs = df[df["date"].dt.month.between(4, 10)]
        tot = df.groupby("year")["et_mm"].sum()
        gst = gs.groupby("year")["et_mm"].sum()
        print(f"{crop:<5} {hits[0].name:<34} "
              + "  ".join(f"{y}: ann {tot[y]:6.1f} / AprOct {gst[y]:6.1f} mm" for y in YEARS))

    all_df = pd.concat(frames, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(args.out, index=False)
    print(f"\n{len(all_df)} daily rows, {all_df['crop'].nunique()} crops x {len(YEARS)} years "
          f"-> {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
