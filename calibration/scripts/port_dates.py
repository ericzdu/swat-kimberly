#!/usr/bin/env python3
"""Port the ``Plant Harvest Dates`` sheet to ``data/plant_harvest_dates.csv``.

Until 2026-09-24 the emerge and harvest dates lived hand-typed in ``monoculture.CROPS`` and
the sheet's **irrigation start / irrigation end** columns were not read at all — which is why
the model irrigated on plant water stress alone and never saw the pre-emergence start dates
(corn 5/25 against a 6/1 emergence) or the stop-before-harvest dates. Both now come from the
sheet through this file, so nothing is transcribed twice.

What the sheet carries, per crop: heat units to maturity (consumed by ``et_phu.py``), emerge
date, up to four harvest dates, and the irrigation window. Its year (2024) is a carrier for
month/day only — every date is used as month/day in every simulated year.

The sheet's own footnote is the specification for alfalfa and is implemented in
:func:`monoculture.irrigation_windows`, not here:

    "Alfalfa irrigation is stopped one week before harvesting and restarted the day after.
     Harvest only operation set to 1 HARVEFF and 0.95 HI_OVR"

That footnote's convention also describes every annual: each crop's ``irrigation end`` already
sits 7-16 days before its harvest date, so the rule is the sheet's throughout and the alfalfa
row is only the case where it has to be applied four times.

Idempotent; re-run after any workbook update.

    uv run python scripts/port_dates.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = (Path.home() / "Documents" / "Kimberly, Idaho"
            / "Crop Parameters and Plant Harvest dates.xlsx")
SHEET = "Plant Harvest Dates"
OUT = ROOT / "data" / "plant_harvest_dates.csv"

#: Sheet crop label -> (workbook code, plants.plt name). The sheet's alfalfa row carries the
#: footnote marker in its label.
NAMES = {
    "Alfalfa": ("ALFA", "alfa"),
    "Spring Barley": ("BARL", "barl"),
    "Corn Silage": ("CSIL", "corn"),
    "Potato": ("POTA", "pota"),
    "Pinto Beans": ("PTBN", "ptbn"),
    "Winter Wheat": ("WWHT", "wwht"),
    "Sugarbeet": ("SGBT", "sgbt"),
}

DATE_COLS = ["emerge date", "harvest date 1", "harvest date 2", "harvest date 3",
             "harvest date 4", "irrigation start", "irrigation end"]
RENAME = {"emerge date": "emerge", "harvest date 1": "harv1", "harvest date 2": "harv2",
          "harvest date 3": "harv3", "harvest date 4": "harv4",
          "irrigation start": "irr_start", "irrigation end": "irr_end"}


def _md(v) -> str:
    """A sheet cell as ``MM-DD``, or "" when the cell is empty."""
    if pd.isna(v):
        return ""
    ts = pd.Timestamp(v)
    return f"{ts.month:02d}-{ts.day:02d}"


def port(workbook: Path) -> pd.DataFrame:
    raw = pd.read_excel(workbook, sheet_name=SHEET)
    label = raw.columns[1]          # the long footnote-bearing column holds the crop label
    rows = []
    for _, r in raw.iterrows():
        name = str(r[label]).strip().rstrip("*")
        if name not in NAMES:
            continue                # blank spacer rows and the footnote row
        code, plt = NAMES[name]
        out = {"crop": code, "plants_plt": plt, "crop_name": name,
               "sheet_phu": r["Heat Units"]}
        out.update({RENAME[c]: _md(r[c]) for c in DATE_COLS})
        rows.append(out)
    df = pd.DataFrame(rows)
    missing = set(NAMES) - set(df["crop_name"])
    if missing:
        raise SystemExit(f"{SHEET}: no row for {sorted(missing)}")
    # Every crop must have an emerge date, one harvest and a full irrigation window, or the
    # management this feeds is silently incomplete.
    for col in ("emerge", "harv1", "irr_start", "irr_end"):
        blank = df.loc[df[col] == "", "crop"].tolist()
        if blank:
            raise SystemExit(f"{SHEET}: {col} empty for {blank}")
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", type=Path, default=WORKBOOK)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not args.workbook.is_file():
        raise SystemExit(f"missing workbook {args.workbook}")
    df = port(args.workbook)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))
    print(f"\nwrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
