"""Phase-0 tests: the regression gate, and the correctness properties FastRunner claims.

The fixture test is the load-bearing one. It pins this model's results to the engine that
produced them, so that swapping in a different SWAT+ build — a Linux ELF engine on WSL, say —
gives an immediate, diagnosable pass/fail on whether the two builds agree, rather than a
silent drift discovered halfway through an experiment.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swat_gym import EDITABLE, FastRunner, input_files
from swat_gym.fastrunner import TXTINOUT

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "baseline.json").read_text())

#: Loose enough to absorb compiler/libm differences between builds, tight enough that a real
#: behavioural divergence cannot hide. A failure here wants investigating, not relaxing.
RTOL = 1e-4


@pytest.fixture(scope="module")
def runner():
    with FastRunner() as r:
        yield r


@pytest.fixture(scope="module")
def baseline(runner):
    runner.run()
    return runner


# --- the regression gate ---------------------------------------------------------------

def test_yields_match_fixture(baseline):
    """Annual dry-matter yields reproduce the committed baseline."""
    got = baseline.yields()
    expected = FIXTURE["yields"]
    assert len(got) == len(expected), f"{len(expected)} harvest years expected, got {len(got)}"

    deviations = []
    for row, exp in zip(got.itertuples(), expected):
        assert row.year == exp["year"]
        assert row.plant_name == exp["crop"]
        assert getattr(row, "_4") == exp["cuts"], f"{exp['year']}: cut count changed"
        actual = getattr(row, "_5")
        deviations.append((exp["year"], abs(actual - exp["yld_t"]) / exp["yld_t"]))

    worst = max(deviations, key=lambda d: d[1])
    assert worst[1] < RTOL, (
        f"Yield mismatch vs fixture, worst in {worst[0]}: {worst[1]:.2e} relative. "
        f"If the engine binary changed, this is build disagreement — see fixtures/baseline.json."
    )


def test_water_balance_matches_fixture(baseline):
    wb = baseline.read("hru_wb_yr.txt")
    for key, exp in FIXTURE["water_mean"].items():
        assert wb[key].mean() == pytest.approx(exp, rel=RTOL), f"{key} drifted"


def test_nitrogen_stress_matches_fixture(baseline):
    """The mechanism variable behind the README's N-limitation finding."""
    pw = baseline.read("hru_pw_yr.txt")
    got = {int(y): s for y, s in zip(pw["yr"], pw["strsn"])}
    assert got == pytest.approx(
        {int(k): v for k, v in FIXTURE["nstress_days"].items()}, rel=RTOL
    )


def test_corn_is_n_stressed_and_alfalfa_is_not(baseline):
    """A property, not a number: the finding Exp 1 is built on must hold.

    The 20-day floor is deliberately NOT tracked down as the model improves. It was
    41 d before the orgn_min fix, 33 d after it, and 26.6 d after the wgn port — a
    monotone decline toward the threshold. Tripping it means the annual/perennial
    N asymmetry Exp 1 is premised on has stopped holding, which wants investigating
    (and re-premising Exp 1), not relaxing.
    """
    pw = baseline.read("hru_pw_yr.txt")
    stress = {int(y): s for y, s in zip(pw["yr"], pw["strsn"])}
    assert stress[2018] > 20, (
        f"2018 corn ran {stress[2018]:.1f} d of N stress, below the 20 d floor. "
        "Exp 1's premise is that the annuals are N-limited where alfalfa is not; "
        "if corn is no longer stressed, re-premise the experiment rather than "
        "lowering this bound."
    )
    assert stress[2016] == 0, "alfalfa fixes its own N and should show none"


# --- correctness properties ------------------------------------------------------------

def test_manifest_excludes_committed_outputs():
    """The source dir has results committed next to inputs; only inputs get copied."""
    names = input_files(TXTINOUT)
    assert "file.cio" in names and "management.sch" in names
    assert "tfccpcp.pcp" in names, "weather series is referenced via pcp.cli, not file.cio"
    assert not any(n.endswith(".csv") for n in names)
    for output in ("basin_crop_yld_yr.txt", "basin_wb_yr.txt", "area_calc.out"):
        assert output not in names, f"{output} is an output and must not be in the manifest"
    assert len(names) < len(list(TXTINOUT.iterdir())) / 2


def test_edits_change_results(runner):
    """An edit must actually reach the engine — otherwise the search optimizes nothing."""
    runner.run()
    base = runner.yields()["yld(t)"].sum()

    sch = (TXTINOUT / "management.sch").read_text()
    halved = sch.replace("43800.00000", "4380.00000").replace("48000.00000", "4800.00000")
    assert halved != sch, "manure rates not found in management.sch — test is stale"

    runner.run({"management.sch": halved})
    starved = runner.yields()["yld(t)"].sum()
    assert starved < base, "cutting manure 10x should reduce yield in an N-limited model"


def test_edits_do_not_leak_between_runs(runner):
    """Run n's edit must not survive into run n+1."""
    sch = (TXTINOUT / "management.sch").read_text()
    runner.run({"management.sch": sch.replace("43800.00000", "4380.00000")})
    edited = runner.yields()["yld(t)"].sum()

    runner.run()  # no edits — must return to baseline
    restored = runner.yields()["yld(t)"].sum()
    expected = sum(y["yld_t"] for y in FIXTURE["yields"])
    assert restored != pytest.approx(edited)
    assert restored == pytest.approx(expected, rel=RTOL)


def test_stale_outputs_are_cleared(runner):
    """A table from a previous run must never be readable as this run's result."""
    runner.run()
    marker = runner.workdir / "basin_crop_yld_yr.txt"
    marker.write_text("POISONED\n")
    sentinel = runner.workdir / "leftover_from_last_run.txt"
    sentinel.write_text("stale\n")

    runner.run()
    assert not sentinel.exists(), "non-input files must be swept before each run"
    assert "POISONED" not in marker.read_text()


def test_rejects_writes_outside_the_editable_set(runner):
    with pytest.raises(ValueError, match="Refusing to write"):
        runner.run({"plants.plt": "should never be written by an action"})
    assert "plants.plt" not in EDITABLE


def test_trimmed_print_prt_still_emits_every_needed_table(baseline):
    for table in ("basin_crop_yld_yr.txt", "hru_wb_yr.txt", "hru_pw_yr.txt",
                  "basin_nb_yr.txt", "basin_aqu_yr.txt",
                  "hru_wb_mon.txt", "hru_pw_mon.txt"):
        assert (baseline.workdir / table).is_file(), f"{table} was trimmed away"
    assert not list(baseline.workdir.glob("*.csv")), "csvout should be off"


def test_read_strips_units_row(baseline):
    """hru_wb_yr and friends carry a units row that would force string dtype."""
    wb = baseline.read("hru_wb_yr.txt")
    assert wb["et"].dtype.kind == "f"
    assert "mm" not in wb["yr"].astype(str).values
    assert wb["yr"].min() >= 2012
