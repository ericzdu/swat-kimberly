"""Port the reference model's remaining parameters — the ones no earlier port claimed.

**Source: the calibrated ArcSWAT reference model** (`TxtInOut-2`, HRU 119 / subbasin 14 —
the same Kimberly GRACEnet field). `port_soil.py`, `port_nutrients.py` and
`port_management.py` between them covered the soil profile, initial nutrients, topography,
basin N cycling and every management operation. Auditing `000140001.*` against the SWAT+
tree turned up a further set that was never ported and still carried **A10 template
defaults**:

* ``CN2`` — the reference's ``.mgt`` sets 75; the SWAT+ tree resolved to **81** through
  ``landuse.lum -> cntable.lum:legr_strow_g``. Six curve-number points is not cosmetic on a
  furrow-irrigated silt loam: it moves the runoff/infiltration split, and therefore
  percolation, which is the signal ``pet_co`` was provisionally rescaled to rescue.
* ``USLE_P`` (1.00 vs the template's 0.75 cross-slope) and ``OV_N`` (0.14 vs 0.19).
* The **snow block**. ``SMFMN`` is 0.1 in the reference against a template 4.5 — a factor of
  45 on the December melt factor, which sets how much of the snowpack leaves before spring.
* The **groundwater file**. ``000140001.gw`` was never read at all, so specific yield,
  revap threshold, the ``GWQMN`` return-flow threshold and the initial water-table height
  were all A10 values. ``revap`` and ``rchg_dp`` happened to match already.
* The **phosphorus block** of ``basins.bsn`` and three stragglers (``SDNCO``, ``SPCON`` /
  ``SPEXP``, ``CN_FROZ``).

What is deliberately *not* reverted to the reference: initial soil nitrate and labile P,
``orgn_min``, soil bulk density and the 2014/2019 irrigation depths. Those are GRACEnet
primary measurements that outrank the reference — see ``port_nutrients.py`` and
``port_soil.py`` for the argument in each case.

    uv run python scripts/port_reference_params.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"

#: Name given to the rows this script adds to the shared NRCS lookup tables. The tables ship
#: as generic land-cover lookups; the reference's values are site measurements and do not
#: belong in a row that claims to describe "close-seeded legumes" everywhere.
SITE_ROW = "kimb_ref"

# ---------------------------------------------------------------------------------------
# 000140001.mgt / 000140001.hru
# ---------------------------------------------------------------------------------------

#: ``CN2 : Initial SCS CN II value`` from ``000140001.mgt``. Soil 80295 is hydrologic group
#: **C**, so ``cn_c`` is the only column SWAT+ will read for this HRU. The other three keep
#: the group spacing of the template row they replace (``legr_strow_g``, 58/72/81/85) so the
#: row stays interpretable if the soil group ever changes; they are not reference values.
REF_CN2_C = 75.0
_CN_OFFSETS = {"cn_a": -23.0, "cn_b": -9.0, "cn_c": 0.0, "cn_d": 4.0}

#: ``OV_N : Manning's "n" value for overland flow`` from ``000140001.hru``.
REF_OV_N = 0.14

#: ``USLE_P : USLE support practice factor`` from ``000140001.mgt``. 1.00 is "no support
#: practice", which is what ``cons_practice.lum:up_down_slope`` already encodes — so this one
#: is a pointer change in ``landuse.lum``, not a new table row.
REF_CONS_PRACTICE = "up_down_slope"

# ---------------------------------------------------------------------------------------
# basins.bsn snow block -> snow.sno
# ---------------------------------------------------------------------------------------

#: SWAT+ column -> (value, SWAT2012 name). ``fall_tmp``, ``melt_max``, ``tmp_lag``,
#: ``snow_h2o`` and ``cov50`` already matched the reference and are listed for the audit.
REF_SNOW = {
    "fall_tmp": (1.0, "SFTMP"),      # already matched
    "melt_tmp": (2.0, "SMTMP"),      # was 0.5
    "melt_max": (4.5, "SMFMX"),      # already matched
    "melt_min": (0.1, "SMFMN"),      # was 4.5 -- a factor of 45
    "tmp_lag": (1.0, "TIMP"),        # already matched
    "snow_h2o": (1.0, "SNOCOVMX"),   # already matched
    "cov50": (0.5, "SNO50COV"),      # already matched
}

# ---------------------------------------------------------------------------------------
# 000140001.gw -> aquifer.aqu (shallow aquifer row)
# ---------------------------------------------------------------------------------------

#: SWAT+ column -> (value, SWAT2012 name). SWAT+ carries the two depth thresholds in
#: **metres** where SWAT2012 used millimetres, hence the /1000.
#:
#: ``hl_no3n`` comes from ``basins.bsn:HLIFE_NGW_BSN`` (5 days), not from the HRU ``.gw``
#: file, whose ``HLIFE_NGW`` is 0 — SWAT2012 reads 0 as "use the basin value".
#:
#: Not ported: ``dep_bot``. The reference has no aquifer-bottom parameter; its nearest
#: relative is ``DEP_IMP`` (6000 mm), which SWAT2012 only reads when the perched-water-table
#: routine is on (``IWTDN``/``wtable`` = 0 here). The template's 10 m stands.
REF_AQUIFER = {
    "dep_wt": (1.0, "GWHT"),            # was 3.0 m
    "alpha_bf": (0.048, "ALPHA_BF"),    # was 0.05
    "revap": (0.02, "GW_REVAP"),        # already matched
    "rchg_dp": (0.05, "RCHRG_DP"),      # already matched
    "spec_yld": (0.003, "GW_SPYLD"),    # was 0.05 -- a factor of ~17
    "hl_no3n": (5.0, "HLIFE_NGW_BSN"),  # was 30 days
    "flo_min": (1.0, "GWQMN/1000"),     # was 3.0 m
    "revap_min": (0.75, "REVAPMN/1000"),  # was 5.0 m
}
AQUIFER_SHALLOW = "aqu10"

# ---------------------------------------------------------------------------------------
# basins.bsn -> parameters.bsn / codes.bsn
# ---------------------------------------------------------------------------------------

#: The phosphorus block plus three stragglers. ``port_nutrients.py`` owns the nitrogen
#: parameters and ``orgn_min``; nothing here overlaps with it.
REF_BASIN = {
    "p_uptake": (10.0, "P_UPDIS"),      # was 20.0
    "p_perc": (11.0, "PPERCO"),         # was 10.0
    "p_soil": (150.0, "PHOSKD"),        # was 175.0
    "p_avail": (0.30, "PSP"),           # was 0.40
    "denit_frac": (1.0, "SDNCO"),       # was 1.30
    "lin_sed": (0.0001, "SPCON"),       # was 0.0
    "exp_sed": (1.0, "SPEXP"),          # was 0.0
    "cn_froz": (0.000862, "CN_FROZ"),   # was 0.0
    # Reach evaporation adjustment. Template left this at 0.6; the reference is 1.0.
    # On a 1 ha single-HRU build the channel is tiny, so the lever is nearly inert — still
    # ported so the basin table is not an unexplained A10 leftover.
    "evap_adj": (1.0, "EVRCH"),         # was 0.6
}

#: ``SOL_P_MODEL = 1`` — the reference runs the newer soil-phosphorus routine.
REF_CODES = {"soil_p": (1, "SOL_P_MODEL")}


# ---------------------------------------------------------------------------------------
# Header-addressed table editing
# ---------------------------------------------------------------------------------------

def _fmt(val: float | int) -> str:
    """Five decimals like the rest of the tree, widened when that would lose the value.

    ``CN_FROZ`` is 0.000862; at ``.5f`` it rounds to 0.00086, a 0.2 % haircut on a parameter
    ported precisely so it would stop being an approximation.
    """
    if isinstance(val, int):
        return str(val)
    for places in range(5, 12):
        text = f"{val:.{places}f}"
        if float(text) == val:
            return text
    return repr(val)


def _read(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _set_columns(path: Path, key: str | None, updates: dict[str, float | int],
                 header_line: int = 1, key_col: int = 0) -> dict[str, tuple[str, str]]:
    """Set named columns on the row whose ``key_col`` token is ``key``.

    Addressing by header name rather than token index is what makes this safe to point at
    six differently-shaped files: ``aquifer.aqu`` puts an ``id`` before ``name``,
    ``parameters.bsn`` has no key column at all, and the ``.lum`` tables carry a trailing
    free-text description. Returns {column: (before, after)} for the caller to report.

    SWAT+ reads these tables free-format, so the rewritten row only has to stay
    whitespace-separated and in column order -- alignment is cosmetic. (``print.prt`` is the
    exception and is handled by :mod:`swat_gym.printprt`.)
    """
    lines = _read(path)
    header = lines[header_line].split()
    for name in updates:
        if name not in header:
            raise SystemExit(f"{path.name}: no column {name!r}; have {header}")

    for i in range(header_line + 1, len(lines)):
        toks = lines[i].split()
        if not toks:
            continue
        if key is not None and toks[key_col] != key:
            continue

        changed: dict[str, tuple[str, str]] = {}
        for name, val in updates.items():
            col = header.index(name)
            if col >= len(toks):
                raise SystemExit(f"{path.name}: row {key!r} has {len(toks)} tokens, "
                                 f"need {col + 1} for {name!r}")
            before, after = toks[col], _fmt(val)
            if float(before) != float(after):
                changed[name] = (before, after)
            toks[col] = after

        # Keep any trailing description column glued to the numbers it annotates.
        lines[i] = "  ".join(toks)
        path.write_text("\n".join(lines) + "\n")
        return changed

    raise SystemExit(f"{path.name}: row {key!r} not found")


def _upsert_row(path: Path, row: str, values: dict[str, float], description: str) -> str:
    """Add ``row`` to a lookup table, or update it if a previous run already added it."""
    lines = _read(path)
    header = lines[1].split()
    ordered = [_fmt(values[c]) for c in header[1:] if c in values]
    new = "  ".join([row, *ordered, description])

    for i in range(2, len(lines)):
        toks = lines[i].split()
        if toks and toks[0] == row:
            verb = "updated" if lines[i].split() != new.split() else "unchanged"
            lines[i] = new
            path.write_text("\n".join(lines) + "\n")
            return verb

    lines.append(new)
    path.write_text("\n".join(lines) + "\n")
    return "added"


def _report(label: str, changed: dict[str, tuple[str, str]],
            names: dict[str, tuple[float | int, str]]) -> None:
    if not changed:
        print(f"{label}: already reconciled")
        return
    for col, (before, after) in changed.items():
        print(f"{label}: {col} {before} -> {after}   ({names[col][1]})")


def main() -> None:
    # --- CN2, OV_N, USLE_P: two new lookup rows plus three pointer changes -------------
    cn = {c: REF_CN2_C + off for c, off in _CN_OFFSETS.items()}
    verb = _upsert_row(TIO / "cntable.lum", SITE_ROW, cn,
                       "Kimberly_reference_CN2  ArcSWAT_000140001.mgt  ----")
    print(f"cntable.lum: row {SITE_ROW} {verb} "
          f"(cn_c {REF_CN2_C} from CN2; was legr_strow_g cn_c 81)")

    verb = _upsert_row(TIO / "ovn_table.lum", SITE_ROW,
                       {"ovn_mean": REF_OV_N, "ovn_min": REF_OV_N, "ovn_max": REF_OV_N},
                       "Kimberly_reference_OV_N")
    print(f"ovn_table.lum: row {SITE_ROW} {verb} (ovn {REF_OV_N} from OV_N; was 0.19)")

    lines = _read(TIO / "landuse.lum")
    header, toks = lines[1].split(), lines[2].split()
    for col, val in (("cn2", SITE_ROW), ("ov_mann", SITE_ROW),
                     ("cons_prac", REF_CONS_PRACTICE)):
        i = header.index(col)
        if toks[i] != val:
            print(f"landuse.lum: {col} {toks[i]} -> {val}")
            toks[i] = val
    lines[2] = "  ".join(toks)
    (TIO / "landuse.lum").write_text("\n".join(lines) + "\n")

    # --- snow, groundwater, basin parameters, codes -----------------------------------
    for path, key, spec, label in (
        (TIO / "snow.sno", "snow001", REF_SNOW, "snow.sno"),
        (TIO / "aquifer.aqu", AQUIFER_SHALLOW, REF_AQUIFER, "aquifer.aqu"),
        (TIO / "parameters.bsn", None, REF_BASIN, "parameters.bsn"),
        (TIO / "codes.bsn", None, REF_CODES, "codes.bsn"),
    ):
        key_col = 1 if path.name == "aquifer.aqu" else 0
        changed = _set_columns(path, key, {k: v for k, (v, _) in spec.items()},
                               key_col=key_col)
        _report(label, changed, spec)


if __name__ == "__main__":
    main()
