"""Port the AgriMet TWFI station record — the site's own primary weather data.

Source: ``~/Documents/Kimberly, Idaho/weather.csv``, a USBR Hydromet/AgriMet export for
station **TWFI** (Twin Falls), daily, **1990-05-05 to 2026-07-16**.

This replaces the two worst input compromises in the model at once:

* **Relative humidity and wind speed were never measured inputs.** ``weather-sta.cli`` set
  ``hmd = sim`` and ``wnd = sim``, so both were *generated* from a monthly climatology every
  day — and both enter Penman-Monteith directly. AgriMet measures them (``TA``, ``UA``).
* **Solar radiation was attributed to the wrong source and carried a hole.** ``port_solar.py``
  claimed to read the ArcSWAT reference model's ``slr.slr`` gauge. It did not — its CSV is the
  AgriMet ``SR`` column to three decimals, agreeing to 0.0005 MJ/m2 on all 3287 non-missing
  days. It also wrote a hard **0.00000 MJ/m2 on 2019-04-30**, where AgriMet reads ``NO RECORD``
  and the neighbouring days are ~25.4 — four days into that year's barley growth window. Solar
  is now written here, from the same load and the same gap interpolation as everything else.
* **Observed ET existed and was unused.** ``ETRS`` (alfalfa reference) and ``ETOS`` (grass
  reference) are Kimberly-Penman reference ET; ``ET`` is the station's crop ET estimate.
  These give the model a *measured* evapotranspiration target instead of scoring ET against
  another model's simulation.

It also carries 36 years of weather, against the 9 the model currently uses — the hard
dependency Experiment 2 was blocked on.

AgriMet parameter codes and the unit conversions applied here:

===== ============================== ==========================
code  quantity                       conversion
===== ============================== ==========================
PP    daily precipitation (in)       x 25.4 -> mm
MX    max air temperature (F)        (F - 32) x 5/9 -> C
MN    min air temperature (F)        "
SR    solar radiation (langley/day)  x 0.04184 -> MJ/m2
YM    mean dewpoint (F)              -> RH fraction, FAO-56 convention (see below)
TA    mean relative humidity (%)     recorded, but NOT used directly (see below)
UA    mean wind speed (mph)          x 0.44704 -> m/s
ETRS  alfalfa reference ET (in)      x 25.4 -> mm
ETOS  grass reference ET (in)        x 25.4 -> mm
ET    crop ET (in)                   x 25.4 -> mm
===== ============================== ==========================

``UA x 24 == WR`` (wind run, miles/day) in the raw file, which confirms the wind units.

**Relative humidity has to be in SWAT+'s convention, not AgriMet's.** AgriMet's ``TA`` is mean
daily RH, i.e. actual vapour pressure over saturation at *mean* air temperature. SWAT+ (like
FAO-56) forms the vapour-pressure deficit against the **mean of saturation vapour pressure at
Tmax and at Tmin**, which is larger because e_s is convex in temperature. Feeding ``TA``
straight in therefore overstates humidity, understates VPD, and understates PET — measured, and
still wrong. Ported directly it drove PET to 1125 mm/yr against a reference 1407 and a measured
alfalfa-reference ET of ~1600.

So RH is recomputed here from the **measured dewpoint** ``YM``::

    RH = e_s(Tdew) / ( ( e_s(Tmax) + e_s(Tmin) ) / 2 )

which is measured *and* in the engine's convention. July comes out at 0.384 by this definition
against 0.474 for raw ``TA`` — and against 0.357 for the reference model's own generated value,
which is the independent check that the convention is right.

Writes ``tfcchmd.hmd`` / ``hmd.cli`` and ``tfccwnd.wnd`` / ``wnd.cli``, wires them into
``weather-sta.cli`` and ``file.cio``, and extracts the observed ET series to
``data/observed_et_agrimet.csv`` for :mod:`scripts.calib_report`.

    uv run --with openpyxl python scripts/port_agrimet.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
AGRIMET = Path.home() / "Documents" / "Kimberly, Idaho" / "weather.csv"
ET_CSV = ROOT / "data" / "observed_et_agrimet.csv"

#: Years written to the weather files. **Not** the simulation window -- ``time.sim`` selects
#: that, and it may select any sub-window of what is written here. Writing the long record is
#: what unblocks Experiment 2: an episode samples an 8-year window out of these by rewriting
#: ``time.sim`` alone, so stochastic weather costs no file rewriting at all.
#:
#: 1995 is the start because coverage is essentially complete from there (365/365 on all six
#: required variables in most years, <=5 interpolated days in 1996-97). 1990-94 carry
#: 20+ missing days a year and are left out rather than interpolated across.
YEARS = range(1995, 2026)
LAT, LON, ELEV = 42.550, -114.350, 1194.800

PCP_DATA, PCP_CLI = "tfccpcp.pcp", "pcp.cli"
TMP_DATA, TMP_CLI = "tfcctmp.tem", "tmp.cli"
SLR_DATA, SLR_CLI = "tfccslr.slr", "slr.cli"
HMD_DATA, HMD_CLI = "tfcchmd.hmd", "hmd.cli"
WND_DATA, WND_CLI = "tfccwnd.wnd", "wnd.cli"

SOLAR_CSV = ROOT / "data" / "solar_2012_2020.csv"

# file.cio `climate` row token positions, after the section label.
CIO_SLOT = {"pcp": 3, "tmp": 4, "slr": 5, "hmd": 6, "wnd": 7}
# weather-sta.cli columns: name wgn pcp tmp slr hmd wnd pet atmo_dep
STA_COL = {"pcp": 2, "tmp": 3, "slr": 4, "hmd": 5, "wnd": 6}

HEADER_ROWS = 13   # USBR preamble + "BEGIN DATA"


def _sat_vp(temp_c):
    """Saturation vapour pressure (kPa), Tetens."""
    import numpy as np
    return 0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3))


def _rh_swatplus(dew_f, tmax_f, tmin_f):
    """Relative humidity in the convention SWAT+/FAO-56 use for the vapour-pressure deficit."""
    f2c = lambda f: (f - 32.0) * 5.0 / 9.0        # noqa: E731
    e_a = _sat_vp(f2c(dew_f))
    e_s = (_sat_vp(f2c(tmax_f)) + _sat_vp(f2c(tmin_f))) / 2.0
    return (e_a / e_s).clip(0.05, 1.0)


def load() -> pd.DataFrame:
    """Read the AgriMet export, convert units, and fill the handful of gaps."""
    df = pd.read_csv(
        AGRIMET, skiprows=HEADER_ROWS, skipfooter=1, engine="python",
        na_values=["NO RECORD", "NO RECORD   "],
    )
    df.columns = [c.strip().replace("TWFI ", "") for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"])
    df = df[df["DATE"].dt.year.isin(YEARS)].sort_values("DATE").reset_index(drop=True)

    out = pd.DataFrame({
        "year": df["DATE"].dt.year,
        "jday": df["DATE"].dt.dayofyear,
        "precip_mm": df["PP"] * 25.4,
        "tmax_c": (df["MX"] - 32.0) * 5.0 / 9.0,
        "tmin_c": (df["MN"] - 32.0) * 5.0 / 9.0,
        "solar_mj": df["SR"] * 0.04184,
        "rh_frac": _rh_swatplus(df["YM"], df["MX"], df["MN"]),
        "rh_mean_daily": df["TA"] / 100.0,   # AgriMet's own definition, kept for reference
        "wind_ms": df["UA"] * 0.44704,
        "et_mm": df["ET"] * 25.4,
        "etrs_mm": df["ETRS"] * 25.4,
        "etos_mm": df["ETOS"] * 25.4,
    })
    # A handful of single-day gaps (<=4 per column over 9 years). Interpolate rather than
    # drop: SWAT+ needs a complete daily series, and a -99 flag would bias the annual sums.
    gaps = out.isna().sum()
    if gaps.any():
        print("filling gaps by interpolation:",
              ", ".join(f"{k}={v}" for k, v in gaps.items() if v))
        out = out.interpolate(limit_direction="both")
    return out


def write_series(df: pd.DataFrame, column: str, data_name: str, cli_name: str,
                 title: str, fmt: str = "13.5f") -> None:
    nbyr = df["year"].nunique()
    with open(TIO / data_name, "w") as f:
        f.write(f"{title}\n")
        f.write("nbyr     tstep       lat       lon      elev\n")
        f.write(f"{nbyr:>4}{0:>10}{LAT:>10.3f}{LON:>10.3f}{ELEV:>10.3f}\n")
        for r in df.itertuples():
            f.write(f"{r.year}{r.jday:>7}{getattr(r, column):>{fmt}}\n")
    (TIO / cli_name).write_text(
        f"{cli_name}: written by swat-kimberly from the AgriMet TWFI record\n"
        "filename\n"
        f"{data_name}\n"
    )
    print(f"wrote {data_name} ({len(df)} days, {nbyr} years) and {cli_name}")


def wire(kind: str, data_name: str, cli_name: str) -> None:
    """Point weather-sta.cli at the series and fill file.cio's climate slot."""
    path = TIO / "weather-sta.cli"
    lines = path.read_text().splitlines()
    toks = lines[2].split()
    if toks[STA_COL[kind]] not in ("sim", data_name):
        raise SystemExit(f"weather-sta.cli {kind} column is {toks[STA_COL[kind]]!r}, "
                         f"expected 'sim' or {data_name!r} — refusing to overwrite")
    toks[STA_COL[kind]] = data_name
    lines[2] = f"{toks[0]:<25}" + "".join(f"{t:>25}" for t in toks[1:])
    path.write_text("\n".join(lines) + "\n")

    path = TIO / "file.cio"
    lines = path.read_text().splitlines()
    for i, ln in enumerate(lines):
        toks = ln.split()
        if toks[:1] != ["climate"]:
            continue
        fields = toks[1:]
        fields[CIO_SLOT[kind]] = cli_name
        lines[i] = f"{'climate':<18}" + "".join(f"{t:<18}" for t in fields)
        path.write_text("\n".join(lines) + "\n")
        print(f"wired {kind}: weather-sta.cli -> {data_name}, file.cio -> {cli_name}")
        return
    raise SystemExit("file.cio: no 'climate' row found")


