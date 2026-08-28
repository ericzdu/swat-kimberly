#!/usr/bin/env python3
"""Is the model on disk the model the documentation describes? Exits non-zero if not.

Two scripts write crop parameters and they used to fight silently. ``port_crops.py`` applies the
collaborator's workbook (CLAUDE.md rule 11b) and ``calibrate/optimize.py --apply`` applies the
fit; whichever ran last won, and nothing recorded which that was. The result, found 2026-08-28,
was a model in a state matching neither: barley and alfalfa carried workbook values while corn
still carried its fitted ``bm_e = 64.5`` and ``lai_pot = 4.95`` — the exact value rule 11b names
as the one that must not stand — plus three canopy-curve overrides that were retired in the code
comments and never undone in the file. Nobody noticed because every number involved is plausible.

The ownership boundary this enforces:

* **Workbook-owned** (rule 11b) — every column in :data:`port_crops.COLMAP` for corn, barley and
  alfalfa, and the ``gn_*`` harvest indices in ``harv.ops``, which must equal the workbook's
  ``HARV_EFF``. These are the collaborator's agronomy. The optimizer must never move them, and
  they are already absent from ``calibrate/optimize.py:PARAMS``.
* **Optimizer-owned** — the parameters in that ``PARAMS`` list, which have no workbook value.
  Their values are *reported*, not asserted: there is no source of truth for them other than the
  last fit, and pinning them here would just move the conflict.
* **Shared, and therefore the dangerous one** — ``alfa.lai_min`` is optimizer-owned but is also
  written by ``port_crops.OVERRIDES``. The two must agree, so that re-porting is idempotent
  rather than a silent revert.

    uv run python scripts/check_param_state.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.abspath(str(ROOT / "scripts")))

from swat_gym.params import get_value  # noqa: E402

from port_crops import COLMAP, CROP_MAP, OVERRIDES  # noqa: E402

TIO = ROOT / "model" / "TxtInOut"
CROP_CSV = ROOT / "data" / "crop_params_swat.csv"
HARVEST = {"CSIL": "gn_corn", "BARL": "gn_barl", "ALFA": "gn_alfa"}
TOL = 1e-4


def workbook_drift() -> list[tuple[str, str, float, float]]:
    """Every workbook-owned value that no longer matches the workbook."""
    txt = (TIO / "plants.plt").read_text()
    header = txt.splitlines()[1].split()
    wb = pd.read_csv(CROP_CSV).set_index("CPNM")
    out = []
    for code, plt in CROP_MAP.items():
        for idx, (field, scale) in COLMAP.items():
            col = header[idx]
            cur = get_value(txt, "plants.plt", plt, col)
            book = float(wb.loc[code, field]) * scale
            if abs(cur - book) > TOL * max(1.0, abs(book)):
                out.append((plt, col, cur, book))
    return out


def harvest_drift() -> list[tuple[str, str, float, float]]:
    """``harv.ops`` harvest indices against the workbook's ``HARV_EFF``."""
    wb = pd.read_csv(CROP_CSV).set_index("CPNM")
    txt = (TIO / "harv.ops").read_text()
    out = []
    for code, row in HARVEST.items():
        cur = get_value(txt, "harv.ops", row, "harv_idx")
        book = float(wb.loc[code, "HARV_EFF"])
        if abs(cur - book) > TOL:
            out.append((row, "harv_idx", cur, book))
    return out


def shared_drift() -> list[tuple[str, str, float, float]]:
    """Parameters both writers touch. They must agree or re-porting silently reverts a fit."""
    txt = (TIO / "plants.plt").read_text()
    out = []
    for (row, col), (value, _why) in OVERRIDES.items():
        cur = get_value(txt, "plants.plt", row, col)
        if abs(cur - value) > TOL * max(1.0, abs(value)):
            out.append((row, col, cur, value))
    return out


def integer_columns_intact() -> list[str]:
    """``days_mat``/``yrs_mat`` must stay integer tokens under rev 62's list-directed read.

    Written as ``120.00000`` they mis-parse and shift every later column on the row, producing
    fake temperature stress and ~3.5 t/ha corn while the run completes normally.
    """
    txt = (TIO / "plants.plt").read_text()
    bad = []
    for plt in CROP_MAP.values():
        line = next(l for l in txt.splitlines() if l.split()[:1] == [plt])
        # Indices are into the split data row, which aligns with the header row token for
        # token. Read them from the header rather than hard-coding a guess: 13 is not
        # ``yrs_mat`` (37 is), and the wrong index reports three false failures.
        header = txt.splitlines()[1].split()
        for idx, name in ((header.index("days_mat"), "days_mat"),
                          (header.index("yrs_mat"), "yrs_mat")):
            tok = line.split()[idx]
            if "." in tok:
                bad.append(f"{plt}.{name} = {tok!r}")
    return bad


def main() -> None:
    problems = 0
    for title, rows, fix in (
        ("workbook-owned (rule 11b)", workbook_drift(),
         "uv run python scripts/port_crops.py"),
        ("harv.ops harvest indices", harvest_drift(),
         "uv run python scripts/port_crops.py  # then re-check harv.ops"),
        ("shared with port_crops.OVERRIDES", shared_drift(),
         "update OVERRIDES to the last applied fit, or re-run optimize.py --apply"),
    ):
        if rows:
            problems += len(rows)
            print(f"\nDRIFT — {title}:")
            print(f"  {'row':<10}{'column':<14}{'in model':>12}{'expected':>12}")
            for r, c, cur, exp in rows:
                print(f"  {r:<10}{c:<14}{cur:>12.5f}{exp:>12.5f}")
            print(f"  fix: {fix}")
        else:
            print(f"ok — {title}")

    bad = integer_columns_intact()
    if bad:
        problems += len(bad)
        print(f"\nDRIFT — integer columns written as floats (rev 62 column shift): {bad}")
    else:
        print("ok — days_mat/yrs_mat still integer tokens")

    # Reported, never asserted: no source of truth beyond the last fit.
    txt = (TIO / "plants.plt").read_text()
    print("\noptimizer-owned (reported, not checked):")
    for row, col in (("alfa", "lai_min"), ("corn", "days_mat"), ("barl", "days_mat")):
        print(f"  {row}.{col:<10} = {get_value(txt, 'plants.plt', row, col)}")
    for f, row, col in (("hydrology.hyd", "hyd1", "epco"), ("hydrology.hyd", "hyd1", "pet_co"),
                        ("parameters.bsn", "", "orgn_min"), ("parameters.bsn", "", "n_perc"),
                        ("nutrients.sol", "soilnut1", "fr_hum_act")):
        print(f"  {f}:{col:<12} = {get_value((TIO / f).read_text(), f, row, col)}")

    print(f"\n{'PASS' if problems == 0 else f'FAIL — {problems} drifted value(s)'}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
