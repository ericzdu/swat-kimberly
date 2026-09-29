"""Turn a completed SWAT+ run into profit, with prices as an explicit experimental axis.

    profit = crop revenue - irrigation cost - manure cost - mineral N cost
             - application-pass cost

Nitrate leaching is **zero-weighted by default** (``no3_price = 0.0``): it is reported as
``no3_leached_kg`` and does not touch the objective unless a price is passed. When it is
priced, the price is a **swept axis whose whole frontier is reported**, with the ``no3_price
= 0`` arm always alongside — so no result rests on a single shadow price that would have to
be defended. Never publish one interior point of that sweep as *the* answer.

Nitrous oxide is IPCC Tier 1 accounting over the same nitrogen flows (:func:`ipcc_n2o`),
reported as ``n2o_kg`` and **never** priced into ``profit``.

Why prices are a parameter and not a constant
---------------------------------------------
Idaho alfalfa hay fell **43 %** in three years (USDA NASS Crop Values 2024 Summary: $272 ->
$204 -> $154 per ton for 2022-24), and the alfalfa:corn-silage ratio moved 1.63 -> 1.63 -> 1.18.
The rotation lever trades alfalfa against the annuals, so **that ratio, not the price level, is
what decides the `R` arm** -- and a single fixed vector would report one point on a curve while
hiding that it is a point.

The arms are not equally exposed, which is why a fixed vector is still fine for two of them:

* ``I`` and ``M`` are **within-crop**. Their optimum turns on crop price : *input* cost, so
  relative crop prices barely matter. Use a named scenario.
* ``R`` is **between-crop**. Its answer *is* the ratio. Sweep it with :meth:`Prices.at_ratio`
  and report where the optimal rotation flips, the same crossover framing Exp 2 uses.

Units
-----
Crop prices are **$/Mg dry matter**, because that is what the model produces -- SWAT+ yields
come off ``basin_crop_yld_yr.txt`` as dry Mg. The NASS figures are $/short ton (hay) and $/bushel
(grain) at market moisture, so the scenarios below carry the conversion and its assumptions
explicitly rather than burying a magic number.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

#: short ton -> Mg
TON = 0.907185
#: 1 mm of water over 1 ha = 10 m**3
M3_PER_MM_HA = 10.0

# -- IPCC Tier 1 nitrous-oxide accounting ------------------------------------------------
# Defaults from the 2019 Refinement to the 2006 IPCC Guidelines, Vol. 4 Ch. 11 (Tier 1).
#
# This is an **accounting layer over simulated nitrogen flows, not a simulated N2O flux.**
# No SWAT variant in the official line emits N2O: the engine computes *total* denitrification
# with N2 and N2O lumped and never partitions them, which is why the N2O literature on this
# model (SWAT-N2O coupler; Wagena et al. 2017) is entirely forks and add-ons.
#
# The `denit` column is the obvious proxy and is already printed, in `basin_nb`/`hru_nb`.
# **Measured 2026-08-07, not inferred:** it is 0.001 kg N/ha over the rotation, against
# 297.5 fertiliser + 138.6 fixation. Denitrification is off here by calibration
# (`denit_exp` 0.001 vs a SWAT default near 1.4; `denit_frac` 1.0, firing only at saturation).
# So partitioning N2O out of `denit`, which is what the coupler approach does, would return
# zero. Getting a non-zero number means reimplementing denitrification itself -- but the
# nitrogen cycle here is calibrated against a measured soil-nitrate trajectory *with*
# denitrification suppressed, so adding it back in post-processing double-counts: it would
# credit N2O to nitrogen the engine still holds in its nitrate pool and still leaches.
#
# Two dead ends, recorded so they are not retried:
#   * `carbon = 1` in codes.bsn does NOT print N2O and is NOT a print flag -- it switches on
#     the Century C/N module and wrecks the calibration. Measured in an isolated copy: corn
#     yield 5.96 -> 2.85 t/ha, N uptake 286.8 -> 240.3, aquifer NO3 recharge 0.039 -> 0.077.
#     `basin_carbon_all.txt` stayed an unpopulated template even with the flag on.
#   * There is no measured N2O at this site. The GRACEnet and Long-Term Manure source
#     workbooks carry no gas-flux data of any kind, so a reimplemented routine could not be
#     validated here even if the mass-balance problem above were solved.
#
# One deviation from Tier 1, in the direction of the model: the indirect leaching term
# normally applies `FracLEACH` to applied N, because an inventory has no transport model.
# Here the leached quantity is simulated, so `EF5` is applied to `no3_rchg` directly. That is
# strictly better information -- and it inherits whatever bias the percolation pathway has,
# which is why `n2o_kg` is reported and never priced into `profit`.
#
# TODO(before submission): verify these six values against the published tables. They are the
# standard Tier 1 defaults but have not been checked against the source document in-repo.
#: Direct N2O-N per kg N applied.
IPCC_EF1 = 0.010
#: Indirect N2O-N per kg N volatilised as NH3/NOx.
IPCC_EF4 = 0.010
#: Indirect N2O-N per kg N lost to leaching/runoff.
IPCC_EF5 = 0.011
#: Fraction of applied *synthetic* N volatilising.
IPCC_FRACGASF = 0.11
#: Fraction of applied *organic* (manure) N volatilising.
IPCC_FRACGASM = 0.21
#: N2O-N -> N2O by molecular mass.
N2O_N_TO_N2O = 44.0 / 28.0


def ipcc_n2o(*, manure_n_kg: float, mineral_n_kg: float, no3_leached_kg: float) -> dict:
    """IPCC Tier 1 N2O (kg N2O/ha) from applied nitrogen and simulated nitrate loss.

    Returns the three pathways separately so a reader can see which dominates; in an
    irrigation experiment nitrogen is pinned, so `direct` and `volatilisation` are constant
    across arms and only `leaching` moves.
    """
    n_applied = float(manure_n_kg) + float(mineral_n_kg)
    direct = n_applied * IPCC_EF1
    volatilised = (float(mineral_n_kg) * IPCC_FRACGASF
                   + float(manure_n_kg) * IPCC_FRACGASM)
    indirect_vol = volatilised * IPCC_EF4
    indirect_leach = float(no3_leached_kg) * IPCC_EF5
    n2o_n = direct + indirect_vol + indirect_leach
    return {
        "n2o_kg": n2o_n * N2O_N_TO_N2O,
        "n2o_direct_kg": direct * N2O_N_TO_N2O,
        "n2o_volat_kg": indirect_vol * N2O_N_TO_N2O,
        "n2o_leach_kg": indirect_leach * N2O_N_TO_N2O,
        "n_applied_kg": n_applied,
    }


def _hay_to_mg_dm(usd_per_ton: float, moisture: float = 0.12) -> float:
    """NASS hay $/short ton at market moisture -> $/Mg dry matter."""
    return usd_per_ton / (TON * (1.0 - moisture))


def _grain_to_mg_dm(usd_per_bu: float, lb_per_bu: float, moisture: float) -> float:
    """NASS grain $/bushel at market moisture -> $/Mg dry matter."""
    kg_dm = lb_per_bu * 0.453592 * (1.0 - moisture)
    return usd_per_bu / kg_dm * 1000.0


def _silage_from_grain(usd_per_bu: float, multiplier: float = 9.0, dm: float = 0.35) -> float:
    """Corn silage $/Mg DM, **derived** -- there is no NASS silage price series.

    ``Crop Values`` carries "Corn for Grain" only, so silage is conventionally valued off the
    grain price. The ``multiplier`` (silage $/ton as-fed ~= 8-10 x corn $/bu) is a rule of
    thumb, not a measurement, and is exposed so it can be varied rather than trusted.
    """
    return usd_per_bu * multiplier / (TON * dm)


@dataclass(frozen=True)
class Prices:
    """A complete price vector. ``crop`` is keyed by SWAT+ plant name (``corn``/``barl``/``alfa``)."""

    crop: Mapping[str, float]   #: $/Mg dry matter
    water: float                #: $ per mm per ha (1 mm-ha = 10 m^3)
    manure: float               #: $ per Mg as applied — labour and haulage, see DEFAULT_MANURE
    # After `label`, not beside `manure` where it belongs semantically: callers construct
    # Prices positionally, so inserting a field mid-list silently rebinds their 4th argument
    # to it. Appending is the change that cannot do that.
    label: str = "unnamed"
    fert_n: float = 0.0         #: $ per kg N as mineral fertiliser
    fert_op: float = 0.0        #: $ per ha per fertiliser *application event*

    def alfalfa_ratio(self, numeraire: str = "corn") -> float:
        """Alfalfa's price relative to the annual crop the rotation trades it against."""
        return self.crop["alfa"] / self.crop[numeraire]

    def at_ratio(self, ratio: float, numeraire: str = "corn") -> Prices:
        """Same vector with alfalfa repriced to ``ratio`` x the numeraire. The `R`-arm axis."""
        crop = dict(self.crop)
        crop["alfa"] = ratio * crop[numeraire]
        return replace(self, crop=crop, label=f"{self.label}@ratio={ratio:g}")


