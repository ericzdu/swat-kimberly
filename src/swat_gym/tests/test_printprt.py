"""``print.prt`` is read positionally by SWAT+, so column alignment is load-bearing."""
from __future__ import annotations

from pathlib import Path

from swat_gym.fastrunner import TXTINOUT
from swat_gym.printprt import GYM_OUTPUTS, trim

ORIGINAL = (TXTINOUT / "print.prt").read_text()


def test_column_positions_are_preserved():
    """Every line keeps its exact width and field offsets; only flag characters change."""
    trimmed = trim(ORIGINAL)
    for before, after in zip(ORIGINAL.splitlines(), trimmed.splitlines()):
        assert len(before) == len(after), f"width changed:\n{before!r}\n{after!r}"
        for i, (b, a) in enumerate(zip(before, after)):
            if b != a:
                assert b in "ynab" and a in "yn", f"non-flag char changed at {i}: {b!r}->{a!r}"


def test_requested_objects_are_kept_and_others_silenced():
    lines = trim(ORIGINAL).splitlines()
    start = next(i for i, l in enumerate(lines) if l.split()[:1] == ["objects"]) + 1
    for line in lines[start:]:
        parts = line.split()
        if len(parts) != 5:
            continue
        name, flags = parts[0], parts[1:]
        on = {iv for iv, f in zip(("daily", "monthly", "yearly", "avann"), flags) if f == "y"}
        assert on == GYM_OUTPUTS.get(name, set()), f"{name}: expected {GYM_OUTPUTS.get(name, set())}, got {on}"


def test_simulation_controls_are_untouched():
    """Trimming changes what is written, never what is simulated."""
    before, after = ORIGINAL.splitlines(), trim(ORIGINAL).splitlines()
    assert after[2] == before[2], "nyskip / date range must not change"
    assert after[8].split()[0] == before[8].split()[0], "crop_yld flag must not change"


def test_csvout_and_mgtout_are_disabled():
    lines = trim(ORIGINAL).splitlines()
    csv_labels = next(i for i, l in enumerate(lines) if l.split()[:1] == ["csvout"])
    assert lines[csv_labels + 1].split()[0] == "n"
    yld_labels = next(i for i, l in enumerate(lines) if l.split()[:1] == ["crop_yld"])
    assert lines[yld_labels + 1].split()[1] == "n", "mgtout should be off in the hot path"


def test_keeping_everything_off_is_a_no_op_on_structure():
    """An empty keep-set must still produce a parseable file of the same shape."""
    trimmed = trim(ORIGINAL, {})
    assert len(trimmed.splitlines()) == len(ORIGINAL.splitlines())
    assert "objects" in trimmed
