"""The model on disk must match the parameter ownership the documentation claims.

This is a *state* test, not a behaviour test: it reads input files and compares them to their
declared source. It exists because two writers — ``scripts/port_crops.py`` (the collaborator's
workbook, CLAUDE.md rule 11b) and ``scripts/calibrate/optimize.py --apply`` (the fit) — both
write ``plants.plt``, and whichever ran last won with nothing recording which that was.

Found 2026-08-28: barley and alfalfa carried workbook values while corn still carried its fitted
``bm_e = 64.5`` and ``lai_pot = 4.95`` — the value rule 11b names explicitly as the one that must
not stand — together with three canopy-curve overrides retired in the code comments and never
undone in the file. Every number involved is plausible on its own, so nothing failed and the
scorecard in PROVENANCE §6 quietly stopped describing the model.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, os.path.abspath(str(ROOT / "scripts")))

check = pytest.importorskip("check_param_state")


def test_workbook_owned_parameters_match_the_workbook():
    """Rule 11b: the crop coefficients are the collaborator's and are not ours to fit."""
    drift = check.workbook_drift()
    assert not drift, (
        "workbook-owned crop parameters have been moved — run "
        "`uv run python scripts/port_crops.py`:\n"
        + "\n".join(f"  {r}.{c}: model {cur:.5f} vs workbook {exp:.5f}" for r, c, cur, exp in drift)
    )


def test_harvest_indices_match_the_workbook_harv_eff():
    """The ``gn_*`` rows are where SWAT+ actually reads the harvest index from."""
    drift = check.harvest_drift()
    assert not drift, "\n".join(
        f"{r}.{c}: model {cur:.5f} vs workbook HARV_EFF {exp:.5f}" for r, c, cur, exp in drift)


def test_shared_parameters_agree_between_their_two_writers():
    """``alfa.lai_min`` is fitted but also written by ``port_crops.OVERRIDES``.

    If the two disagree, the next ``port_crops.py`` run silently reverts the fit — which is
    precisely the failure this module was written after.
    """
    drift = check.shared_drift()
    assert not drift, "\n".join(
        f"{r}.{c}: model {cur:.5f} vs port_crops.OVERRIDES {exp:.5f}"
        for r, c, cur, exp in drift)


def test_maturity_columns_are_still_integer_tokens():
    """``days_mat = 120.00000`` mis-parses under rev 62 and shifts every later column.

    The run still completes and reports plausible nonsense (~3.5 t/ha corn on fake temperature
    stress), so only a format check catches it.
    """
    bad = check.integer_columns_intact()
    assert not bad, f"integer columns written as floats: {bad}"
