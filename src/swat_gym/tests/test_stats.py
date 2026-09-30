"""Windows split and paired statistics (rule 7)."""
from __future__ import annotations

import pytest

from swat_gym.experiments.common import paired
from swat_gym.windows import TEST_YEARS, TRAIN_YEARS, effective_n, window_years


def test_train_and_test_share_no_calendar_years():
    train = {y for s in TRAIN_YEARS for y in window_years(s)}
    test = {y for s in TEST_YEARS for y in window_years(s)}
    assert not train & test


def test_test_ess_is_1_25():
    assert effective_n(TEST_YEARS) == pytest.approx(1.25, abs=0.01)


def test_paired_has_no_se_key_and_uses_ess():
    a = [{"profit": p, "start_year": s} for p, s in zip([10, 20, 30, 40, 55], TEST_YEARS)]
    b = [{"profit": 0.0, "start_year": s} for s in TEST_YEARS]
    p = paired(a, b)
    assert "se" not in p
    assert p["se_ess"] > p["se_naive"]
    assert p["per_window"] == [10, 20, 30, 40, 55]