# -- named scenarios ---------------------------------------------------------------------
# Idaho marketing-year averages, USDA NASS Crop Values 2024 Summary (cpvl0225.pdf): alfalfa hay
# p.32, barley p.19, corn for grain p.16. Barley is priced as grain because that is what the
# model reports -- harv.ops `gn_barl` applies a biomass harvest index of 0.54, and the GRACEnet
# measurements it is calibrated against are grain.
_NASS = {  # year: (alfalfa hay $/ton, barley $/bu, corn grain $/bu)
    2022: (272.00, 7.61, 7.37),
    2023: (204.00, 7.76, 5.53),
    2024: (154.00, 6.70, 5.80),
}

# -- water: a sourced composite, $ per mm per ha ------------------------------------------
#
# The field is in the Twin Falls Canal Company tract (gravity diversion at Milner Dam). TFCC
# charges a flat per-share assessment -- its IRS 990 shows ~$5.6M program-service revenue over
# ~202,700 acres, ~$27/acre/yr -- so within the allotment the *marginal* cost of a mm from the
# canal company is zero. What a mm actually costs at the margin is two things, both published:
#
# 1. **Opportunity cost: the Water District 1 rental pool.** *WD01 2025 Rental Pool
#    Procedures* (IDWR) §5.3, rentals "for purposes above Milner": common-pool Tier 1 $25.18/af
#    + 10 % Board surcharge + $1.30 administrative fee = **$29.00/af all-in**. Assigned-storage
#    tiers 5-7 (§10.7) are $35 / $45 / $55 depending on whether the system fills. A shareholder
#    can lease water at this price or forgo it by using it, which is the standard marginal value
#    of water for a canal-company irrigator.
# 2. **Pumping energy.** The field is sprinkler-irrigated from a ditch turnout. Idaho Power
#    Schedule 24 (Agricultural Irrigation Service, effective 2026-01-01), secondary service,
#    in-season: **6.7222 c/kWh** energy plus **$16.50/kW-month** demand. The tariff is exact;
#    converting it to $/mm needs a head and an efficiency, and those two are assumptions stated
#    here rather than measured: 45 m total dynamic head (a ~40 psi sprinkler plus lift and
#    friction) at 0.65 wire-to-water efficiency, and a 60 % in-season load factor to spread the
#    demand charge over kWh.
#
# The two sum to $0.43, which is where the old "~$50/acre-ft" placeholder ($0.41) happened to
# sit -- so nothing scored before 2026-09-14 moves materially, but the number now has a
# provenance. The sourced *range* is rental-only (furrow, or no pump) $0.235 up to Tier 7 plus
# pumping $0.65; the frontier and `water_breakeven` machinery cover it at no engine cost.

