"""Extract the primary GRACEnet spreadsheets into committed CSVs the ports read.

`~/Documents/Kimberly, Idaho/` is the canonical data folder for this site. Everything the
model needs should come from there, not from a sibling model's re-export. This script pulls
the spreadsheets into `data/` so the ports have a stable, diffable, committed input and the
build does not depend on a path outside the repo.

Produces:
  data/irrigation_gracenet.csv   — every measured irrigation event, 2013-2020
  data/crop_params_swat.csv      — the site's calibrated SWAT crop parameter table
  data/soil_gracenet.csv         — measured bulk density and initial soil N/P by depth

    uv run --with openpyxl python scripts/extract_primary.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = Path.home() / "Documents" / "Kimberly, Idaho"
GN = SRC / "USDA GRACEnet"

IRR_CSV = ROOT / "data" / "irrigation_gracenet.csv"
CROP_CSV = ROOT / "data" / "crop_params_swat.csv"

#: (workbook, sheet, year, column holding millimetres). The GRACEnet workbooks were kept by
#: different people in different years and none of the three layouts agree.
IRR_SHEETS = [
    ("GRACEnet Irrigation 2013-2015.xlsx", "2013 Corn", 2013, "Irrigation (mm)", 0),
    ("GRACEnet Irrigation 2013-2015.xlsx", "2014 Barley", 2014, "Irrigation (mm)", 0),
    ("GRACEnet Irrigation 2013-2015.xlsx", "2015 Alfalfa", 2015, "Irrigation (mm)", 0),
    ("GRACEnet Irrigation 2016.xlsx", "ismData", 2016, "Irrigation (mm)", 6),
    ("GRACEnet Irrigation 2017-2019.xlsx", " 2017 Alfalfa", 2017, "mm, Irrig", 0),
    ("GRACEnet Irrigation 2017-2019.xlsx", "2018 Corn", 2018, "mm, Irrig", 0),
]


def irrigation_2019() -> pd.DataFrame:
    """2019 comes from the pivot-controller export, not the 2017-2019 workbook.

    The two sources disagree. ``GRACEnet Irrigation 2017-2019.xlsx::2019 Barley`` rounds every
    event to 1.00 in (520.70 mm for the season); ``GRACEnet Irrigation 2020-2022.xlsx::2019``
    is the controller's own log and records the same events at **0.96 in** (502.41 mm), with
    one date a day later. 0.96 in is a real controller setting used throughout 2018, 2020,
    2021 and 2022, so the rounding is in the summary workbook rather than in the field. 2018
    cross-checks *exactly* between the same two sources (558.80 mm, all 20 dates identical),
    which is what identifies the 2019 discrepancy as a transcription artefact.
    """
    df = pd.read_excel(GN / "GRACEnet Irrigation 2020-2022.xlsx", sheet_name="2019")
    d = pd.DataFrame({
        "date": pd.to_datetime(df["Unnamed: 1"], errors="coerce"),
        "mm": pd.to_numeric(df["Inch"], errors="coerce") * 25.4,
    }).dropna()
    d = d[d["mm"] > 0]
    d["year"] = 2019
    print(f"  2019: {d['mm'].sum():7.1f} mm over {len(d):3d} events   "
          f"(GRACEnet Irrigation 2020-2022.xlsx::2019, pivot-controller export)")
    return d


def irrigation() -> pd.DataFrame:
    rows = []
    for book, sheet, year, col, header in IRR_SHEETS:
        df = pd.read_excel(GN / book, sheet_name=sheet, header=header)
        date_col = "Date" if "Date" in df.columns else df.columns[1]
        d = pd.DataFrame({
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "mm": pd.to_numeric(df[col], errors="coerce"),
        }).dropna()
        d = d[d["mm"] > 0]
        d["year"] = year
        rows.append(d)
        print(f"  {year}: {d['mm'].sum():7.1f} mm over {len(d):3d} events   ({book}::{sheet})")

    rows.append(irrigation_2019())

    # 2020 is extracted for the record but is NOT simulated: the crop that received this water
    # is unknown (it was harvested in October, so not the barley the rotation would imply), and
    # no yield was measured. The simulation therefore ends at 2019. See PROVENANCE.md 1b.
    df = pd.read_excel(GN / "GRACEnet Irrigation 2020-2022.xlsx", sheet_name="2020")
    d = pd.DataFrame({
        "date": pd.to_datetime(df["Unnamed: 1"], errors="coerce"),
        "mm": pd.to_numeric(df["Irrigation (in.) "], errors="coerce") * 25.4,
    }).dropna()
    d = d[d["mm"] > 0]
    d["year"] = 2020
    rows.append(d)
    print(f"  2020: {d['mm'].sum():7.1f} mm over {len(d):3d} events   (NOT yet used - see PROVENANCE 1b)")

    out = pd.concat(rows).sort_values("date").reset_index(drop=True)
    out["jday"] = out["date"].dt.dayofyear
    return out[["year", "jday", "date", "mm"]]


def crop_params() -> pd.DataFrame:
    """The site's calibrated SWAT crop table — first block only, before the SWAT defaults."""
    df = pd.read_excel(SRC / "Crop Parameters and Plant Harvest dates.xlsx",
                       sheet_name="SWAT Crop Parameters")
    df = df[df["CPNM"].notna()]
    # The sheet stacks two blocks: calibrated values first, stock SWAT defaults after. Take
    # the first occurrence of each crop code.
    return df.drop_duplicates(subset="CPNM", keep="first").reset_index(drop=True)


