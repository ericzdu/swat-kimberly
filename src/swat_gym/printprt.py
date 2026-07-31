"""Rewriting ``print.prt`` to emit only the output tables a run actually needs.

The shipped model prints daily *and* yearly *and* average-annual tables for ~every SWAT+
object, in both ``.txt`` and ``.csv``. Writing that is a large share of the non-engine cost
and none of it is read by the reward. Trimming is purely an I/O change: it alters which
results are *written*, never what is *simulated*.

Flag positions are edited in place, character for character, so column alignment survives
untouched — SWAT+ reads this file positionally in places and is unforgiving about it.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

INTERVALS = ("daily", "monthly", "yearly", "avann")

#: Tables the Exp-1 reward and diagnostics read. ``basin_crop_yld_*`` is not an object row —
#: it is governed by the ``crop_yld`` flag in the header block, which is left alone.
GYM_OUTPUTS: dict[str, set[str]] = {
    "basin_nb": {"yearly"},              # N budget: fertn, fixn, nuptake, mineralisation
    "basin_aqu": {"yearly"},             # no3_rchg — the leaching externality
    # Monthly water / plant-stress tables are the mid-season observation channel for the
    # monthly-cadence env. Yearly rows stay for open-loop scoring and the annual path.
    "hru_wb": {"monthly", "yearly"},     # irr, et, pet, perc, sw_final
    "hru_pw": {"monthly", "yearly"},     # strsn, strsw
}

_FLAG = re.compile(r"(?<!\S)[yn](?!\S)")
# Header value lines are not all y/n — `crop_yld` takes 'a'/'y'/'b' — so the header path
# matches any single-character token and edits only the columns it was asked to.
_ANY_FLAG = re.compile(r"(?<!\S)\S(?!\S)")
_ROW = re.compile(r"^(\s*)(\S+)(\s+)(.*?)(\s*)$")


def _set_flags(line: str, wanted: set[str]) -> str:
    """Rewrite one object row's four interval flags, preserving every column position."""
    m = _ROW.match(line)
    if not m:
        return line
    lead, name, gap, rest, tail = m.groups()
    positions = [mm.start() for mm in _FLAG.finditer(rest)]
    if len(positions) != len(INTERVALS):
        return line  # not a flag row we understand; leave it exactly as found
    chars = list(rest)
    for pos, interval in zip(positions, INTERVALS):
        chars[pos] = "y" if interval in wanted else "n"
    return f"{lead}{name}{gap}{''.join(chars)}{tail}"


def trim(
    text: str,
    keep: Mapping[str, set[str]] = GYM_OUTPUTS,
    *,
    csvout: bool = False,
    mgtout: bool = False,
) -> str:
    """Return ``print.prt`` content emitting only ``keep`` (plus the crop-yield table).

    ``keep`` maps object name -> intervals to print. Objects absent from it are silenced.
    ``csvout`` and ``mgtout`` default off: the CSV copies duplicate the ``.txt`` tables we
    parse, and ``mgt_out.txt`` is a per-operation diagnostic log the gym never reads.

    The simulation-control fields — ``nyskip``, the date range, ``crop_yld`` — are not touched.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_objects = False

    for i, line in enumerate(lines):
        if in_objects:
            m = _ROW.match(line)
            name = m.group(2) if m else ""
            out.append(_set_flags(line, keep.get(name, set())))
            continue

        # Header block: the flag *values* sit on the line after their label line.
        prev = lines[i - 1] if i else ""
        if prev.split()[:1] == ["csvout"]:
            line = _set_flags_named(line, prev, {"csvout": csvout})
        elif prev.split()[:1] == ["crop_yld"]:
            line = _set_flags_named(line, prev, {"mgtout": mgtout})

        out.append(line)
        if line.split()[:1] == ["objects"]:
            in_objects = True

    return "\n".join(out) + "\n"


def _set_flags_named(values: str, labels: str, wanted: Mapping[str, bool]) -> str:
    """Set named single-char flags on a header value line, by column index of the label."""
    names = labels.split()
    positions = [mm.start() for mm in _ANY_FLAG.finditer(values)]
    if len(positions) != len(names):
        return values  # unexpected layout; safer to leave it untouched
    chars = list(values)
    for pos, name in zip(positions, names):
        if name in wanted:
            chars[pos] = "y" if wanted[name] else "n"
    return "".join(chars)