M3_PER_ACRE_FOOT = 1233.48

#: WD01 common-pool Tier 1, above Milner, 2025, all fees in. $/acre-foot.
WD01_RENTAL_AF = 25.18 * 1.10 + 1.30          # = 29.00
#: WD01 assigned-storage Tier 7 (system does not fill, no flow augmentation). The top of the
#: published range.
WD01_RENTAL_AF_TIER7 = 55.0

WATER_RENTAL = WD01_RENTAL_AF / M3_PER_ACRE_FOOT * M3_PER_MM_HA     # 0.235 $/mm/ha

#: Idaho Power Schedule 24, secondary, in-season, effective 2026-01-01.
IPC_SCHED24_ENERGY_PER_KWH = 0.067222
IPC_SCHED24_DEMAND_PER_KW_MONTH = 16.50
#: Stated assumptions for the pumping conversion -- not measured on site.
PUMP_HEAD_M = 45.0
PUMP_EFFICIENCY = 0.65
PUMP_LOAD_FACTOR = 0.60
HOURS_PER_MONTH = 730.0

#: kWh to lift 1 mm over 1 ha (10 m^3) through PUMP_HEAD_M: rho g V H / (3.6e6 eta).
PUMP_KWH_PER_MM_HA = 9810.0 * M3_PER_MM_HA * PUMP_HEAD_M / (3.6e6 * PUMP_EFFICIENCY)  # 1.89
WATER_PUMPING = PUMP_KWH_PER_MM_HA * (
    IPC_SCHED24_ENERGY_PER_KWH
    + IPC_SCHED24_DEMAND_PER_KW_MONTH / (HOURS_PER_MONTH * PUMP_LOAD_FACTOR))  # 0.198 $/mm/ha