def soil() -> pd.DataFrame:
    """Measured bulk density and the April-2013 soil N/P profile, by depth."""
    book = GN / "GraceNet Soil and Nutrient Properties.xlsx"
    bd = pd.read_excel(book, sheet_name="Soil Bulk Density")
    bd = (bd[["Depth (mm)", "Average BD (g/cm3)"]].dropna()
          .rename(columns={"Depth (mm)": "depth_mm", "Average BD (g/cm3)": "bd_g_cm3"}))

    np_ = pd.read_excel(book, sheet_name="Soil N & P")
    first = np_[pd.to_datetime(np_["Year"], errors="coerce") == pd.Timestamp("2013-04-01")]
    prof = (first.groupby("Depth")[["NO3-N mg/kg", "Olsen P mg/kg"]].mean()
            .rename(columns={"NO3-N mg/kg": "no3_n_mg_kg", "Olsen P mg/kg": "olsen_p_mg_kg"}))
    prof.index.name = "depth_cm"
    prof = prof.reset_index()
    prof["depth_mm"] = prof["depth_cm"] * 10
    return bd.merge(prof.drop(columns="depth_cm"), on="depth_mm", how="outer").sort_values("depth_mm")


def soil_no3() -> pd.DataFrame:
    """The measured **seven-year April soil-nitrate trajectory**, 2013-2019.

    ``GraceNet Soil and Nutrient Properties.xlsx::Soil N & P`` samples four plots at five
    depths (15, 31, 61, 91, 122 cm) every April. :func:`soil` already reads the 2013 column of
    this sheet for the initial condition; the remaining six years were never extracted, and
    they are the only measured constraint on the nitrogen cycle at this site.

    The sampled profile is **exactly** the modelled profile: soil ``80295`` is four layers to
    1220 mm with the same measured bulk densities, so the comparison needs no depth
    reconciliation. Per-layer stock is ``0.1 * ppm * thickness_cm * bd`` kg/ha — the factor the
    workbook's own ``kg_ha to mg_kg`` sheet implies (70 ppm over 0.3 m at 1.45 -> 304.5 kg/ha).

    Both units are written. ``no3_ppm`` is the profile mass-weighted mean, which is the
    quantity ``nutrients.sol:nitrate`` holds; ``no3_kg_ha`` is the profile stock, which is what
    a flux balance accumulates into. They differ by a constant 17.04 kg/ha per ppm here.
    """
    book = GN / "GraceNet Soil and Nutrient Properties.xlsx"
    bd = (pd.read_excel(book, sheet_name="Soil Bulk Density")[["Depth (cm)", "Average BD (g/cm3)"]]
          .dropna().rename(columns={"Depth (cm)": "depth_cm", "Average BD (g/cm3)": "bd"}))
    bd["thick_cm"] = bd["depth_cm"].diff().fillna(bd["depth_cm"])
    bd["mass"] = bd["thick_cm"] * bd["bd"]          # cm * g/cm3, proportional to layer mass

    df = pd.read_excel(book, sheet_name="Soil N & P")[["Year", "Plot", "Depth", "NO3-N mg/kg"]]
    # Year and Plot are written once per 5-depth block; the depths repeat down the column.
    df["Year"] = pd.to_datetime(df["Year"], errors="coerce").ffill()
    df = df.dropna(subset=["Year", "NO3-N mg/kg"])

    # Mean over the four plots at each depth, then mass-weight down the profile.
    prof = df.groupby([df["Year"].dt.year, "Depth"])["NO3-N mg/kg"].agg(["mean", "std", "count"])
    prof.index.names = ["year", "depth_cm"]
    prof = prof.reset_index().merge(bd[["depth_cm", "thick_cm", "bd", "mass"]], on="depth_cm")

    out = []
    for year, g in prof.groupby("year"):
        out.append({
            "year": int(year),
            "no3_ppm": float((g["mean"] * g["mass"]).sum() / g["mass"].sum()),
            "no3_kg_ha": float(0.1 * (g["mean"] * g["thick_cm"] * g["bd"]).sum()),
            # Plot-to-plot spread, propagated the same way — the measurement's own noise floor.
            "sd_ppm": float((g["std"] * g["mass"]).sum() / g["mass"].sum()),
            "n_plots": int(g["count"].min()),
        })
    return pd.DataFrame(out)


def main() -> None:
    IRR_CSV.parent.mkdir(parents=True, exist_ok=True)

    print("irrigation (GRACEnet primary records):")
    irr = irrigation()
    irr.to_csv(IRR_CSV, index=False)
    used = irr[irr["year"] <= 2019]
    print(f"  -> {IRR_CSV.relative_to(ROOT)}  "
          f"({len(used)} events 2013-2019, {len(irr) - len(used)} more in 2020)")

    soils = soil()
    soils.to_csv(ROOT / "data" / "soil_gracenet.csv", index=False)
    print("\nsoil (measured) -> data/soil_gracenet.csv")
    print(soils.to_string(index=False))

    no3 = soil_no3()
    no3.to_csv(ROOT / "data" / "soil_no3_gracenet.csv", index=False)
    print("\nsoil nitrate trajectory (measured) -> data/soil_no3_gracenet.csv")
    print(no3.to_string(index=False))

    crops = crop_params()
    crops.to_csv(CROP_CSV, index=False)
    print(f"\ncrop parameters -> {CROP_CSV.relative_to(ROOT)}")
    print(crops[["CPNM", "CROPNAME", "BIO_E", "HVSTI", "BLAI", "T_OPT", "T_BASE"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
