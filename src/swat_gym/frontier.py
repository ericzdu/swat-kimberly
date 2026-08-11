"""Profit–sustainability frontiers, computed exactly from stored rows.

**Why a frontier rather than a weighted objective.** Profit is the optimised objective and
sustainability the second one, but there is no defensible market price for either externality
at this site: the
farmer's water price does not reflect aquifer scarcity — which is *why* depletion is a problem
— and Idaho has no price for nitrate leaching at all. Picking one number for either would make
the result an artefact of that number. So both enter as **swept prices whose whole curve is
reported**, with the market-price arm always alongside, and claims are stated as *dominance*:
at matched profit, which strategy uses less water, or leaches less?

**Why this is free.** ``profit`` is linear in every price and
:func:`swat_gym.experiments._focused._row` stores the terms separably, so profit at any price
vector is arithmetic on a stored row — no engine runs. Only *re-optimising* at a new price
costs simulation. Re-scoring answers "how does this schedule fare if water gets dearer";
re-optimising answers "what schedule would you choose if it did". They are different questions
and the paper should not conflate them.

**λ_w and λ_n are not independent here, and that must be said.** In this model leaching is
driven by over-irrigation, not by fertiliser: holding irrigation at the measured rate, nitrogen
dose produces exactly zero leaching at every rate up to 4,490 kg N/ha, while raising applied
water 20 % produces 32 kg N/ha. Both prices therefore act on the same lever — water — so the
two axes are partly redundant rather than orthogonal, and a two-dimensional grid will show
correlated rather than independent movement.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

#: Market-price arm: the placeholder ``DEFAULT_WATER``. Always reported alongside any sweep.
SCORED_WATER = 0.41
#: Profit-only arm.
SCORED_NO3 = 0.0


def profit_at(row: dict, water_price: float, no3_price: float = SCORED_NO3) -> float:
    """One window's profit at an arbitrary price vector, exactly, from stored terms.

    Reconstructed from the separable identity rather than adjusted from a scored value, so the
    result does not depend on what the row was originally priced at.
    """
    return float(row["revenue"]
                 - water_price * row["irrigation_mm"]
                 - row["manure_cost"] - row["fert_cost"] - row["op_cost"]
                 - no3_price * row["no3"])


def mean_profit_at(rows: Sequence[dict], water_price: float,
                   no3_price: float = SCORED_NO3) -> float:
    """Mean over weather windows at a price vector."""
    return float(np.mean([profit_at(r, water_price, no3_price) for r in rows]))


def intensities(rows: Sequence[dict]) -> dict:
    """Per-unit-output resource use — the axis that survives a pinned nitrogen lever.

    In an irrigation experiment nitrogen is held constant, so total N₂O is constant across arms
    and tells you nothing. Emissions *intensity* still moves, because yield does: a schedule
    that grows more from the same nitrogen emits less per tonne. That is the standard
    agricultural LCA framing and it costs nothing to report.
    """
    def m(k):
        vals = [r[k] for r in rows if r.get(k) is not None]
        return float(np.mean(vals)) if vals else None

    y, water, no3, n2o = m("yield_mg"), m("irrigation_mm"), m("no3"), m("n2o_kg")
    n_app = m("fert_n_kg")
    out = {"yield_mg": y, "irrigation_mm": water, "no3_kg": no3, "n2o_kg": n2o}
    if y:
        out |= {"water_mm_per_Mg": water / y if water is not None else None,
                "no3_kg_per_Mg": no3 / y if no3 is not None else None,
                "n2o_kg_per_Mg": n2o / y if n2o is not None else None}
    if n_app:
        out["n_use_efficiency"] = y / n_app if y else None
    return out


def dominates(a: Sequence[dict], b: Sequence[dict], *,
              water_price: float = SCORED_WATER, no3_price: float = SCORED_NO3) -> bool:
    """Does ``a`` beat ``b`` on profit **and** use no more water **and** leach no more?

    A dominance claim needs no price at all, which is why it is the strongest form the
    sustainability result can take: "at matched profit, X leaches less" survives any reader's
    disagreement about what nitrate is worth.
    """
    pa, pb = mean_profit_at(a, water_price, no3_price), mean_profit_at(b, water_price, no3_price)
    wa = float(np.mean([r["irrigation_mm"] for r in a]))
    wb = float(np.mean([r["irrigation_mm"] for r in b]))
    na, nb = float(np.mean([r["no3"] for r in a])), float(np.mean([r["no3"] for r in b]))
    return pa >= pb and wa <= wb and na <= nb


def sweep(strategies: dict[str, Sequence[dict]], water_grid: Iterable[float],
          no3_grid: Iterable[float] = (SCORED_NO3,)) -> list[dict]:
    """Re-score every strategy across the price grid. Zero engine runs.

    Returns one record per (λ_w, λ_n) with each strategy's profit and the winner, so the paper
    can report where — if anywhere — the ranking changes. A ranking that never changes is
    itself the result: the winner dominates rather than trading off.
    """
    out = []
    for w in water_grid:
        for n in no3_grid:
            scores = {k: mean_profit_at(rows, w, n) for k, rows in strategies.items()}
            best = max(scores, key=scores.get)
            out.append({"water_price": float(w), "no3_price": float(n),
                        "profit": scores, "winner": best})
    return out


def crossing(a: Sequence[dict], b: Sequence[dict], *, axis: str = "water",
             scored_water: float = SCORED_WATER,
             scored_no3: float = SCORED_NO3) -> float | None:
    """Price at which ``a``'s advantage over ``b`` vanishes, or ``None`` if it never does.

    Profit is linear in the price, so this is exact. ``None`` means the advantage does not
    depend on that price (identical usage) or never reverses — report it as "holds for any
    price", which converts an unsourced placeholder into a bounded claim.
    """
    key = "irrigation_mm" if axis == "water" else "no3"
    scored = scored_water if axis == "water" else scored_no3
    adv = mean_profit_at(a, scored_water, scored_no3) - mean_profit_at(b, scored_water, scored_no3)
    d = float(np.mean([r[key] for r in a]) - np.mean([r[key] for r in b]))
    if abs(d) < 1e-9:
        return None
    x = scored + adv / d
    return float(x) if x >= 0 else None
