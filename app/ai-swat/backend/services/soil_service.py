"""gSSURGO soil integration: field location -> dominant soil -> soils.sol.

lat/lon -> USDA Soil Data Access (dominant mukey) -> SWAT-US-SSURGO .mdb
(dominant CMPPCT component) -> a SWAT+ soils.sol record. Verified to reproduce the
a10 demo soil (mukey 80295 = Portneuf) field-for-field, including SOL_CBN/1.72
(organic matter -> organic carbon).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


def _f(v, d: int = 5) -> str:
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "0.00000"


def dominant_mukey(lat: float, lon: float) -> str | None:
    """USDA SDA: the dominant SSURGO map-unit key at a point (US only)."""
    q = ("SELECT TOP 1 mukey FROM "
         f"SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})')")
    body = json.dumps({"format": "JSON", "query": q}).encode()
    req = urllib.request.Request(_SDA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    tbl = data.get("Table") or []
    return str(tbl[0][0]) if tbl and tbl[0] else None


def _dominant_component_sqlite(mukey: str) -> dict | None:
    """Portable backend — the .mdb converted to SQLite (see tools/convert_ssurgo.sh).

    Works on every platform, so gSSURGO soil is available inside Linux containers
    where the Access/pyodbc driver does not exist.
    """
    import sqlite3

    cn = sqlite3.connect(f"file:{config.SSURGO_SQLITE}?mode=ro", uri=True)
    cn.row_factory = sqlite3.Row
    try:
        row = cn.execute(
            "SELECT * FROM SSURGO_Soils WHERE MUID = ? ORDER BY CMPPCT DESC LIMIT 1",
            (str(mukey),),
        ).fetchone()
    finally:
        cn.close()
    return dict(row) if row else None


def _dominant_component_mdb(mukey: str) -> dict | None:
    """Original backend — MS Access .mdb via pyodbc (Windows only)."""
    import pyodbc
    cn = pyodbc.connect(
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=%s;" % config.SSURGO_MDB,
        autocommit=True,
    )
    cur = cn.cursor()
    cur.execute("SELECT * FROM SSURGO_Soils WHERE MUID=? ORDER BY CMPPCT DESC", str(mukey))
    cols = [c[0] for c in cur.description]
    row = cur.fetchone()
    cn.close()
    return dict(zip(cols, row)) if row else None


def _dominant_component(mukey: str) -> dict | None:
    """Prefer the portable SQLite database; fall back to the Access .mdb."""
    if config.SSURGO_SQLITE and Path(config.SSURGO_SQLITE).is_file():
        return _dominant_component_sqlite(mukey)
    return _dominant_component_mdb(mukey)


def soils_sol_record(mukey: str) -> dict | None:
    """Translate the dominant component of a mukey into a SWAT+ soils.sol record."""
    d = _dominant_component(mukey)
    if not d:
        return None
    name = str(mukey)
    nly = int(float(d["NLAYERS"]))
    hdr = (f"{name:<32}{nly:>6}{str(d['HYDGRP']):>18}{_f(d['SOL_ZMX']):>14}"
           f"{_f(d['ANION_EXCL']):>14}{_f(d['SOL_CRK']):>14}  "
           f"{str(d['TEXTURE']).strip().replace(' ', '_')}")
    lines = [hdr]
    for n in range(1, nly + 1):
        cbn = float(d.get(f"SOL_CBN{n}") or 0) / 1.72  # organic matter -> organic carbon
        vals = [
            _f(d.get(f"SOL_Z{n}")), _f(d.get(f"SOL_BD{n}")), _f(d.get(f"SOL_AWC{n}")),
            _f(d.get(f"SOL_K{n}")), _f(cbn), _f(d.get(f"CLAY{n}")), _f(d.get(f"SILT{n}")),
            _f(d.get(f"SAND{n}")), _f(d.get(f"ROCK{n}")), _f(d.get(f"SOL_ALB{n}")),
            _f(d.get(f"USLE_K{n}")), _f(d.get(f"SOL_EC{n}")), _f(d.get(f"SOL_CAL{n}")),
            _f(d.get(f"SOL_PH{n}")),
        ]
        lines.append(" " * 38 + "".join(v.rjust(14) for v in vals))
    return {
        "name": name, "snam": str(d.get("SNAM", "")).strip(), "cmppct": d.get("CMPPCT"),
        "nly": nly, "hyd_grp": str(d["HYDGRP"]), "record": "\n".join(lines),
    }


_SOL_HEADER = (
    "name                            nly           hyd_grp        dp_tot    anion_excl"
    "      perc_crk  texture              dp            bd           awc        soil_k"
    "        carbon          clay          silt          sand          rock           alb"
    "        usle_k            ec         caco3            ph  "
)


def apply_gssurgo_soil(txtinout: str | Path, lat: float, lon: float) -> dict:
    """Write the dominant gSSURGO soil into soils.sol and point the single HRU at it."""
    tio = Path(txtinout)
    try:
        mukey = dominant_mukey(lat, lon)
    except Exception as exc:
        logger.warning("SDA lookup failed for (%s,%s): %s", lat, lon, exc)
        return {"ok": False, "error": f"Soil lookup failed: {exc}"}
    if not mukey:
        return {"ok": False, "error": "No SSURGO map unit at this location (US only)."}
    try:
        rec = soils_sol_record(mukey)
    except Exception as exc:
        logger.warning("gSSURGO .mdb read failed for mukey %s: %s", mukey, exc)
        return {"ok": False, "error": f"Soil database read failed: {exc}"}
    if not rec:
        return {"ok": False, "error": f"mukey {mukey} not in gSSURGO database."}

    (tio / "soils.sol").write_text(
        "soils.sol: AI-SWAT+ gSSURGO dominant soil\n" + _SOL_HEADER + "\n" + rec["record"] + "\n",
        encoding="utf-8",
    )
    hru = tio / "hru-data.hru"
    if hru.exists():
        L = hru.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(L):
            t = ln.split()
            if len(t) >= 6 and t[0] == "1":  # the single HRU row
                t[4] = rec["name"]
                L[i] = "  ".join(t)
                break
        hru.write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"ok": True, "mukey": mukey, "soil": rec["snam"], "cmppct": rec["cmppct"],
            "nly": rec["nly"], "hyd_grp": rec["hyd_grp"]}
