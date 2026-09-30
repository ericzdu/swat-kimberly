"""Profit-sustainability frontiers re-scored from stored rows (no engine runs).

Externalities are swept prices, never one fixed price; prefer dominance claims. Re-scoring
is not re-optimising. λ_w and λ_n are correlated: leaching is driven by over-irrigation.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from .rewarders import DEFAULT_WATER

#: Market-price arm; always reported alongside a sweep.
SCORED_WATER = DEFAULT_WATER
#: Profit-only arm.
SCORED_NO3 = 0.0


def profit_at(row: dict, water_price: float, no3_price: float = SCORED_NO3) -> float:
    """One window's profit at any prices, rebuilt from stored terms."""
    return float(row["revenue"]
                 - water_price * row["irrigation_mm"]
                 - row["manure_cost"] - row["fert_cost"] - row["op_cost"]
                 - no3_price * row["no3"])


def mean_profit_at(rows: Sequence[dict], water_price: float,
                   no3_price: float = SCORED_NO3) -> float:
    """Mean over weather windows at a price vector."""
    return float(np.mean([profit_at(r, water_price, no3_price) for r in rows]))


def intensities(rows: Sequence[dict]) -> dict:
    """Resource use per unit yield (varies even when N is pinned)."""
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
    """True if a >= b on profit and <= b on water and leaching."""
    pa, pb = mean_profit_at(a, water_price, no3_price), mean_profit_at(b, water_price, no3_price)
    wa = float(np.mean([r["irrigation_mm"] for r in a]))
    wb = float(np.mean([r["irrigation_mm"] for r in b]))
    na, nb = float(np.mean([r["no3"] for r in a])), float(np.mean([r["no3"] for r in b]))
    return pa >= pb and wa <= wb and na <= nb


def sweep(strategies: dict[str, Sequence[dict]], water_grid: Iterable[float],
          no3_grid: Iterable[float] = (SCORED_NO3,)) -> list[dict]:
    """Re-score all strategies per (λ_w, λ_n); one record each with the winner."""
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
    """Price where a's advantage over b vanishes; None if it never does."""
    key = "irrigation_mm" if axis == "water" else "no3"
    scored = scored_water if axis == "water" else scored_no3
    adv = mean_profit_at(a, scored_water, scored_no3) - mean_profit_at(b, scored_water, scored_no3)
    d = float(np.mean([r[key] for r in a]) - np.mean([r[key] for r in b]))
    if abs(d) < 1e-9:
        return None
    x = scored + adv / d
    return float(x) if x >= 0 else None
