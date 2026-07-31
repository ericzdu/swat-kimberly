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

    return names
