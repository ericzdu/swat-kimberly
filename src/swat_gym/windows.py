"""Train / test weather-window splits with **zero shared calendar years**.

A window spans ``start_year .. start_year + N_YEARS + SPINUP - 1`` (8 calendar years).
The old split ``TRAIN=1995..2011``, ``TEST=2012..2018`` let the 2011 training window cover
2011–2018 and the 2012 test window cover 2012–2019 — seven shared years. CMA-ES and PPO
were therefore optimising and evaluating on largely the same weather.

With weather 1995–2025 available:
- train starts 1995–2004 → spans end at most 2011
- test starts 2013–2017 → spans 2013–2024

That is 10 train and 5 test windows, with a one-year buffer (2012) unused.
"""
from __future__ import annotations

from .env import N_YEARS, SPINUP, WEATHER_YEARS

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


# -- how much independent evidence five overlapping windows actually carry -------------------
#
# Test windows are eight calendar years long and start one year apart, so the 2013 and 2014
# windows share seven of their eight years. Their profits are therefore strongly correlated and
# a standard error computed as ``sd / sqrt(5)`` claims roughly twice the precision the design
# bought. `CLAUDE.md` rule 7 forbids reporting that number; these helpers give the replacement.

def overlap_fraction(a: int, b: int) -> float:
    """Share of calendar years two windows have in common, in ``[0, 1]``."""
    ya, yb = set(window_years(a)), set(window_years(b))
    return len(ya & yb) / WINDOW_LEN


def overlap_matrix(starts: list[int]) -> list[list[float]]:
    """Correlation *proxy* between windows: the fraction of calendar years they share.

    This is a proxy, not a fitted correlation. It is the assumption that two windows covary in
    proportion to the weather they literally have in common, which is conservative in the sense
    that matters here — it never claims two overlapping windows are independent. Fitting the
    real correlation from five points would be estimating a 5×5 matrix from five numbers.
    """
    return [[overlap_fraction(a, b) for b in starts] for a in starts]


def effective_n(starts: list[int]) -> float:
    """Effective sample size of a mean over correlated windows: ``n² / ΣΣ ρ_ij``.

    The variance of a mean of correlated unit-variance terms is ``ΣΣ ρ_ij / n²``, so this is the
    number of *independent* windows that would give the same precision. For the five test
    starts 2013–2017 it is **1.25**: five overlapping eight-year windows carry a little over one
    window's worth of independent weather. Report intervals against this, never against ``n``.
    """
    n = len(starts)
    if n <= 1:
        return float(n)
    total = sum(sum(row) for row in overlap_matrix(starts))
    return float(n * n / total) if total > 0 else float(n)


#: Effective sample size of the held-out set — the divisor any reported interval must use.
TEST_ESS = effective_n(TEST_YEARS)