#: The scored water price: rental opportunity cost plus pumping. **Sourced 2026-09-14**; was
#: the 0.41 placeholder before that.
DEFAULT_WATER = WATER_RENTAL + WATER_PUMPING                                  # 0.433

#: Sourced range for the water axis, $/mm/ha: rental only (no pump) to Tier 7 plus pumping.
WATER_PRICE_RANGE = (WATER_RENTAL,
                     WD01_RENTAL_AF_TIER7 / M3_PER_ACRE_FOOT * M3_PER_MM_HA + WATER_PUMPING)

#: Manure haul-and-spread, $/Mg as applied. **Sourced 2026-09-14**: Iowa State University
#: Extension, *2026 Iowa Farm Custom Rate Survey* (Ag Decision Maker A3-10, Johanns, March
#: 2026), "Loading, spreading solid manure": **$7.20 per ton**, median $6.50, range $5-9, n = 7,
#: labour, fuel and equipment included, materials not. $7.20 / 0.907185 = $7.94/Mg. It stands for
#: the labour and haulage of getting manure onto the field -- loading, trucking, spreading --
#: rather than a purchase price, because dairy manure here is a disposal stream that nobody buys.
#:
#: Iowa, not Idaho: the site-state survey (U of I BUL 1078, 2025) has no manure row at all, and
#: its one trucking figure ($10/ton, n = 1) is not a spreading rate. The Iowa row is the only
#: surveyed custom rate for exactly this operation, so it is used and its origin is stated.
#:
#: It was $5.00 (representative, unsourced) from 2026-08 to 2026-09-14 and zero before that, and
#: both moves matter in the same two directions:
#:
#: * The earlier manure null (+162 $/ha, `runs/exp1_nitrogen.json` lineage) was measured with
#:   manure **free**, the case most favourable to applying it. A positive cost only makes
#:   manure less attractive, so that null survives -- it gets stronger, not weaker.
#: * It **lowers the human bar**, because measured practice is manure-only: the shipped
#:   schedule hauls 234.4 Mg/ha over the rotation, which is ~$1,860/ha at this price. An
#:   optimizer that can substitute mineral N pays far less of that. So every "vs human" delta
#:   widens for a reason that is this number, not management skill. Any result that moves
#:   materially with it must be reported with its breakeven.
DEFAULT_MANURE = 7.20 / 0.907185

#: Mineral N, $/kg N. **Sourced**, unlike the two above: USDA AMS reported urea at $644/short
#: ton on average for the Inter-Mountain West in the week ending 2025-04-04 -- the regional
#: series that covers Idaho. Urea is 46 % N, so a short ton carries 2000 x 0.46 lb = 417.3 kg N
#: and $644 / 417.3 = $1.54/kg N.
#:
#: Two caveats it is worth being explicit about. It is a **2025** price against **2022-24**
#: crop prices; a period-matched average would be higher, since urea passed $1,000/ton in 2022.
#: And it is a *weekly regional average*, not a marketing-year average like the crop series.
#: Both errors point the same way -- N is cheaper here than a consistent vector would make it
#: -- which is the case most favourable to buying nitrogen, so an `N` null under this default
#: is a strong null, the same logic under which :data:`DEFAULT_MANURE` was long held at zero.
DEFAULT_FERT_N = 644.0 / (2000.0 * 0.46 * 0.453592)

