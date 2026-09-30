"""Input file set of a TxtInOut, from file.cio plus weather files (named in .cli) and the engine."""
from __future__ import annotations

from pathlib import Path

FILE_CIO = "file.cio"


def _tokens(line: str) -> list[str]:
    return [t for t in line.split() if t and t != "null"]


#: Inputs whose absence silently corrupts output (engine still exits 0). Fail early.
REQUIRED = frozenset({
    "file.cio", "time.sim", "print.prt",
    "plants.plt",        # crop parameter database — silent corruption when absent
    "management.sch", "irr.ops", "fertilizer.frt", "tillage.til", "harv.ops",
    "hru.con", "hru-data.hru", "soils.sol", "plant.ini",
})


def input_files(txtinout: Path) -> set[str]:
    """Names of files SWAT+ reads; declared-but-missing entries skipped."""
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
