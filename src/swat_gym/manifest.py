"""Which files in a ``TxtInOut`` are *inputs*.

This repo's ``model/TxtInOut`` has SWAT+ output files committed alongside the inputs (14 MB,
238 files, most of it results). Copying all of that per run is what makes the ``runner.py``
path 3.9 s against a 0.42 s engine.

``file.cio`` is SWAT+'s own manifest of what it reads, so we derive the input set from it
rather than hardcoding a list — a scenario change that adds an input file stays covered.
Two things ``file.cio`` does not name directly:

* the weather data files, which are named *inside* the ``.cli`` index files it points at;
* the engine binary itself.

Both are added explicitly.
"""
from __future__ import annotations

from pathlib import Path

FILE_CIO = "file.cio"


def _tokens(line: str) -> list[str]:
    return [t for t in line.split() if t and t != "null"]


#: Inputs whose absence corrupts a run **without** failing it.
#:
#: `input_files` deliberately skips declared-but-missing entries because SWAT+ tolerates a
#: missing *optional* input. `plants.plt` is not optional: deleted, the engine still exits 0
#: and still writes `basin_crop_yld_yr.txt`, but the crop-name column contains entries from its
#: internal file table (`checker.out`, `hru_wb_mon.txt`) — it reads past the end of the plant
#: array into adjacent memory. Downstream that surfaces as a `UnicodeDecodeError` from pandas
#: on a NUL byte, which points at the reader rather than the cause and cost an hour to trace.
#: Fail at construction instead.
REQUIRED = frozenset({
    "file.cio", "time.sim", "print.prt",
    "plants.plt",        # crop parameter database — silent corruption when absent
    "management.sch", "irr.ops", "fertilizer.frt", "tillage.til", "harv.ops",
    "hru.con", "hru-data.hru", "soils.sol", "plant.ini",
})


def input_files(txtinout: Path) -> set[str]:
    """Return the names of every file SWAT+ reads from ``txtinout``.

    Names only (not paths) — SWAT+ resolves everything relative to its working directory.
    Entries listed in ``file.cio`` but absent from disk are skipped: SWAT+ tolerates a
    declared-but-missing optional input, so their absence is not an error here.
    """
    cio = txtinout / FILE_CIO
    if not cio.is_file():
        raise FileNotFoundError(f"{cio} not found — is {txtinout} a SWAT+ TxtInOut?")

    names = {FILE_CIO}
    for line in cio.read_text().splitlines()[1:]:  # line 0 is the editor's title banner
        # Column 0 is the section label ("climate", "soils", …), not a filename.
        for token in _tokens(line)[1:]:
            if (txtinout / token).is_file():
                names.add(token)

    # The .cli index files name the actual weather series (e.g. pcp.cli -> tfccpcp.pcp).
    for cli in [n for n in names if n.endswith(".cli")]:
        for line in (txtinout / cli).read_text().splitlines()[2:]:  # title + column header
            for token in _tokens(line):
                if (txtinout / token).is_file():
                    names.add(token)

    missing = sorted(n for n in REQUIRED if not (txtinout / n).is_file())
    if missing:
        raise FileNotFoundError(
            f"{txtinout} is missing required SWAT+ input(s): {missing}. "
            "These do not fail the engine — it exits 0 and writes structurally valid output "
            "with garbage in it. Restore them (e.g. `git checkout -- model/TxtInOut/`) "
            "before running anything.")
    return names
