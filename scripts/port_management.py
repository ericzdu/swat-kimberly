"""Build the GRACEnet rotation management for the Kimberly SWAT+ HRU.

Irrigation: ``data/irrigation_gracenet.csv``, extracted from the GRACEnet primary workbooks.

**Operation dates, harvest indices and fertiliser timing follow the calibrated ArcSWAT
reference model** (`TxtInOut-2/000140001.mgt`, HRU 119 / subbasin 14 — the same field).
Earlier versions applied each manure on the planting date and used the generic SWAT+
`silage` / `hay_cut_high` harvest types; the reference applies every manure on **April 10**
regardless of planting, and overrides the harvest index per crop.

Writes: management.sch (rotation: plant / harvest / kill / fertilize / 158 measured daily
irrigation events), plant.ini (community of the rotation crops), appends measured GRACEnet
manures to fertilizer.frt, per-crop harvest types to harv.ops, per-event amounts to irr.ops,
and points landuse.lum at the new schedule + community.

SWAT+ processes schedule ops in listed order; a year rolls over when the next op's
day-of-year is earlier than the previous op's — so we emit ALL ops sorted by (year, doy).
Crops map corn_silage->corn, barley/triticale_silage->barl, alfalfa->alfa.

**The simulation runs 2012-2019**: a 2012 barley spin-up plus the seven measured rotation
years. The reference model stretched its 8-year rotation over a 9-year run by repeating 2012's
operations in 2020; that fabricated year is dropped here. See ``SIM_END_YEAR``.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
# Irrigation comes from the GRACEnet primary records (see scripts/extract_primary.py), not
# from RuFaS's re-export. The two agree to 0.1 mm in every year and on all 158 events; the
# primary source is used because it is the primary source.
IRR_CSV = ROOT / "data" / "irrigation_gracenet.csv"

COMM, SCHED, LUM = "kimb_comm", "kimb_rot", "alfa_lum"

# --- harvest types ----------------------------------------------------------------------
# The reference overrides the harvest index per crop (HI_OVR) at efficiency 1.0 with no
# minimum-biomass floor. The stock SWAT+ types differ materially: `silage` is 0.90 HI at
# 0.95 efficiency, `hay_cut_high` is 0.80 HI with a 3000 kg/ha floor that suppresses cuts.
# HI_OVR and HARV_EFF both come from the site's own crop table
# (`Crop Parameters and Plant Harvest dates.xlsx`, sheet `SWAT Crop Parameters`), which gives
# HI_OVR 1.0 for all three and HARV_EFF 0.95 / 0.98 / **0.54**. Barley previously carried 0.52,
# which is the sheet's *HVSTI* rather than its HARV_EFF — the two columns were conflated.
HARVEST = {          # name -> (harv_idx, harv_eff, harv_bm_min)
    "gn_corn": (0.98, 1.0, 0.0),
    "gn_barl": (0.54, 1.0, 0.0),
    "gn_alfa": (0.95, 1.0, 0.0),
}

# --- tillage ----------------------------------------------------------------------------
# Bierer et al. 2022 section 2.3: "Manure was immediately incorporated through disking to a
# 15-cm depth to minimize ammonia volatilization and P runoff losses." The model had **zero**
# tillage operations across the whole rotation and applied every manure as a surface broadcast
# at 99 % ammoniacal N — the maximum-volatilisation configuration, and the opposite of what
# was done in the field. A disk pass on each manure date incorporates it.
TILLAGE = {"gn_disk": (0.85, 150.0, 30.0)}   # name -> (mix_eff, mix_dp mm, rough)

# --- measured GRACEnet manures: name -> (rate kg/ha, min_n, min_p, org_n, org_p) ---------
# Rates and concentrations are the measured GRACEnet compositions. The reference expresses
# the same applications as rate/10 with concentration x10 (algebraically identical N and P)
# and rounds its fert.dat to 3 decimals; ours keep full precision.
MANURES = {
    "gn2013": (43800, 0.00260, 0.004655, 0.01040, 0.000245),
    "gn2014": (48000, 0.00390, 0.006650, 0.01560, 0.000350),
    "gn2018": (88300, 0.00082, 0.001995, 0.00328, 0.000105),
    "gn2019": (54300, 0.00082, 0.007220, 0.00328, 0.000380),
}
NH3_FRAC = 0.99   # reference fert.dat FNH3N; the template default is 1.0

# The reference applied Elem-N 350 / Elem-P 320 kg/ha on 3/15 in both spin-up years. That was
# a device to charge a profile initialised to zero nitrate, and it has no counterpart in the
# source record: `GraceNet Data Summary2.xlsx::Fert App` begins in 2013, and Bierer et al. 2022
# Table 1 shows the spring-manure plot received nothing in 2012 (the Fall 2012 entries belong
# to the fall-manure and fall-compost treatments, which are different plots). The profile is
# now initialised from the measured April-2013 soil N and P instead (see port_nutrients.py),
# so the synthetic charge is dropped rather than carried forward.

# --- rotation ---------------------------------------------------------------------------
# (op, year, month, day, op_data1, op_data2). Dates verbatim from the reference schedule.
#
# The reference terminates a crop with `harvonly` followed by `kill` the next day. SWAT+
# rev 60.5.7 **silently ignores a standalone `kill` op** — it never reaches mgt_out.txt and
# the plant keeps growing, which made the 2017 alfalfa stand survive into 2018 (the corn
# planting logged PLANT_ALREADY_GROWING and "corn" harvested 155 t/ha of runaway alfalfa).
# `hvkl` on the harvest date is SWAT+'s combined harvest-and-kill and is the correct
# equivalent; plain `harv` is used only for the intermediate alfalfa cuts, where the stand
# is meant to survive.
SPINUP_OPS = [
    ("plnt", 4, 1, "barl", "null"),
    ("hvkl", 8, 10, "barl", "gn_barl"),
]

CROP_OPS = [
    ("fert", 2013, 4, 10, "gn2013", "broadcast"),
    ("till", 2013, 4, 10, "gn_disk", "null"),
    ("plnt", 2013, 5, 16, "corn", "null"),
    ("hvkl", 2013, 9, 12, "corn", "gn_corn"),

    ("plnt", 2014, 4, 9, "barl", "null"),
    ("fert", 2014, 4, 10, "gn2014", "broadcast"),
    ("till", 2014, 4, 10, "gn_disk", "null"),
    ("hvkl", 2014, 8, 20, "barl", "gn_barl"),

    ("plnt", 2015, 4, 16, "alfa", "null"),
    ("harv", 2015, 7, 18, "alfa", "gn_alfa"),
    ("harv", 2015, 9, 9, "alfa", "gn_alfa"),

    ("harv", 2016, 5, 26, "alfa", "gn_alfa"),
    ("harv", 2016, 7, 13, "alfa", "gn_alfa"),
    ("harv", 2016, 9, 7, "alfa", "gn_alfa"),

    ("harv", 2017, 5, 31, "alfa", "gn_alfa"),
    ("harv", 2017, 7, 10, "alfa", "gn_alfa"),
    ("hvkl", 2017, 9, 15, "alfa", "gn_alfa"),

    ("fert", 2018, 4, 10, "gn2018", "broadcast"),
    ("till", 2018, 4, 10, "gn_disk", "null"),
    ("plnt", 2018, 5, 17, "corn", "null"),
    ("hvkl", 2018, 9, 24, "corn", "gn_corn"),

    ("fert", 2019, 4, 10, "gn2019", "broadcast"),
    ("till", 2019, 4, 10, "gn_disk", "null"),
    ("plnt", 2019, 4, 13, "barl", "null"),
    ("hvkl", 2019, 8, 8, "barl", "gn_barl"),
]

SPINUP_YEARS = (2012,)

#: The simulation ends at 2019, not 2020.
#:
#: 2020 was a fabricated year. The reference model runs an 8-year rotation over a 9-year
#: simulation, so 2020 simply repeated 2012's barley operations — and because
#: ``build_ops`` filtered irrigation to 2019, it repeated them with **zero irrigation**, in a
#: year when 757.7 mm was actually applied (``GRACEnet Irrigation 2020-2022.xlsx::2020``,
#: 26 events, 22 Apr - 11 Oct). Simulated 2020 ET came out at 250 mm against 421-1013 mm in
#: every other year, and ``print.prt`` skips only the 2012 spin-up, so that year was being
#: **scored**.
#:
#: Wiring the measured water in would not fix it: the 2020 water was applied to a crop
#: harvested in October, which is not the August-harvested barley the rotation assumes, and no
#: 2020 yield was measured. Rather than choose between a fabricated crop and a fabricated
#: water balance, the year is dropped. What remains is 2012 spin-up plus **2013-2019, all
#: seven of which have a measured yield**. The 2020 irrigation stays in
#: ``data/irrigation_gracenet.csv`` so it is available if the crop is ever identified.
SIM_END_YEAR = 2019


def doy(year: int, mon: int, day: int) -> int:
    return date(year, mon, day).timetuple().tm_yday


def md(year: int, jday: int) -> tuple[int, int]:
    d = date.fromordinal(date(year, 1, 1).toordinal() + jday - 1)
    return d.month, d.day


def build_ops() -> list[tuple]:
    """Return all schedule ops as (year, doy, line-tuple), sorted by (year, doy)."""
    ops: list[tuple[int, int, tuple]] = []

    rotation = list(CROP_OPS)
    for yr in SPINUP_YEARS:
        rotation += [(op, yr, mon, day, d1, d2) for op, mon, day, d1, d2 in SPINUP_OPS]

    for op, yr, mon, day, d1, d2 in rotation:
        d3 = MANURES[d1][0] if op == "fert" else 0.0
        # NOTE: op_data3 on `plnt` is NOT heat units (large values segfault the engine);
        # SWAT+ derives heat units from plants.plt `days_mat` plus climate.
        ops.append((yr, doy(yr, mon, day), (op, mon, day, 0.0, d1, d2, float(d3))))

    # measured daily irrigation -> one irrm op per event, referencing an irr.ops entry.
    df = pd.read_csv(IRR_CSV)
    df = df[df.year <= SIM_END_YEAR].rename(columns={"mm": "irrigation"})
    for i, r in enumerate(df.itertuples(), start=1):
        mon, day = md(int(r.year), int(r.jday))
        ops.append((int(r.year), int(r.jday),
                    ("irrm", mon, day, 0.0, f"gn{i:04d}", "null", 0.0)))

    ops.sort(key=lambda t: (t[0], t[1]))
    return ops


def write_management(ops: list[tuple]) -> None:
    lines = [
        "management.sch: written by swat-kimberly port_management.py\n",
        "name                                       numb_ops  numb_auto            op_typ       mon       day        hu_sch          op_data1          op_data2      op_data3  \n",
        f"{SCHED:<34}{len(ops):>6}{0:>11}  \n",
    ]
    for _, _, o in ops:
        typ, mon, day, hu, d1, d2, d3 = o
        lines.append(f"{'':>48}{typ:<10}{mon:>6}{day:>10}{hu:>14.5f}{d1:>18}{d2:>18}{d3:>14.5f}  \n")
    (TIO / "management.sch").write_text("".join(lines))
    print(f"management.sch: {len(ops)} ops")


#: ``yrs_init`` -- years of growth the stand already has at simulation start.
#:
#: This was 1.0 for every plant, which is wrong for alfalfa: the stand is not planted until
#: 2015-04-16, so declaring it a year old on 2012-01-01 makes SWAT+ carry an established
#: perennial through the 2013 corn and 2014 barley years. Setting it to **0** moves 2013 corn
#: from 12.63 to 18.03 t/ha (measured 22.10) and leaves the alfalfa years essentially unchanged
#: (2016: 24.63 -> 23.96). See ``runs/growth_diagnosis.md`` section 7.
#:
#: It does **not** fix the whole problem. A perennial in the community competes for light and
#: nitrogen in every year regardless, and rev 60.5.7 offers no way to end that residency --
#: ``kill`` after ``hvkl`` is silently ignored, there is no ``lu_change`` decision-table action,
#: and there is no ``lum.upd`` slot in ``file.cio``. That is why 2018-19 stay depressed.
YRS_INIT = {"corn": 1.0, "barl": 1.0, "alfa": 0.0}


def write_plant_ini() -> None:
    plants = ["corn", "barl", "alfa"]
    lines = [
        "plant.ini: written by swat-kimberly port_management.py\n",
        "pcom_name          plt_cnt  rot_yr_ini          plt_name     lc_status      lai_init       bm_init      phu_init      plnt_pop      yrs_init      rsd_init  \n",
        f"{COMM:<19}{len(plants):>7}{1:>11}  \n",
    ]
    for p in plants:
        lines.append(f"{'':>40}{p:<8}{'n':>6}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{YRS_INIT[p]:>14.5f}{0.0:>14.5f}  \n")
    (TIO / "plant.ini").write_text("".join(lines))
    print(f"plant.ini: community {COMM} with {plants}, yrs_init {YRS_INIT}")


def append_fertilizers() -> None:
    frt = (TIO / "fertilizer.frt").read_text().rstrip("\n").splitlines()
    existing = {ln.split()[0] for ln in frt[2:]}
    for name, (_, min_n, min_p, org_n, org_p) in MANURES.items():
        if name in existing:
            continue
        frt.append(f"{name:<22}{min_n:>10.5f}{min_p:>14.5f}{org_n:>14.5f}{org_p:>14.5f}"
                   f"{NH3_FRAC:>14.5f}{'null':>14}  GRACEnet_manure")
    (TIO / "fertilizer.frt").write_text("\n".join(frt) + "\n")
    print(f"fertilizer.frt: +{len(MANURES)} GRACEnet manures (nh3_n={NH3_FRAC})")


def append_harvest_ops() -> None:
    harv = (TIO / "harv.ops").read_text().rstrip("\n").splitlines()
    existing = {ln.split()[0] for ln in harv[2:]}
    for name, (idx, eff, bm_min) in HARVEST.items():
        if name in existing:
            continue
        harv.append(f"{name:<22}{'biomass':>14}{idx:>14.5f}{eff:>14.5f}{bm_min:>14.5f}  reference_HI_override")
    (TIO / "harv.ops").write_text("\n".join(harv) + "\n")
    print(f"harv.ops: +{len(HARVEST)} reference harvest types "
          + ", ".join(f"{n} HI={v[0]}" for n, v in HARVEST.items()))


def append_tillage_ops() -> None:
    til = (TIO / "tillage.til").read_text().rstrip("\n").splitlines()
    existing = {ln.split()[0] for ln in til[2:]}
    for name, (eff, dp, rough) in TILLAGE.items():
        if name in existing:
            continue
        til.append(f"{name:<22}{eff:>10.5f}{dp:>14.5f}{rough:>14.5f}"
                   f"{0.0:>14.5f}{0.0:>14.5f}  manure_incorporation_disk_15cm")
    (TIO / "tillage.til").write_text("\n".join(til) + "\n")
    print(f"tillage.til: +{len(TILLAGE)} " + ", ".join(
        f"{n} (mix_eff {v[0]}, mix_dp {v[1]:.0f} mm)" for n, v in TILLAGE.items()))


def set_time_sim() -> None:
    """Set the simulation window to SPINUP..SIM_END_YEAR (see SIM_END_YEAR for why 2019).

    The a10 template ships ``time.sim`` at 2018-2025. Setting it used to be a side effect of
    the now-retired ``port_weather.py``; when that script was dropped from ``build_model.sh``
    nothing took the job over, so a clean rebuild silently produced a model whose simulation
    window did not overlap its own weather record. Owning it here makes the window explicit
    and keeps it beside the schedule that has to fit inside it.
    """
    path = TIO / "time.sim"
    lines = path.read_text().splitlines()
    toks = lines[2].split()
    toks[1], toks[3] = str(min(SPINUP_YEARS)), str(SIM_END_YEAR)   # yrc_start, yrc_end
    lines[2] = "".join(f"{t:>10}" for t in toks)
    path.write_text("\n".join(lines) + "\n")
    print(f"time.sim: {toks[1]}-{toks[3]} (2020 dropped)")


def append_irr_ops() -> None:
    df = pd.read_csv(IRR_CSV).rename(columns={"mm": "irrigation"})
    events = df[df.year <= SIM_END_YEAR].reset_index(drop=True)
    irr = (TIO / "irr.ops").read_text().rstrip("\n").splitlines()
    for i, r in enumerate(events.itertuples(), start=1):
        amt = float(r.irrigation)
        irr.append(f"{f'gn{i:04d}':<22}{amt:>8.5f}{1.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}  gracenet")
    (TIO / "irr.ops").write_text("\n".join(irr) + "\n")
    print(f"irr.ops: +{len(events)} measured irrigation events")


def point_landuse() -> None:
    lum = (TIO / "landuse.lum").read_text().splitlines(keepends=True)
    parts = lum[2].split()
    parts[2] = COMM   # plnt_com
    parts[3] = SCHED  # mgt
    lum[2] = "  ".join(parts) + "  \n"
    (TIO / "landuse.lum").write_text("".join(lum))
    print(f"landuse.lum: plnt_com={COMM}, mgt={SCHED}")


def main() -> None:
    ops = build_ops()
    write_management(ops)
    write_plant_ini()
    append_fertilizers()
    append_harvest_ops()
    append_tillage_ops()
    append_irr_ops()
    point_landuse()
    set_time_sim()


if __name__ == "__main__":
    main()
