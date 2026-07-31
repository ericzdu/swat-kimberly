"""Translate an action vector into the SWAT+ input files that express it.

One :class:`YearAction` per decision year becomes ``management.sch`` operations plus the
``irr.ops`` entries they reference. Everything else about the model is left alone.

Two conventions this relies on
------------------------------
**Year boundaries are implied by date order.** A SWAT+ ``management.sch`` is one flat op list
with no year column; the engine advances a year whenever the next operation's date falls
*before* the previous one's. The shipped measured schedule confirms it -- ``hvkl 8/10 barl``
is followed by ``fert 4/10``, which is what rolls 2012 into 2013. So each year's ops are
emitted in date order and simply concatenated.

**Irrigation is parameterized, not enumerated.** ``EXPERIMENTS.md`` gates this: exposing the
158 measured daily ``irrm`` events as actions forces sub-annual cadence and a ~40 s episode.
The decision-table route was spiked first and **failed** -- both ``irr_opt_sw_unlim`` and
``irr_str8_unlim`` exit the engine with code 24 -- so this uses the documented fallback, a
fixed-interval schedule parameterized by ``(start day, interval, depth)``. That is also the
more deterministic choice for RL: no decision-table semantics between the action and the water.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

CROPS = ("corn", "barl", "alfa")

#: Field calendar per crop, taken from the measured GRACEnet schedule's own dates so a
#: generated schedule is comparable to the baseline rather than to an invented calendar.
#: Alfalfa is multi-cut; the others are plant-once/harvest-once.
CALENDAR = {
    "corn": {"plant": (5, 16), "harvest": (9, 20)},
    "barl": {"plant": (4, 9), "harvest": (8, 15)},
    "alfa": {"plant": (4, 16), "cuts": [(5, 28), (7, 12), (9, 8)]},
}

#: harv.ops type per crop — the reference harvest-index overrides appended by port_management.
HARV_OPS = {"corn": "gn_corn", "barl": "gn_barl", "alfa": "gn_alfa"}

#: The four measured GRACEnet manure compositions, as the action's discrete `source` choice.
MANURE_SOURCES = ("gn2013", "gn2014", "gn2018", "gn2019")

#: Mineral fertiliser product. **Urea only, deliberately.** `fertilizer.frt` also carries
#: `elem_n`, `46_00_00` and `anh_nh3`, and product choice is a real lever — urea carries
#: `nh3_n` 1.0 and so volatilises, while `46_00_00` does not. It is held fixed here because
#: Exp 1 asks whether *N management* pays, not which bag to buy, and because only urea has a
#: price series we sourced. Exposed as a constant so it can be varied rather than trusted.
MINERAL_SOURCE = "urea"

#: min_n fraction of the mineral product, read off `fertilizer.frt`. Used to convert an action
#: expressed in **kg N/ha** into the kg of *product* that `op_data3` wants.
MINERAL_N_FRAC = {"urea": 0.46, "elem_n": 1.00, "46_00_00": 0.46, "anh_nh3": 0.82}

#: Tillage used to incorporate manure, per Bierer et al. 2022 §2.3 (disked to 15 cm).
INCORPORATION_TILL = "gn_disk"

#: ``eff_frac`` written into every generated ``irr.ops`` entry. **1.0, and it must match the
#: measured record**, which is the whole reason this is a named constant rather than a literal.
#:
#: It was 0.85 -- the value on the shipped ``sprinkler_med`` entry -- while all 158 measured
#: ``gn####`` events carry 1.00000. ``hru_wb.irr`` reports water *post*-efficiency, so a
#: generated plan asking for 30 mm delivered 25.5 while the measured schedule delivered what it
#: asked for. Over the rotation the grid emits 120 events: 120 x 30 = 3,600 mm requested, and
#: 3,600 x 0.85 = 3,060.0 mm is exactly what came back out of ``hru_wb_yr`` against a measured
#: 3,938.8. Every generated row was therefore under-irrigated by 15 % relative to the human bar
#: it was scored against, which is not a lever anyone chose -- alfalfa ran 65-100 water-stress
#: days and lost 14-23 % of yield for it.
#:
#: A conveyance loss is a real thing to model, but it has to apply to both sides of a
#: comparison, and the reward charges for delivered water (``rewarders.profit``), so an
#: efficiency below 1 also hands back the lost fraction for free. If application efficiency is
#: ever wanted as a lever it belongs in the action vector and in the price, not hard-coded here.
IRR_EFF = 1.0

#: Growing-season months for monthly irrigation (April–September).
GROWING_MONTHS = (4, 5, 6, 7, 8, 9)


@dataclass
class YearAction:
    """One year's management decision."""

    crop: str = "corn"
    manure_mg: float = 0.0          #: Mg/ha as applied
    manure_doy: int = 100           #: day of year
    manure_src: str = "gn2013"
    fert_n_kg: float = 0.0          #: mineral N, kg N/ha (**not** kg of product)
    fert_doy: int = 120             #: day of year
    fert_src: str = MINERAL_SOURCE
    #: Split mineral-N program as ``((day-of-year, kg N/ha), ...)``, one entry per application.
    #: When non-empty it **replaces** the single ``fert_n_kg``/``fert_doy`` application, so the
    #: scalar path stays byte-identical for every caller that predates splitting.
    #:
    #: Day-of-year, not month: Exp 1 optimises application *timing* as a continuous lever and
    #: was already pinning against its range floor, so month resolution would quantise away
    #: the thing being measured. Callers that think in months pass ``_doy(month, 1)``.
    fert_splits: tuple[tuple[int, float], ...] = ()
    irr_start_doy: int = 140
    irr_interval: int = 7           #: days between events
    irr_depth: float = 25.0         #: mm per event
    #: When set, overrides ``(irr_start_doy, irr_interval, irr_depth)``. Six values for
    #: April–September (mm applied mid-month as a single ``irrm`` event). Empty months are
    #: skipped. The annual fixed-interval schedule nests here via
    #: :func:`swat_gym.monthly.annual_to_monthly`.
    irr_month_depths: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.crop not in CROPS:
            raise ValueError(f"unknown crop {self.crop!r}; expected one of {CROPS}")
        if self.manure_src not in MANURE_SOURCES:
            raise ValueError(f"unknown manure source {self.manure_src!r}")
        if self.fert_src not in MINERAL_N_FRAC:
            raise ValueError(f"unknown mineral source {self.fert_src!r}")
        if self.irr_month_depths is not None and len(self.irr_month_depths) != 6:
            raise ValueError("irr_month_depths must have length 6 (Apr–Sep)")


