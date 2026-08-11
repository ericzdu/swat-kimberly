"""Port the site's calibrated SWAT crop parameters into plants.plt.

**Source: `~/Documents/Kimberly, Idaho/Crop Parameters and Plant Harvest dates.xlsx`**, sheet
`SWAT Crop Parameters`, extracted to `data/crop_params_swat.csv`. This is the site's own
calibrated table. An earlier version read the same numbers out of RuFaS's crop configuration,
which merely re-exported them; the primary table is used because it is the primary source, and
because it also carries the stock SWAT defaults beside the calibrated values (corn BIO_E 39.0
default vs 50.0 calibrated here) — a plausibility anchor when bounding a fit.

Overrides the mapped columns for SWAT+ corn / barl / alfa, leaving all other plants.plt
columns at their SWAT+ defaults. Column order per the plants.plt header (0-indexed within
whitespace tokens).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_gym.params import set_value

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
CROP_CSV = ROOT / "data" / "crop_params_swat.csv"

# SWAT crop code (CPNM in the site table) -> SWAT+ plants.plt name
CROP_MAP = {"CSIL": "corn", "BARL": "barl", "ALFA": "alfa"}

# SWAT+ plants.plt token index -> RuFaS field (with optional transform)
COLMAP = {
    5:  ("BIO_E", 1.0),          # bm_e        radiation-use efficiency
    6:  ("HVSTI", 1.0),          # harv_idx
    7:  ("BLAI", 1.0),           # lai_pot
    8:  ("FRGRW1", 1.0),         # frac_hu1
    9:  ("LAIMX1", 1.0),         # lai_max1
    10: ("FRGRW2", 1.0),         # frac_hu2
    11: ("LAIMX2", 1.0),         # lai_max2
    12: ("DLAI", 1.0),           # hu_lai_decl
    15: ("RDMX", 1.0),           # rt_dp_max (the site table is already in m)
    16: ("T_OPT", 1.0),          # tmp_opt
    17: ("T_BASE", 1.0),         # tmp_base
    18: ("CNYLD", 1.0),          # frac_n_yld
    19: ("CPYLD", 1.0),          # frac_p_yld
    20: ("BN1", 1.0),            # frac_n_em
    21: ("BN2", 1.0),            # frac_n_50
    22: ("BN3", 1.0),            # frac_n_mat
    23: ("BP1", 1.0),            # frac_p_em
    24: ("BP2", 1.0),            # frac_p_50
    25: ("BP3", 1.0),            # frac_p_mat
    26: ("WSYF", 1.0),           # harv_idx_ws
    # Everything below index 26 was previously left at the SWAT+ template default. Where the
    # template happened to agree with the site table that was invisible; where it did not, the
    # model silently ran the *stock* value while the calibrated one sat unused in the sheet —
    # barley GSI 0.008 against a calibrated 0.002 (4x), corn USLE_C 0.14 against 0.20, and
    # RSDCO_PL 0.05 against 0.01 for both corn and alfalfa.
    14: ("CHTMX", 1.0),          # can_ht_max
    27: ("USLE_C", 1.0),         # usle_c_min
    28: ("GSI", 1.0),            # stcon_max   maximum stomatal conductance
    29: ("VPDFR", 1.0),          # vpd
    30: ("FRGMAX", 1.0),         # frac_stcon
    31: ("WAVP", 1.0),           # ru_vpd
    32: ("CO2HI", 1.0),          # co2_hi
    33: ("BIOEHI", 1.0),         # bm_e_hi
    34: ("RSDCO_PL", 1.0),       # plnt_decomp
    39: ("EXT_COEF", 1.0),       # ext_co      radiation extinction coefficient
    42: ("BM_DIEOFF", 1.0),      # bm_dieoff
}

#: Sheet columns deliberately NOT ported. ``ALAI_MIN``, ``BIO_LEAF``, ``MAT_YRS`` and
#: ``BMX_TREES`` are zero for every crop in the site table — they are unfilled placeholders,
#: not calibrated zeros. Writing them would set alfalfa's minimum LAI and years-to-maturity to
#: 0, which for a perennial is not a parameter choice but a broken stand. The SWAT+ template
#: values (lai_min 2.0, yrs_mat 2.0) are kept.
UNFILLED = ("ALAI_MIN", "BIO_LEAF", "MAT_YRS", "BMX_TREES")

#: plants.plt token 1, ``plnt_typ``, overridden for barley. **This is a bug fix, not a tuning
#: choice, and it was the whole barley shortfall.**
#:
#: The site table gives barley ``IDC = 5``, which is SWAT2012 for "cold annual", and the SWAT+
#: template accordingly carries ``cold_annual``. That classification is right in SWAT2012's
#: sense — barley is a cool-season cereal — but SWAT+ rev 60.5.7's ``cold_annual`` pathway is
#: built for a *fall-sown* crop that accumulates heat units before dormancy and resumes in
#: spring. Applied to an April-sown spring barley it collapses the potential heat units: the
#: crop reached maturity **46 days after planting** on ~530 degree-days, then stood in the field
#: without growing for the remaining 66-85 days until harvest, with every stress term at exactly
#: 0.000. Peak biomass was 4.5-6.2 Mg/ha against a measured 14.05-17.05 (`USDA Long-Term
#: Manure/LT Manure Soil Properties and P uptake data.xlsx`, sheet `plant P uptake`).
#:
#: ``Plant Harvest Dates`` documents **1800 heat units** for Spring Barley. With the plant type
#: corrected and *no other change* — ``days_mat`` left at the SWAT+ stock 105 — the engine
#: realizes **1517 (2014) and 1766 (2019)**, and the growth window roughly doubles to 97 and 110
#: days against the site's documented 124-day season. The same measurement on corn is the
#: control: corn is already ``warm_annual`` and already realizes 1889/1888 against the same
#: documented 1800, at its own stock ``days_mat``.
#:
#: ``days_mat`` is deliberately NOT adjusted. It has no value anywhere in the source table, and
#: moving it trades heat-unit fidelity against yield fit — which is calibration, not porting.
PLNT_TYP = {"barl": "warm_annual"}

#: Deviations from the site's calibrated column, applied *after* ``COLMAP``.
#:
#: Each entry is ``(row, column) -> (value, justification)``. Two of the four are source-backed
#: -- they take the workbook's own ``DEFAULT`` block instead of its calibrated block -- and two
#: are **fits**, labelled as such so they are never mistaken for measurements. Full derivation
#: in ``runs/growth_diagnosis.md``.
OVERRIDES: dict[tuple[str, str], tuple[float, str]] = {
    # -- source-backed: the workbook's DEFAULT block ------------------------------------
    # The site's calibrated canopy-development curve (FRGRW1 0.10 / LAIMX1 0.01 / FRGRW2 0.80)
    # was fitted inside SWAT2012. Applied in SWAT+ it delays canopy closure to about jday 210
    # for corn planted 17 May, costing ~15 PBIAS points. Curve *shape* is engine-specific in a
    # way BIO_E is not, so the same workbook's DEFAULT values are the better prior here.
    # REMOVED 2026-08-07 (CLAUDE.md rule 11b): corn's frac_hu1 0.15 / lai_max1 0.05 /
    # frac_hu2 0.50, taken from the workbook's DEFAULT block on the argument that his
    # calibrated 0.10 / 0.01 / 0.80 was SWAT2012-fitted and cost ~15 PBIAS points here. That
    # is a real rev-62 concern (rule 12) but it is *his* curve to change, not ours, and the
    # cost is already included in the 37.1 % mean |PBIAS| measured on his exact values.
    # Raise it with him rather than substituting a different block of his own workbook.

    # -- fits, not source values ---------------------------------------------------------
    # plant.ini declares a three-plant community, so alfalfa's minimum LAI is imposed on the
    # HRU in *every* year -- year-round, with zero standing biomass, including corn and barley
    # years and including 2013-14 before the stand is ever planted. At ext_co 0.65 a floor of
    # 2.0 intercepts 73 % of PAR and produces nothing.
    #
    # **This is a trade-off point, not a "lower is better" knob**, and the trade is against the
    # *water balance*. Dropping it far (0.1) maximises the yield recovery but the annual crops
    # then transpire the entire water input: ET rises 670 -> 785 mm/yr and deep percolation
    # falls 69 -> **0**, taking `basin_aqu_yr.no3_rchg` -- the leaching externality the Exp 1
    # reward reads -- to exactly zero with it. 1.75 keeps most of the yield gain, is *better*
    # on both annuals than 0.1, and leaves 32 mm/yr of drainage so the leaching term stays
    # alive. Measured at alfa.bm_e 10.0:
    #
    #   lai_min  corn    barl    alfa    perc   no3_rchg
    #   0.10    -31.4   -20.3    +5.8     0.0     0.00
    #   1.50    -25.8   -16.9    -0.4    20.4     0.94
    #   1.75    -24.7   -17.9    +0.5    32.3     1.56   <- shipped (rev 60.5.7)
    #   2.00    -23.6   -33.3    +1.8    46.4     4.09
    #
    # Under rev 62.0.0 the resident-perennial PAR-theft pathway is largely gone (plant-community
    # fix), so sweeping lai_min no longer moves ET/perc. Drainage was briefly "restored" via
    # hydrology.hyd ``pet_co`` 0.81, which turned out to cost 16 % PET bias against measured
    # ETos and to be treating a symptom; ``pet_co`` is now calibrated to 0.964 and the drainage
    # collapse is an open engine-difference finding — PROVENANCE §5h, OPEN_ITEMS #11.
    ("alfa", "lai_min"): (1.75, "FIT: trades resident-perennial PAR theft against drainage"),
    # REMOVED 2026-08-07 (CLAUDE.md rule 11b): ("alfa", "bm_e") -> 10.0. Its own rationale
    # said the quiet part out loud -- "it is absorbing the over-prediction, not measuring
    # radiation-use efficiency" -- which is exactly why it goes. The workbook's 17.0 stands.
}


def main() -> None:
    table = pd.read_csv(CROP_CSV).set_index("CPNM")
    cfgs = {code: table.loc[code].to_dict() for code in CROP_MAP}
    lines = (TIO / "plants.plt").read_text().splitlines(keepends=True)

    for rufas_name, swat_name in CROP_MAP.items():
        cfg = cfgs[rufas_name]
        # find the plants.plt row whose first token == swat_name
        for i, ln in enumerate(lines):
            toks = ln.split()
            if toks[:1] == [swat_name]:
                for idx, (field, scale) in COLMAP.items():
                    toks[idx] = f"{cfg[field] * scale:.5f}"
                if swat_name in PLNT_TYP:
                    toks[1] = PLNT_TYP[swat_name]
                # rebuild: name left-justified, rest right-justified 14-wide, desc trailing
                desc = toks[-1] if not _is_float(toks[-1]) else ""
                nums = toks[1:-1] if desc else toks[1:]
                lines[i] = f"{swat_name:<22}" + "".join(f"{t:>14}" for t in nums) + (f"  {desc}" if desc else "") + "\n"
                print(f"{swat_name} <- {rufas_name} ({cfg['CROPNAME']}): "
                      f"bm_e={cfg['BIO_E']} lai_pot={cfg['BLAI']} "
                      f"harv_idx={cfg['HVSTI']} tmp_opt={cfg['T_OPT']} tmp_base={cfg['T_BASE']}")
                break
        else:
            print(f"WARNING: {swat_name} not found in plants.plt")

    (TIO / "plants.plt").write_text("".join(lines))

    # Applied by column *name* rather than token index: these are columns SWAT+ has and the
    # SWAT2012 source table does not, so COLMAP has no entry to reuse.
    text = (TIO / "plants.plt").read_text()
    for (row, column), (value, why) in OVERRIDES.items():
        text = set_value(text, "plants.plt", row, column, value)
        print(f"  override {row}.{column} = {value}  ({why})")
    (TIO / "plants.plt").write_text(text)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