def write_tmp(df: pd.DataFrame) -> None:
    """tmax and tmin share one file, two values per day."""
    nbyr = df["year"].nunique()
    with open(TIO / TMP_DATA, "w") as f:
        f.write("Temperature C - AgriMet TWFI (measured), ported by swat-kimberly\n")
        f.write("nbyr     tstep       lat       lon      elev\n")
        f.write(f"{nbyr:>4}{0:>10}{LAT:>10.3f}{LON:>10.3f}{ELEV:>10.3f}\n")
        for r in df.itertuples():
            f.write(f"{r.year}{r.jday:>7}{r.tmax_c:>13.5f}{r.tmin_c:>13.5f}\n")
    (TIO / TMP_CLI).write_text(
        f"{TMP_CLI}: written by swat-kimberly from the AgriMet TWFI record\n"
        "filename\n"
        f"{TMP_DATA}\n"
    )
    print(f"wrote {TMP_DATA} ({len(df)} days, {nbyr} years) and {TMP_CLI}")


def main() -> None:
    df = load()

    write_series(df, "precip_mm", PCP_DATA, PCP_CLI,
                 "Precipitation mm - AgriMet TWFI (measured), ported by swat-kimberly")
    wire("pcp", PCP_DATA, PCP_CLI)

    write_tmp(df)
    wire("tmp", TMP_DATA, TMP_CLI)

    write_series(df, "solar_mj", SLR_DATA, SLR_CLI,
                 "Solar radiation MJ/m2 - AgriMet TWFI (measured), ported by swat-kimberly")
    wire("slr", SLR_DATA, SLR_CLI)
    df[["year", "jday", "solar_mj"]].rename(columns={"solar_mj": "solar_mj_m2"}).to_csv(
        SOLAR_CSV, index=False)

    write_series(df, "rh_frac", HMD_DATA, HMD_CLI,
                 "Relative humidity - AgriMet TWFI (measured), ported by swat-kimberly")
    wire("hmd", HMD_DATA, HMD_CLI)

    write_series(df, "wind_ms", WND_DATA, WND_CLI,
                 "Wind speed m/s - AgriMet TWFI (measured), ported by swat-kimberly")
    wire("wnd", WND_DATA, WND_CLI)

    ET_CSV.parent.mkdir(parents=True, exist_ok=True)
    df[["year", "jday", "et_mm", "etrs_mm", "etos_mm"]].to_csv(ET_CSV, index=False)
    annual = df.groupby("year")[["et_mm", "etrs_mm", "etos_mm"]].sum().round(0)
    print(f"\nobserved ET -> {ET_CSV.relative_to(ROOT)}")
    print(annual.to_string())


if __name__ == "__main__":
    main()