def _md(doy: int, year: int = 2015) -> tuple[int, int]:
    """Day-of-year -> (month, day), on a non-leap reference year."""
    d = date(year, 1, 1) + timedelta(days=int(doy) - 1)
    return d.month, d.day


def _doy(mon: int, day: int, year: int = 2015) -> int:
    return (date(year, mon, day) - date(year, 1, 1)).days + 1


def _op(typ: str, mon: int, day: int, d1: str, d2: str = "null", d3: float = 0.0) -> str:
    return (f"{'':>48}{typ:<10}{mon:>6}{day:>10}{0.0:>14.5f}"
            f"{d1:>18}{d2:>18}{d3:>14.5f}  \n")


def _year_ops(action: YearAction, *, plant: bool, terminate: bool, irr_name: str) -> list[tuple[int, str]]:
    """(day-of-year, rendered op) for one year, unsorted."""
    crop, cal = action.crop, CALENDAR[action.crop]
    ops: list[tuple[int, str]] = []

    if action.manure_mg > 0:
        doy = int(action.manure_doy)
        ops.append((doy, _op("fert", *_md(doy), action.manure_src, "broadcast",
                             action.manure_mg * 1000.0)))
        # Incorporation the day after, matching the measured practice.
        ops.append((doy + 1, _op("till", *_md(doy + 1), INCORPORATION_TILL)))

    # Mineral N. `op_data3` is kg of *product*, so an action in kg N/ha is divided by the
    # product's min_n. Left on the surface rather than incorporated: broadcast urea is the
    # normal practice, and it is also what exposes the `nh3_n` 1.0 volatilisation loss the
    # engine models. Incorporating it here would quietly hand the lever free N.
    frac = MINERAL_N_FRAC[action.fert_src]
    if action.fert_splits:
        # Split program: one application per (day-of-year, rate) entry.
        for doy, kg_n in action.fert_splits:
            if kg_n <= 0:
                continue
            doy = int(doy)
            ops.append((doy, _op("fert", *_md(doy), action.fert_src, "broadcast",
                                 kg_n / frac)))
    elif action.fert_n_kg > 0:
        doy = int(action.fert_doy)
        ops.append((doy, _op("fert", *_md(doy), action.fert_src, "broadcast",
                             action.fert_n_kg / frac)))

    if plant:
        ops.append((_doy(*cal["plant"]), _op("plnt", *cal["plant"], crop)))

    if crop == "alfa":
        cuts = cal["cuts"]
        for i, (mon, day) in enumerate(cuts):
            last = terminate and i == len(cuts) - 1
            ops.append((_doy(mon, day),
                        _op("hvkl" if last else "harv", mon, day, crop, HARV_OPS[crop])))
        end_doy = _doy(*cuts[-1])
    else:
        mon, day = cal["harvest"]
        ops.append((_doy(mon, day), _op("hvkl", mon, day, crop, HARV_OPS[crop])))
        end_doy = _doy(mon, day)

    # Irrigation. Monthly depths take precedence over the fixed-interval triple so the
    # open-loop monthly arm and the annual default share one renderer.
    if action.irr_month_depths is not None:
        for mon, depth in zip(GROWING_MONTHS, action.irr_month_depths):
            if depth <= 0:
                continue
            # Prefer mid-month; if that is at/after harvest, place on the last day before it
            # so nested annual totals are not silently dropped.
            doy = _doy(mon, 15)
            if doy >= end_doy:
                doy = end_doy - 1
                if doy < _doy(mon, 1):
                    continue  # harvest before this month starts
                mon, day = _md(doy)
            else:
                day = 15
            month_name = f"{irr_name}_m{mon}"
            ops.append((doy, _op("irrm", mon, day, month_name)))
    elif action.irr_depth > 0 and action.irr_interval > 0:
        doy = int(action.irr_start_doy)
        while doy < end_doy:
            ops.append((doy, _op("irrm", *_md(doy), irr_name)))
            doy += int(action.irr_interval)

    return ops


