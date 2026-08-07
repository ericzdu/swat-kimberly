"""RETIRED — superseded by :mod:`scripts.port_agrimet`, which now writes ``tfccslr.slr``.

This script's stated source was false. It claimed to read the ArcSWAT reference model's
``slr.slr`` gauge; ``data/solar_2012_2020.csv`` is in fact the AgriMet TWFI ``SR`` column
rounded to three decimals, matching a direct re-derivation from ``weather.csv`` to within
0.0005 MJ/m2 on every non-missing day. It also wrote a hard zero on 2019-04-30, where AgriMet
has ``NO RECORD``, because unlike ``port_agrimet.py`` it did not interpolate gaps.

Solar therefore moved to ``port_agrimet.py`` alongside the other four measured series, so that
one script owns one source and gap handling is uniform. Kept for reference only; it is no
longer in ``build_model.sh``.

---

Original docstring follows.

Port measured solar radiation into the SWAT+ TxtInOut.

Without a measured series SWAT+ *generates* solar radiation from the weather generator's
monthly climatology. That shows up in ``hru_pw_yr.solarad`` as an essentially constant
17.78 MJ/m2 in every simulated year, whereas the measured record at this site varies
14.8-17.0 MJ/m2 between years. Solar radiation drives both the Penman-Monteith PET
(codes.bsn pet=1) and SWAT's radiation-limited biomass accumulation, so a generated series
decouples crop growth from the actual years being simulated.

Source: the ArcSWAT reference model's ``slr.slr`` gauge (2002-2022), sliced to 2012-2020
into ``data/solar_2012_2020.csv``.

Wiring, all of which this script performs:
  1. write ``tfccslr.slr``           - the daily series, SWAT+ .slr format
  2. write ``slr.cli``               - the index file naming it
  3. weather-sta.cli ``slr`` column  - "sim" -> "tfccslr.slr"
  4. file.cio ``climate`` row        - fill the slr slot with "slr.cli"
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
SOLAR_CSV = ROOT / "data" / "solar_2012_2020.csv"

SLR_DATA = "tfccslr.slr"
SLR_CLI = "slr.cli"
LAT, LON, ELEV = 42.550, -114.350, 1194.800

# file.cio `climate` row, tokens after the section label:
#   0 weather-sta  1 weather-wgn  2 wind-dir  3 pcp  4 tmp  5 slr  6 hmd  7 wnd  8 atmo
SLR_SLOT = 5
# weather-sta.cli columns: name wgn pcp tmp slr hmd wnd pet atmo_dep
STA_SLR_COL = 4


def write_series(df: pd.DataFrame) -> None:
    nbyr = df["year"].nunique()
    with open(TIO / SLR_DATA, "w") as f:
        f.write("Solar radiation - Kimberly (reference slr.slr gauge), ported by swat-kimberly\n")
        f.write("nbyr     tstep       lat       lon      elev\n")
        f.write(f"{nbyr:>4}{0:>10}{LAT:>10.3f}{LON:>10.3f}{ELEV:>10.3f}\n")
        for r in df.itertuples():
            f.write(f"{r.year}{r.jday:>7}{r.solar_mj_m2:>13.5f}\n")
    (TIO / SLR_CLI).write_text(
        "slr.cli: Solar radiation file names - written by swat-kimberly\n"
        "filename\n"
        f"{SLR_DATA}\n"
    )
    print(f"wrote {SLR_DATA} ({len(df)} days, {nbyr} years) and {SLR_CLI}")


def wire_station() -> None:
    path = TIO / "weather-sta.cli"
    lines = path.read_text().splitlines()
    toks = lines[2].split()
    toks[STA_SLR_COL] = SLR_DATA
    lines[2] = f"{toks[0]:<25}" + "".join(f"{t:>25}" for t in toks[1:])
    path.write_text("\n".join(lines) + "\n")
    print(f"weather-sta.cli: slr -> {SLR_DATA}")


def wire_file_cio() -> None:
    path = TIO / "file.cio"
    lines = path.read_text().splitlines()
    for i, ln in enumerate(lines):
        toks = ln.split()
        if toks[:1] != ["climate"]:
            continue
        fields = toks[1:]
        if fields[SLR_SLOT] not in ("null", SLR_CLI):
            raise SystemExit(f"file.cio climate slot {SLR_SLOT} is {fields[SLR_SLOT]!r}, "
                             f"expected 'null' — refusing to overwrite")
        fields[SLR_SLOT] = SLR_CLI
        lines[i] = f"{'climate':<18}" + "".join(f"{t:<18}" for t in fields)
        path.write_text("\n".join(lines) + "\n")
        print(f"file.cio: climate slr slot -> {SLR_CLI}")
        return
    raise SystemExit("file.cio: no 'climate' row found")


def main() -> None:
    df = pd.read_csv(SOLAR_CSV).sort_values(["year", "jday"]).reset_index(drop=True)
    write_series(df)
    wire_station()
    wire_file_cio()


if __name__ == "__main__":
    main()
