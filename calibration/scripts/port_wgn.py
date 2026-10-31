"""Replace the a10 template's weather-generator station with the site's own.

The a10 template ships a 3x3 grid of gridded wgn stations spanning 42.31-42.93 N,
114.06-114.69 W. That grid covers this site, so the carryover was never absurd — but the
assigned cell (``426n1144w``, 42.619/-114.375, 1145 m) is a gridded product, not the station
the field's own calibrated model uses, and it sits 62 m below the site.

This matters because ``weather-sta.cli`` sets ``hmd = sim`` and ``wnd = sim``: relative
humidity and wind speed are **generated from this monthly climatology every day**, and both
enter Penman-Monteith (``codes.bsn`` pet=1) directly. Precipitation, temperature and solar
radiation are measured series, so their wgn statistics only matter for gap-filling; humidity
and wind have no measured series behind them at all.

Source: the ArcSWAT reference model's own generator for subbasin 14, station
``IDTWINFALLSWS0`` (42.55/-114.35, 1207 m, 10 rain-years), extracted to
``data/reference_wgn_sub14.csv``.

The two formats map 1:1 except for humidity: SWAT2012 records a monthly mean **dewpoint in
degrees C** (``DEWPT``) where the SWAT+ file this model uses carries a **relative humidity
fraction** (``dew_ave``, 0-1 in the shipped station). Converted here with Tetens' formula at
the month's mean air temperature, which is the same reduction SWAT makes internally.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
WGN_CSV = ROOT / "data" / "reference_wgn_sub14.csv"

STATION = "IDTWINFALLSWS0"
LAT, LON, ELEV, RAIN_YRS = 42.55, -114.35, 1207.0, 10

#: weather-wgn.cli monthly columns, in file order.
COLUMNS = [
    "tmp_max_ave", "tmp_min_ave", "tmp_max_sd", "tmp_min_sd", "pcp_ave", "pcp_sd",
    "pcp_skew", "wet_dry", "wet_wet", "pcp_days", "pcp_hhr", "slr_ave", "dew_ave", "wnd_ave",
]
#: SWAT2012 .wgn name -> SWAT+ name. ``DEWPT`` is handled separately (unit change).
DIRECT = {
    "TMPMX": "tmp_max_ave", "TMPMN": "tmp_min_ave", "TMPSTDMX": "tmp_max_sd",
    "TMPSTDMN": "tmp_min_sd", "PCPMM": "pcp_ave", "PCPSTD": "pcp_sd", "PCPSKW": "pcp_skew",
    "PR_W1": "wet_dry", "PR_W2": "wet_wet", "PCPD": "pcp_days", "RAINHHMX": "pcp_hhr",
    "SOLARAV": "slr_ave", "WNDAV": "wnd_ave",
}


def sat_vapour_kpa(temp_c: float) -> float:
    """Saturation vapour pressure (kPa) by Tetens' formula."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def to_swatplus(ref: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({new: ref[old] for old, new in DIRECT.items()})
    mean_air = (ref["TMPMX"] + ref["TMPMN"]) / 2.0
    out["dew_ave"] = [
        sat_vapour_kpa(dew) / sat_vapour_kpa(air) for dew, air in zip(ref["DEWPT"], mean_air)
    ]
    return out[COLUMNS]


def render(monthly: pd.DataFrame) -> list[str]:
    """Station header + the 12 monthly rows, in the file's fixed-width layout."""
    head = f"{STATION:<31}{LAT:>8.5f}{LON:>14.5f}{ELEV:>14.5f}{RAIN_YRS:>10}  "
    rows = []
    for r in monthly.itertuples(index=False):
        vals = list(r)
        rows.append(f"{vals[0]:>12.5f}" + "".join(f"{v:>14.5f}" for v in vals[1:]) + "  ")
    return [head, *rows]


def replace_station(block: list[str]) -> None:
    """Swap the station block ``weather-sta.cli`` points at for ``block``.

    The file is [title, (station, colnames, 12 rows) x N]. Only the referenced station is
    replaced; the rest of the grid is left in place, unused and harmless.
    """
    sta_path = TIO / "weather-sta.cli"
    sta_lines = sta_path.read_text().splitlines()
    current = sta_lines[2].split()[1]

    path = TIO / "weather-wgn.cli"
    lines = path.read_text().splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^\S", ln) and i > 0
              and lines[i + 1].split()[:1] == ["tmp_max_ave"]]
    for i in starts:
        if lines[i].split()[0] != current:
            continue
        colnames = lines[i + 1]
        lines[i:i + 14] = [block[0], colnames, *block[1:]]
        path.write_text("\n".join(lines) + "\n")
        print(f"weather-wgn.cli: {current} -> {STATION} "
              f"({LAT}, {LON}, {ELEV} m, from the reference model)")
        break
    else:
        raise SystemExit(f"weather-wgn.cli: station {current!r} not found")

    toks = sta_lines[2].split()
    toks[1] = STATION
    sta_lines[2] = f"{toks[0]:<25}" + "".join(f"{t:>25}" for t in toks[1:])
    sta_path.write_text("\n".join(sta_lines) + "\n")
    print(f"weather-sta.cli: wgn -> {STATION}")


def main() -> None:
    ref = pd.read_csv(WGN_CSV).sort_values("month")
    monthly = to_swatplus(ref)
    print("humidity conversion (dewpoint C -> RH fraction):")
    for m, dew, rh in zip(ref["month"], ref["DEWPT"], monthly["dew_ave"]):
        print(f"  {m:>2}  {dew:>6.2f} C  ->  {rh:.3f}")
    replace_station(render(monthly))


if __name__ == "__main__":
    main()
