"""FastRunner must agree with the reference implementation, exactly.

``swat_kimberly.runner.KimberlySwat`` is the path that produced the README's results table.
FastRunner is an I/O optimization over it, so any disagreement is a bug in FastRunner —
not a tolerance to widen. Marked slow because it runs the 3-4 s pySWATPlus path.
"""
from __future__ import annotations

import pytest

from swat_gym import FastRunner


@pytest.mark.slow
def test_bit_identical_to_reference_runner():
    from swat_kimberly.runner import KimberlySwat

    reference = KimberlySwat()
    run_dir = reference.run()
    ref = reference.read_table(run_dir, "basin_crop_yld_yr.txt")
    ref = ref[ref["yld(t)"] > 0].reset_index(drop=True)

    with FastRunner() as fast:
        fast.run()
        got = fast.yields()

    merged = ref[["year", "plant_name", "yld(t)"]].merge(
        got[["year", "plant_name", "yld(t)"]],
        on=["year", "plant_name"],
        suffixes=("_ref", "_fast"),
    )
    assert len(merged) == len(ref), "harvest years differ between the two paths"
    diff = (merged["yld(t)_ref"] - merged["yld(t)_fast"]).abs().max()
    assert diff == 0.0, f"FastRunner diverged from runner.py by {diff}"
