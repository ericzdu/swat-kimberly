"""Trim print.prt to the needed output tables (I/O only). Flags edited in place; file is positional."""
from __future__ import annotations

import re
from collections.abc import Mapping

INTERVALS = ("daily", "monthly", "yearly", "avann")

#: Tables the reward and diagnostics read (crop yield is controlled by the header flag).
GYM_OUTPUTS: dict[str, set[str]] = {
    "basin_nb": {"yearly"},              # N budget: fertn, fixn, nuptake, mineralisation
    "basin_aqu": {"yearly"},             # no3_rchg — the leaching externality
    "basin_ls": {"yearly"},              # surqno3, lat3no3, tileno3 — the soil-N loss terms
    # Monthly for the monthly env's obs; yearly for scoring.
    "hru_wb": {"monthly", "yearly"},     # irr, et, pet, perc, sw_final
    "hru_pw": {"monthly", "yearly"},     # strsn, strsw
}

_FLAG = re.compile(r"(?<!\S)[yn](?!\S)")
# Header flags can be any single char (crop_yld uses a/y/b).
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
    """print.prt emitting only ``keep`` {object: intervals}; others silenced. Sim control untouched."""
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