def build(actions: list[YearAction], *, spinup: list[tuple[int, str]] | None = None,
          name: str = "kimb_rot") -> dict[str, str]:
    """Render ``actions`` to ``{filename: content}``, ready for :meth:`FastRunner.run`.

    ``actions[0]`` is the first *decision* year. The 2012 barley spin-up is emitted ahead of
    them unchanged unless ``spinup`` overrides it, so every arm shares an identical start state.
    """
    irr_lines: list[str] = []
    blocks: list[str] = []

    if spinup is None:
        spinup_action = YearAction(crop="barl", manure_mg=0.0, irr_depth=0.0)
        spin_ops = _year_ops(spinup_action, plant=True, terminate=True, irr_name="none")
        blocks.append("".join(op for _, op in sorted(spin_ops, key=lambda t: t[0])))

    for i, action in enumerate(actions):
        prev = actions[i - 1].crop if i else None
        nxt = actions[i + 1].crop if i + 1 < len(actions) else None
        # A perennial stand is planted once and terminated when the rotation moves on.
        plant = not (action.crop == "alfa" and prev == "alfa")
        terminate = not (action.crop == "alfa" and nxt == "alfa")

        irr_name = f"gy{i:02d}"
        if action.irr_month_depths is not None:
            for mon, depth in zip(GROWING_MONTHS, action.irr_month_depths):
                if depth <= 0:
                    continue
                month_name = f"{irr_name}_m{mon}"
                irr_lines.append(
                    f"{month_name:<22}{float(depth):>10.5f}{IRR_EFF:>14.5f}{0.0:>14.5f}"
                    f"{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}  \n"
                )
        else:
            irr_lines.append(
                f"{irr_name:<22}{action.irr_depth:>10.5f}{IRR_EFF:>14.5f}{0.0:>14.5f}"
                f"{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}  \n"
            )
        ops = _year_ops(action, plant=plant, terminate=terminate, irr_name=irr_name)
        # Year block must stay non-empty: SWAT+ advances years by date order alone, so a
        # collapsed block silently shifts the rest of the rotation.
        if not ops:
            raise ValueError(f"year {i} produced no management ops — refusing empty block")
        blocks.append("".join(op for _, op in sorted(ops, key=lambda t: t[0])))

    body = "".join(blocks)
    n_ops = body.count("\n")
    sch = (
        "management.sch: written by swat_gym.schedule\n"
        "name                                       numb_ops  numb_auto            op_typ"
        "       mon       day        hu_sch          op_data1          op_data2      op_data3  \n"
        f"{name:<37}{n_ops:>7}{0:>11}  \n"
        + body
    )
    return {"management.sch": sch, "irr.ops": _irr_ops(irr_lines)}


def _irr_ops(new_lines: list[str]) -> str:
    """Append generated entries to the shipped irr.ops rather than replacing it.

    The 158 measured ``gn####`` events must survive: the ``baseline`` arm still references them.
    """
    from .fastrunner import TXTINOUT

    base = (TXTINOUT / "irr.ops").read_text().rstrip("\n").splitlines(keepends=True)
    return "".join(base) + "\n" + "".join(new_lines)
