"""Turn a completed SWAT+ run into profit, with prices as an explicit experimental axis.

    profit = crop revenue - irrigation cost - manure cost - mineral N cost
             - application-pass cost

Nitrate leaching is deliberately **not** in that sum. Per ``EXPERIMENTS.md`` it is reported
alongside and run as an on/off ablation, so the result never depends on a shadow price for
nitrate that would have to be defended.

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

#: **PLACEHOLDER, not fetched.** Irrigation water in Idaho is priced by district and there is no
#: national series; ~$50/acre-foot is a mid-range surface-district figure, which is
#: $50 / 1233 m^3 x 10 m^3 = $0.41 per mm-ha. Override it with a real district rate before any
#: result about the `I` arm is reported as agronomic advice.
DEFAULT_WATER = 0.41

#: **ARBITRARY BY CONSTRUCTION.** $/Mg as applied, standing for the labour and haulage of
#: getting manure onto the field -- loading, trucking, spreading -- rather than a purchase
#: price. Dairy manure here is a disposal stream, so nobody buys it; what it costs is moving
#: it. $5/Mg sits inside the usual $3-6/ton custom solid-manure haul-and-spread range, but it
#: was chosen to be *representative*, not sourced, and it is the one number in this reward that
#: makes no claim to being measured.
#:
#: It was zero until now, and that mattered in two directions worth recording:
#:
#: * The earlier manure null (+162 $/ha, `runs/exp1_nitrogen.json` lineage) was measured with
#:   manure **free**, the case most favourable to applying it. A positive cost only makes
#:   manure less attractive, so that null survives -- it gets stronger, not weaker.
#: * It **lowers the human bar**, because measured practice is manure-only: the shipped
#:   schedule hauls 234.4 Mg/ha over the rotation, which is ~$1,172/ha at this price. An
#:   optimizer that can substitute mineral N pays far less of that. So every "vs human" delta
#:   widens for a reason that is this arbitrary number, not management skill. Any result that
#:   moves materially with it must be reported as contingent on it.
DEFAULT_MANURE = 5.0

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
#: is a strong null, the same logic that puts :data:`DEFAULT_MANURE` at zero.
DEFAULT_FERT_N = 644.0 / (2000.0 * 0.46 * 0.453592)

#: Cost of one fertiliser *application pass*, $/ha. Borrowed from CyclesGym 2.0 §2.5, which
#: uses $5.0/ha/event as a "soft constraint that naturally penalises excessive fertilisation
#: frequency" instead of a hard limit on application count. That framing is the right one and
#: is why this exists: **without a per-event charge, splitting nitrogen is free**, so any
#: optimizer prefers unlimited applications and the question "how many passes are worth it"
#: has no answer.
#:
#: Their $5/ha looks low — US custom-application rates for broadcast dry fertiliser run about
#: $8-10/acre, i.e. **$20-25/ha**. Their figure is kept as the default so the comparison to
#: the paper is direct, but it is the conservative end: a low pass cost favours *more* splits,
#: so a result showing few splits are optimal under $5/ha is the stronger version of that
#: result. Vary it if the cadence knee turns out to sit against it.
DEFAULT_FERT_OP = 5.0


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
    if manure_mg is None or fert_n_kg is None or prices.fert_op:
        sch = (runner.workdir / "management.sch").read_text()
        frt = (runner.workdir / "fertilizer.frt").read_text()
        applied = fert_applied(sch, frt)
        n_events = int((applied["mg_ha"] > 0).sum())
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
        "irrigation_mm": irrigation_mm,
        "manure_mg": manure_mg,
        "fert_n_kg": fert_n_kg,
        "alfalfa_ratio": prices.alfalfa_ratio(),
    }