#: Cost of one fertiliser *application pass*, $/ha, materials not included. **Sourced
#: 2026-09-14**: University of Idaho Extension, *Custom Rates for Idaho Agricultural
#: Operations: 2025* (BUL 1078, Wilder, Field & Hatzenbuehler, August 2025), Table 2 "Dry
#: Fertilizer Application": **$15.00 per acre**, n = 1 (north region). $15.00 / 0.404686 =
#: $37.07/ha. The comparable Iowa figure (ISU *2026 Iowa Farm Custom Rate Survey*, "Dry bulk -
#: applied") is $8.15/acre = $20.14/ha, median $8.00, range $4.00-13.50, n = 59; Idaho's own
#: liquid-application row is $12.69/acre (n = 8, range 9.50-15.00). The site-state value is
#: used because it is the site-state value, and it is a single response: treat the Iowa
#: figure as the lower end and report the breakeven wherever the pass count is load-bearing.
#:
#: Why the term exists at all is from CyclesGym 2.0 §2.5, which charges $5.0/ha/event as a
#: "soft constraint that naturally penalises excessive fertilisation frequency" instead of a
#: hard limit on application count. That framing is the right one: **without a per-event
#: charge, splitting nitrogen is free**, so any optimizer prefers unlimited applications and
#: the question "how many passes are worth it" has no answer. Their $5 was the default here
#: until 2026-09-14; it is 4-7x below any surveyed custom rate. A *low* pass cost favours more
#: splits, so a result showing few splits are optimal was stronger under $5 than it is under
#: $37 -- state that direction whenever the split count is reported.
DEFAULT_FERT_OP = 15.00 / 0.404686


def nass(year: int, *, water: float = DEFAULT_WATER, manure: float = DEFAULT_MANURE,
         fert_n: float = DEFAULT_FERT_N, fert_op: float = DEFAULT_FERT_OP,
         silage_multiplier: float = 9.0) -> Prices:
    """A price vector from a NASS marketing year, converted to $/Mg dry matter."""
    hay, barl_bu, corn_bu = _NASS[year]
    return Prices(
        crop={
            "alfa": _hay_to_mg_dm(hay),
            "barl": _grain_to_mg_dm(barl_bu, lb_per_bu=48.0, moisture=0.135),
            "corn": _silage_from_grain(corn_bu, multiplier=silage_multiplier),
        },
        water=water, manure=manure, fert_n=fert_n, fert_op=fert_op, label=f"NASS{year}",
    )


#: The marketing years averaged into :func:`average`. All three of the series we carry.
AVERAGE_YEARS = (2022, 2023, 2024)


def average(years: tuple[int, ...] = AVERAGE_YEARS, **kw) -> Prices:
    """The fixed price vector the focused experiments run at: a mean over marketing years.

    Averaging the **converted $/Mg DM vectors** rather than the raw NASS quotes, so the
    moisture and bushel-weight conversions are applied per year at that year's own price
    instead of to a mean of mixed units.

    What this does to the rotation question, stated once here rather than rediscovered later:
    the averaged alfalfa:corn ratio is **1.489** and Exp 1b put the rotation crossover at
    **≈1.60**, so this vector sits on the annuals-win side by 0.11 of ratio -- while 2022 and
    2023 were each 1.63, on the other side. Holding prices fixed is deliberate (it is what
    makes the three experiments comparable), but it means a rotation result at this vector is
    a result *at this vector*. ``runs/exp1b_price_ratio.json`` holds the full curve.
    """
    vecs = [nass(y, **kw) for y in years]
    crop = {k: sum(v.crop[k] for v in vecs) / len(vecs) for k in vecs[0].crop}
    return replace(vecs[0], crop=crop, label=f"avg{years[0]}-{years[-1]}")


# -- reading what the run actually did ----------------------------------------------------

_FERT = re.compile(r"^\s*fert\s+\d+\s+\d+\s+\S+\s+(\S+)\s+\S+\s+([0-9.]+)", re.M)


def fert_applied(sch_text: str, frt_text: str) -> pd.DataFrame:
    """Every ``fert`` operation in a schedule, as mass and as nitrogen, classified by source.

    ``op_data3`` is the application rate in kg/ha, so mass is read directly rather than
    back-derived. The N cross-check is exact against ``basin_nb_yr.fertn``: the 2013 GRACEnet
    manure is 43,800 kg/ha at ``min_n`` 0.0026 + ``org_n`` 0.0104, giving 569.4 kg N/ha, which
    is what the engine reports.

    Both sources land in the same ``fert`` op, so they are told apart by product name against
    :data:`swat_gym.schedule.MANURE_SOURCES`. Without the ``kind`` split the reward would
    charge urea at the manure price -- zero -- and the `N` arm would get its nitrogen free.
    """
    from .schedule import MANURE_SOURCES

    comp = {}
    for line in frt_text.splitlines()[2:]:
        p = line.split()
        if len(p) >= 5:
            comp[p[0]] = float(p[1]) + float(p[3])  # min_n + org_n

    rows = [{"fert": name,
             "kind": "manure" if name in MANURE_SOURCES else "mineral",
             "mg_ha": float(kg) / 1000.0,
             "n_frac": comp.get(name, float("nan")),
             "n_kg_ha": float(kg) * comp.get(name, float("nan"))}
            for name, kg in _FERT.findall(sch_text)]
    return pd.DataFrame(rows, columns=["fert", "kind", "mg_ha", "n_frac", "n_kg_ha"])


