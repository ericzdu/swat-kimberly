"""Agronomic feasibility for a rotation plan.

Unconstrained search finds degenerate optima -- corn nine years running, or manure at the
bound every year -- that are not agronomy but artefacts of an unbounded action space.
``EXPERIMENTS.md`` names three rules; they are implemented here as a **repair** rather than a
rejection.

Repair, not reject, because the search sees a dense reward either way. Rejecting infeasible
plans gives an optimizer (or a policy) a flat, uninformative penalty region it has to random-walk
out of; projecting them onto the nearest feasible plan means every action maps to a real field
outcome and the gradient stays meaningful. The cost is that several actions can map to the same
plan, which is recorded in :func:`violations` so an experiment can report how often it bit.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .schedule import MANURE_SOURCES, MINERAL_N_FRAC, YearAction

#: Minimum years an alfalfa stand must run once established. A stand is expensive to establish
#: and is not torn out after one season; three years is the site's own rotation length.
MIN_ALFALFA_STAND = 3

#: Maximum consecutive corn years, a standard agronomic limit on corn-on-corn.
MAX_CONSECUTIVE_CORN = 2

#: Agronomic nitrogen loading cap, kg N/ha/yr. Set at roughly the N removal of the most
#: demanding crop in the rotation, which is the usual basis for a manure permit. This is a
#: **policy choice, not a measurement** -- vary it if the `N` arm turns out to sit against it.
#:
#: It binds on **manure and mineral N together**. Capping each separately would let a plan
#: apply 400 kg N as manure and another 400 as urea, which is not a cap; it would also make
#: the two sources non-substitutable, and substitution is the question Exp 1 asks.
MAX_N_LOADING = 400.0

#: N fraction (min_n + org_n) of each measured GRACEnet manure, from fertilizer.frt.
MANURE_N_FRAC = {"gn2013": 0.0130, "gn2014": 0.0195, "gn2018": 0.0041, "gn2019": 0.0041}


def max_manure_mg(source: str, max_n: float = MAX_N_LOADING) -> float:
    """Largest application of ``source`` that stays inside the loading cap."""
    return max_n / (MANURE_N_FRAC[source] * 1000.0)


def _set_mineral(action: YearAction, target_kg: float) -> YearAction:
    """Scale the year's mineral N to ``target_kg``, **preserving the number of passes**.

    Clipping must not change the cadence: if it zeroed trailing splits instead of scaling all
    of them, a k=7 plan pushed against the cap would silently become a k=4 plan and the whole
    cadence comparison would be measuring the constrainer.
    """
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
    """Mineral nitrogen for the year, kg N/ha, however the action expressed it.

    A split program supersedes the single application (the same precedence
    :func:`swat_gym.schedule._year_ops` applies when it writes the ops), so the cap sees the
    program's *sum* rather than double-counting a scalar the schedule never emitted.
    """
    if action.fert_splits:
        return float(sum(kg for _, kg in action.fert_splits))
    return action.fert_n_kg


def total_n(action: YearAction) -> float:
    """Nitrogen applied from both sources, kg N/ha -- what :data:`MAX_N_LOADING` bounds.

    Manure N is ``min_n + org_n``, i.e. total N applied rather than plant-available N. The
    mineral term is already in kg N by construction, since the action carries N and
    :mod:`swat_gym.schedule` converts to product mass when it writes the op.
    """
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
            # A stand running to the end of the horizon is truncated by the horizon, not by
            # the plan, so it is not a violation.
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
    """Project a plan onto the nearest feasible one, left to right.

    Ordering matters and is deliberate: rotation structure is fixed first, because extending an
    alfalfa stand changes which years exist to carry manure, and only then is the N cap applied.
    """
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

    # 3. N loading: clip to the shared cap, keeping the chosen sources and timing.
    #    Mineral N gives way first. Manure at this site is a disposal stream the grower is
    #    taking anyway, so the realistic decision is how much urea to buy *on top of* it --
    #    clipping urea first models that. Manure is clipped only if it breaches the cap alone.
    if max_n is not None:
        for k in range(n):
            a = out[k]
            m_n = manure_n(a)
            if m_n > max_n:
                out[k] = _set_mineral(
                    replace(a, manure_mg=max_manure_mg(a.manure_src, max_n)), 0.0)
            elif m_n + mineral_n(a) > max_n:
                out[k] = _set_mineral(a, max_n - m_n)

    # 4. Alfalfa fixes its own nitrogen; fertilising it is not a real management option here
    #    and would let the optimizer park surplus N in a year that does not need it. Applies
    #    to both sources — otherwise the mineral lever inherits exactly the loophole that
    #    zeroing manure was added to close.
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
