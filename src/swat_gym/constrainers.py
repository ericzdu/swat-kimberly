"""Agronomic feasibility, enforced by repair (projection), not rejection. See violations()."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .schedule import MANURE_SOURCES, MINERAL_N_FRAC, YearAction

#: Minimum alfalfa stand length, years.
MIN_ALFALFA_STAND = 3

#: Maximum consecutive corn years, a standard agronomic limit on corn-on-corn.
MAX_CONSECUTIVE_CORN = 2

#: N loading cap, kg N/ha/yr, on manure + mineral combined. A policy choice, not a measurement.
MAX_N_LOADING = 400.0

#: N fraction (min_n + org_n) of each measured GRACEnet manure, from fertilizer.frt.
MANURE_N_FRAC = {"gn2013": 0.0130, "gn2014": 0.0195, "gn2018": 0.0041, "gn2019": 0.0041}


def max_manure_mg(source: str, max_n: float = MAX_N_LOADING) -> float:
    """Largest application of ``source`` that stays inside the loading cap."""
    return max_n / (MANURE_N_FRAC[source] * 1000.0)


def _set_mineral(action: YearAction, target_kg: float) -> YearAction:
    """Scale mineral N to ``target_kg``, keeping the number of passes."""
    if not action.fert_splits:
        return replace(action, fert_n_kg=max(0.0, target_kg))
    current = mineral_n(action)
    if current <= 0:
        return action
    scale = max(0.0, target_kg) / current
    return replace(action,
                   fert_splits=tuple((m, kg * scale) for m, kg in action.fert_splits))


def manure_n(action: YearAction) -> float:
    """Nitrogen applied as manure, kg N/ha."""
    return action.manure_mg * MANURE_N_FRAC[action.manure_src] * 1000.0


def mineral_n(action: YearAction) -> float:
    """Year's mineral N, kg/ha (splits supersede the scalar, as in schedule)."""
    if action.fert_splits:
        return float(sum(kg for _, kg in action.fert_splits))
    return action.fert_n_kg


def total_n(action: YearAction) -> float:
    """Total N applied (manure min_n + org_n, plus mineral), kg/ha."""
    return manure_n(action) + mineral_n(action)


def violations(actions: Sequence[YearAction], *,
               max_n: float | None = MAX_N_LOADING) -> list[str]:
    """Every rule the plan breaks, as human-readable strings. Empty means feasible."""
    out: list[str] = []
    crops = [a.crop for a in actions]

    run = 0
    for i, c in enumerate(crops):
        run = run + 1 if c == "corn" else 0
        if run > MAX_CONSECUTIVE_CORN:
            out.append(f"year {i}: {run} consecutive corn years > {MAX_CONSECUTIVE_CORN}")

    i = 0
    while i < len(crops):
        if crops[i] == "alfa":
            j = i
            while j < len(crops) and crops[j] == "alfa":
                j += 1
            # Stand cut off by the horizon is not a violation.
            if (j - i) < MIN_ALFALFA_STAND and j < len(crops):
                out.append(f"year {i}: alfalfa stand of {j - i} < {MIN_ALFALFA_STAND} years")
            i = j
        else:
            i += 1

    for k, a in enumerate(actions):
        if max_n is not None and total_n(a) > max_n + 1e-6:
            out.append(
                f"year {k}: {total_n(a):.0f} kg N/ha "
                f"({manure_n(a):.0f} manure + {mineral_n(a):.0f} mineral) "
                f"> {max_n:.0f}"
            )
        if a.crop == "alfa" and (a.manure_mg > 0 or mineral_n(a) > 0):
            out.append(f"year {k}: N applied to alfalfa")
    return out


def repair(actions: Sequence[YearAction], *,
           max_n: float | None = MAX_N_LOADING) -> list[YearAction]:
    """Project a plan onto the nearest feasible one: rotation rules first, then N cap."""
    out = [replace(a) for a in actions]
    n = len(out)

    # 1. Alfalfa stands: extend any short stand forward to the minimum length.
    i = 0
    while i < n:
        if out[i].crop == "alfa":
            j = i
            while j < n and out[j].crop == "alfa":
                j += 1
            if (j - i) < MIN_ALFALFA_STAND and j < n:
                for k in range(i, min(i + MIN_ALFALFA_STAND, n)):
                    out[k] = replace(out[k], crop="alfa")
                j = min(i + MIN_ALFALFA_STAND, n)
            i = j
        else:
            i += 1

    # 2. Corn-on-corn: the year that would break the run becomes barley.
    run = 0
    for k in range(n):
        if out[k].crop == "corn":
            run += 1
            if run > MAX_CONSECUTIVE_CORN:
                out[k] = replace(out[k], crop="barl")
                run = 0
        else:
            run = 0

    # 3. N cap: clip mineral first; manure only if it alone exceeds the cap.
    if max_n is not None:
        for k in range(n):
            a = out[k]
            m_n = manure_n(a)
            if m_n > max_n:
                out[k] = _set_mineral(
                    replace(a, manure_mg=max_manure_mg(a.manure_src, max_n)), 0.0)
            elif m_n + mineral_n(a) > max_n:
                out[k] = _set_mineral(a, max_n - m_n)

    # 4. No N (either source) on alfalfa.
    for k in range(n):
        if out[k].crop == "alfa" and (out[k].manure_mg > 0 or mineral_n(out[k]) > 0):
            out[k] = _set_mineral(replace(out[k], manure_mg=0.0), 0.0)

    return out


def feasible(actions: Sequence[YearAction], *,
             max_n: float | None = MAX_N_LOADING) -> bool:
    return not violations(actions, max_n=max_n)


__all__ = ["MANURE_N_FRAC", "MAX_CONSECUTIVE_CORN", "MAX_N_LOADING", "MIN_ALFALFA_STAND",
           "MANURE_SOURCES", "MINERAL_N_FRAC", "feasible", "manure_n", "max_manure_mg",
           "mineral_n", "repair", "total_n", "violations"]
