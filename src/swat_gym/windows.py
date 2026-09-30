"""Train/test weather windows (8 yr each) sharing zero calendar years.

Train starts 1995-2004 (end <= 2011); test starts 2013-2017. 2012 is a buffer.
"""
from __future__ import annotations

from .plan import N_YEARS, SPINUP, WEATHER_YEARS

WINDOW_LEN = N_YEARS + SPINUP  # 8


def window_years(start: int) -> range:
    """Calendar years covered by a window that starts at ``start``."""
    return range(start, start + WINDOW_LEN)


def spans_overlap(a: int, b: int) -> bool:
    return not (set(window_years(a)).isdisjoint(window_years(b)))


#: Train window starts: spans end ≤ 2011.
TRAIN_YEARS = list(range(1995, 2005))  # 10 windows, last span 2004–2011

#: Test window starts: spans begin ≥ 2013.
TEST_YEARS = list(range(2013, 2018))   # 5 windows, spans 2013–2020 … 2017–2024


def assert_no_leakage(train: list[int] = TRAIN_YEARS, test: list[int] = TEST_YEARS) -> None:
    """Raise if any train window shares a calendar year with any test window."""
    train_years = {y for s in train for y in window_years(s)}
    test_years = {y for s in test for y in window_years(s)}
    leak = train_years & test_years
    if leak:
        raise AssertionError(f"train/test share calendar years: {sorted(leak)}")


# Fail loudly at import if the constants drift.
assert_no_leakage()

# Weather record must cover the latest test span.
_lo, _hi = WEATHER_YEARS
assert min(TRAIN_YEARS) >= _lo
assert max(TEST_YEARS) + WINDOW_LEN - 1 <= _hi


# Windows overlap, so use ESS, not n (rule 7).

def overlap_fraction(a: int, b: int) -> float:
    """Share of calendar years two windows have in common, in ``[0, 1]``."""
    ya, yb = set(window_years(a)), set(window_years(b))
    return len(ya & yb) / WINDOW_LEN


def overlap_matrix(starts: list[int]) -> list[list[float]]:
    """Correlation proxy: fraction of shared calendar years."""
    return [[overlap_fraction(a, b) for b in starts] for a in starts]


def effective_n(starts: list[int]) -> float:
    """ESS = n² / ΣΣ ρ_ij (1.25 for the test set)."""
    n = len(starts)
    if n <= 1:
        return float(n)
    total = sum(sum(row) for row in overlap_matrix(starts))
    return float(n * n / total) if total > 0 else float(n)


#: Effective sample size of the held-out set — the divisor any reported interval must use.
TEST_ESS = effective_n(TEST_YEARS)