def manure_applied(sch_text: str, frt_text: str) -> pd.DataFrame:
    """Just the manure rows of :func:`fert_applied`."""
    df = fert_applied(sch_text, frt_text)
    return df[df["kind"] == "manure"].reset_index(drop=True)


def profit(runner, prices: Prices, *, manure_mg: float | None = None,
           fert_n_kg: float | None = None, no3_price: float = 0.0) -> dict:
    """Rotation-total profit ($/ha) for a completed run, with the terms kept separable.

    ``manure_mg`` and ``fert_n_kg`` override the schedule-derived totals, for when the caller
    (an action) already knows what it applied. ``no3_price`` is the leaching penalty in $/kg N
    and defaults to **0** -- the ablation switch, not a baked-in externality price.
    """
    yields = runner.yields()
    wb = runner.read("hru_wb_yr.txt")
    aqu = runner.read("basin_aqu_yr.txt")

    unpriced = set(yields["plant_name"]) - set(prices.crop)
    if unpriced:
        raise KeyError(f"no price for {sorted(unpriced)}; have {sorted(prices.crop)}")

    revenue = float(sum(r["yld(t)"] * prices.crop[r["plant_name"]]
                        for _, r in yields.iterrows()))
    irrigation_mm = float(wb["irr"].sum())
    # The schedule is parsed whenever anything is unknown *or* an application pass is priced:
    # the pass count cannot be recovered from a caller-supplied total, since 400 kg N in one
    # pass and in four passes give the same total and different costs.
    n_events = 0
    manure_n_kg = None
    if manure_mg is None or fert_n_kg is None or prices.fert_op:
        sch = (runner.workdir / "management.sch").read_text()
        frt = (runner.workdir / "fertilizer.frt").read_text()
        applied = fert_applied(sch, frt)
        n_events = int((applied["mg_ha"] > 0).sum())
        # Organic N, for the emissions accounting only: it is priced by *mass* (manure_mg),
        # never by N content, so this must not touch any cost term below.
        manure_n_kg = float(applied.loc[applied["kind"] == "manure", "n_kg_ha"].sum())
        if manure_mg is None:
            manure_mg = float(applied.loc[applied["kind"] == "manure", "mg_ha"].sum())
        if fert_n_kg is None:
            fert_n_kg = float(applied.loc[applied["kind"] == "mineral", "n_kg_ha"].sum())
    no3 = float(aqu["no3_rchg"].sum())

    water_cost = irrigation_mm * prices.water
    manure_cost = manure_mg * prices.manure
    fert_cost = fert_n_kg * prices.fert_n
    # Every pass costs, manure or mineral: a manure spreader trip is a trip. For the cadence
    # sweep manure is pinned at zero, so there the charge is purely the mineral split count.
    op_cost = n_events * prices.fert_op
    leach_cost = no3 * no3_price

    if manure_n_kg is None:  # caller supplied both totals and no pass is priced
        manure_n_kg = 0.0
    n2o = ipcc_n2o(manure_n_kg=manure_n_kg, mineral_n_kg=float(fert_n_kg),
                   no3_leached_kg=no3)

    return {
        "label": prices.label,
        "revenue": revenue,
        "water_cost": water_cost,
        "manure_cost": manure_cost,
        "fert_cost": fert_cost,
        "op_cost": op_cost,
        "n_fert_events": n_events,
        "profit": revenue - water_cost - manure_cost - fert_cost - op_cost - leach_cost,
        # Reported alongside, never silently inside `profit` unless no3_price was set.
        "no3_leached_kg": no3,
        "leach_cost": leach_cost,
        # IPCC Tier 1 accounting; reported only, never priced into `profit`.
        **n2o,
        "irrigation_mm": irrigation_mm,
        "manure_mg": manure_mg,
        "fert_n_kg": fert_n_kg,
        "alfalfa_ratio": prices.alfalfa_ratio(),
    }
