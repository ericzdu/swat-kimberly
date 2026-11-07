"""LTM weather windows: a spin-up year then 8 scored seasons (the trial's length).

A window is named by its spin-up year s (the time.sim start); seasons are s+1 .. s+8.
Train and test share zero calendar years (CLAUDE.md rule 7); 2002 is a buffer. Since 2026-11-04
(user decision) the record is gridMET's whole span from 1979, split evenly: 15 train windows on
the older weather, 15 test windows on the newer (was 1995-2025, 7 + 7, ESS 1.34 each).
"""
from __future__ import annotations

from ..stats import effective_n

SEASONS = 8
WINDOW_LEN = SEASONS + 1           #: spin-up + seasons
WEATHER = (1979, 2025)             #: gridMET at the LTM field (scripts/port_gridmet.py --site ltm)

TRAIN = list(range(1979, 1994))    #: spans 1979-1987 ... 1993-2001 (15 windows)
TEST = list(range(2003, 2018))     #: spans 2003-2011 ... 2017-2025 (15 windows)


def years(s: int) -> range:
    return range(s, s + WINDOW_LEN)


def _check() -> None:
    tr = {y for s in TRAIN for y in years(s)}
    te = {y for s in TEST for y in years(s)}
    if tr & te:
        raise AssertionError(f"LTM train/test share years {sorted(tr & te)}")
    if min(TRAIN) < WEATHER[0] or max(TEST) + WINDOW_LEN - 1 > WEATHER[1]:
        raise AssertionError("LTM windows outrun the weather record")


_check()

TRAIN_ESS = effective_n(TRAIN, WINDOW_LEN)
TEST_ESS = effective_n(TEST, WINDOW_LEN)
