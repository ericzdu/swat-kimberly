"""SUPERSEDED by scripts/port_agrimet.py — kept for reference, not run by build_model.sh.

This wrote precipitation and temperature from RuFaS's ``kimberly_rotation.csv``, with 2020
patched in from the ArcSWAT reference's gauge. Both turned out to be re-exports of the same
underlying record: the AgriMet TWFI station series, which the site's own data folder holds
directly at ``~/Documents/Kimberly, Idaho/weather.csv``. Verified before switching — daily
correlation 1.0000 for precipitation, tmax and tmin, identical annual totals in every year
except 2020 (0.8 mm, where the old path used the reference gauge rather than AgriMet).

``port_agrimet.py`` now writes pcp, tmp, hmd and wnd from that one measured source.

ORIGINAL DOCSTRING FOLLOWS
"""
"""Port the Kimberly TWFI weather (2012-2020) into the SWAT+ TxtInOut.

2012-2019 comes from the RuFaS ``kimberly_rotation.csv``, so the SWAT+↔RuFaS comparison
isolates model differences rather than weather. 2020 is not in that file, so it comes from
``data/weather_2020.csv``, extracted from the ArcSWAT reference model's gauge (pcp_0001 /
tmp_0001, 2002-2022). The two sources are the same underlying record: over 2012-2019 their
annual precipitation totals agree to ~0.4 %, which is the reference file's 0.1 mm rounding.

The reference model simulates 2012-2020 with NYSKIP=1, so we match that window.
Overwrites the template's weather data files in place (same filenames → no .cli /
weather-sta.cli rewiring needed) and sets time.sim.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
RUFAS_CSV = Path.home() / "Desktop/projects/RuFaS/input/data/weather/kimberly_rotation.csv"
EXTRA_CSV = ROOT / "data" / "weather_2020.csv"

# keep the template station's geolocation header (Kimberly-area, elev ~1195 m)
LAT, LON, ELEV = 42.550, -114.350, 1194.800

COLS = ["year", "jday", "precip", "high", "low"]


def _header(kind: str, nbyr: int) -> str:
    return (
        f"{kind} - Kimberly TWFI (RuFaS + reference gauge), ported by swat-kimberly\n"
        f"nbyr     tstep       lat       lon      elev\n"
        f"{nbyr:>4}{0:>10}{LAT:>10.3f}{LON:>10.3f}{ELEV:>10.3f}\n"
    )


def load() -> pd.DataFrame:
    df = pd.read_csv(RUFAS_CSV)[COLS]
    extra = pd.read_csv(EXTRA_CSV)[COLS]
    df = pd.concat([df, extra], ignore_index=True)
    return df.sort_values(["year", "jday"]).reset_index(drop=True)


def main() -> None:
    df = load()
    nbyr = df["year"].nunique()
    print(f"loaded {len(df)} days, {nbyr} years ({df.year.min()}-{df.year.max()})")

    # precipitation (.pcp)  -> year jday pcp(mm)
    with open(TIO / "tfccpcp.pcp", "w") as f:
        f.write(_header("Precipitation data", nbyr))
        for r in df.itertuples():
            f.write(f"{r.year}{r.jday:>7}{r.precip:>13.5f}\n")

    # temperature (.tem)    -> year jday tmax tmin (degC)
    with open(TIO / "tfcctmp.tem", "w") as f:
        f.write(_header("Temperature data", nbyr))
        for r in df.itertuples():
            f.write(f"{r.year}{r.jday:>7}{r.high:>13.5f}{r.low:>13.5f}\n")

    # simulation period
    tsim = TIO / "time.sim"
    lines = tsim.read_text().splitlines()
    lines[2] = f"{0:>8}{df.year.min():>10}{0:>10}{df.year.max():>10}{0:>10}"
    tsim.write_text("\n".join(lines) + "\n")

    print("wrote tfccpcp.pcp, tfcctmp.tem; set time.sim ->", df.year.min(), df.year.max())


if __name__ == "__main__":
    main()
