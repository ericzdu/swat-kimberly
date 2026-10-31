"""
SWAT+ Editor backend — browse and edit the raw TxtInOut input files, organized
into SWAT+ Editor-like categories. pySWATPlus 1.3 exposes only run/print controls,
so these read/write the whitespace-delimited SWAT+ text files directly.

Safety: restricted to the farm's TxtInOut folder, bare filenames only (no path
traversal), a .bak is written before every save.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from db import db_one
from services import data_service

logger = logging.getLogger(__name__)

# Files that are model OUTPUTS or junk — never shown in the input editor.
_EXCLUDE_EXT = {".txt", ".out", ".fin", ".exe", ".bak", ".zip", ".csv", ".json"}
_EXCLUDE_PREFIX = ("fort.", "__", ".")
_EXCLUDE_NAMES = {"success.fin", "area_calc.out", "checker.out", "diagnostics.out",
                  "files_out.out", "erosion.out", "co2.out"}

# SWAT+ Editor-style categories, keyed by file extension.
_EXT_CATEGORY = {
    ".sim": "Simulation", ".prt": "Simulation", ".cio": "Simulation", ".bsn": "Simulation", ".cnt": "Simulation",
    ".cli": "Climate", ".pcp": "Climate", ".tmp": "Climate", ".slr": "Climate", ".hmd": "Climate", ".wnd": "Climate", ".wgn": "Climate",
    ".con": "Connections",
    ".cha": "Channels",
    ".aqu": "Aquifers", ".gw": "Aquifers",
    ".res": "Reservoirs",
    ".hru": "HRUs",
    ".rtu": "Routing units", ".def": "Routing units", ".ele": "Routing units",
    ".lum": "Land use management", ".sch": "Land use management", ".ops": "Land use management",
    ".dtl": "Decision tables",
    ".sol": "Soils",
    ".hyd": "Hydrology", ".fld": "Hydrology",
    ".plt": "Databases", ".frt": "Databases", ".til": "Databases", ".pes": "Databases",
    ".urb": "Databases", ".sep": "Databases", ".sno": "Databases",
    ".ini": "Initialization",
    ".str": "Structural",
    ".cal": "Calibration", ".sft": "Calibration",
    ".rec": "Recall",
}

# Friendly descriptions for the most common files.
_FILE_DESC = {
    "time.sim": "Simulation dates (start/end year, step)",
    "print.prt": "Output print objects and frequency",
    "object.cnt": "Object counts",
    "file.cio": "Master file list",
    "codes.bsn": "Basin process codes",
    "parameters.bsn": "Basin-level parameters",
    "hydrology.hyd": "HRU hydrology parameters (CN, ESCO, EPCO, perco…)",
    "topography.hyd": "HRU topography (slope, slope length)",
    "field.fld": "Field parameters",
    "soils.sol": "Soil layers and physical properties",
    "nutrients.sol": "Soil nutrient parameters",
    "hru-data.hru": "HRU definitions (topo/hydro/soil/lu links)",
    "hru.con": "HRU spatial connections/routing",
    "landuse.lum": "Land-use management links",
    "management.sch": "Management schedules (operations)",
    "plant.ini": "Initial plant communities per HRU",
    "plants.plt": "Plant growth database",
    "fertilizer.frt": "Fertilizer database",
    "tillage.til": "Tillage database",
    "pesticide.pes": "Pesticide database",
    "cal_parms.cal": "Calibratable parameters list",
    "calibration.cal": "Calibration parameter changes",
    "aquifer.aqu": "Aquifer parameters",
    "initial.aqu": "Aquifer initial conditions",
    "channel-lte.cha": "Channel (lite) parameters",
    "nutrients.cha": "Channel nutrient parameters",
    "weather-sta.cli": "Weather stations",
    "weather-wgn.cli": "Weather generator statistics",
}


def _txtinout(farm_id: str) -> Optional[Path]:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return None
    return data_service.resolve_farm_txtinout(farm_id, farm)


def _is_input_file(name: str) -> bool:
    lower = name.lower()
    if name in _EXCLUDE_NAMES:
        return False
    if any(lower.startswith(p) for p in _EXCLUDE_PREFIX):
        return False
    ext = Path(name).suffix.lower()
    if ext in _EXCLUDE_EXT:
        return False
    return ext in _EXT_CATEGORY


def _safe_path(farm_id: str, name: str) -> Path:
    """Resolve a bare filename inside the farm's TxtInOut, rejecting traversal."""
    tio = _txtinout(farm_id)
    if not tio:
        raise ValueError("Farm not found")
    if "/" in name or "\\" in name or ".." in name or Path(name).name != name:
        raise ValueError("Invalid file name")
    path = (tio / name).resolve()
    if tio.resolve() not in path.parents and path.parent != tio.resolve():
        raise ValueError("File outside the field folder")
    return path


def list_files(farm_id: str) -> dict[str, Any]:
    tio = _txtinout(farm_id)
    if not tio or not tio.is_dir():
        return {"ok": False, "error": "This field has no SWAT+ model files yet.", "categories": []}
    grouped: dict[str, list[dict]] = {}
    for f in sorted(tio.iterdir()):
        if not f.is_file() or not _is_input_file(f.name):
            continue
        cat = _EXT_CATEGORY.get(f.suffix.lower(), "Other")
        grouped.setdefault(cat, []).append({
            "name": f.name,
            "ext": f.suffix.lower(),
            "size": f.stat().st_size,
            "desc": _FILE_DESC.get(f.name, ""),
        })
    # Preferred display order (mirrors the SWAT+ Editor left nav).
    order = ["Simulation", "Climate", "Connections", "Channels", "Aquifers", "Reservoirs",
             "HRUs", "Routing units", "Land use management", "Decision tables", "Hydrology",
             "Soils", "Databases", "Initialization", "Structural", "Recall", "Calibration", "Other"]
    categories = [{"name": c, "files": grouped[c]} for c in order if c in grouped]
    return {"ok": True, "farm_id": farm_id, "txtinout": str(tio), "categories": categories}


def read_file(farm_id: str, name: str) -> dict[str, Any]:
    path = _safe_path(farm_id, name)
    if not path.exists():
        return {"ok": False, "error": "File not found"}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return {"ok": True, "name": name, "title": "", "tabular": False, "raw": "", "header": [], "rows": []}
    title = lines[0]
    if len(lines) < 2:
        return {"ok": True, "name": name, "title": title, "tabular": False,
                "raw": "\n".join(lines), "header": [], "rows": []}
    header = lines[1].split()
    data_lines = [ln for ln in lines[2:] if ln.strip()]
    rows: list[list[str]] = []
    tabular = bool(header)
    # A trailing "description"/"text" column is free-text (rest-of-line): it may be
    # blank or contain spaces, so it isn't a fixed whitespace token like the SWAT+
    # Editor treats it. Parse the fixed columns first and fold the remainder into it.
    free_tail = bool(header) and header[-1] in ("description", "text")
    n_fixed = len(header) - 1 if free_tail else len(header)
    for ln in data_lines:
        cols = ln.split()
        if free_tail:
            if len(cols) < n_fixed:
                tabular = False
                break
            rows.append(cols[:n_fixed] + [" ".join(cols[n_fixed:])])
        else:
            if len(cols) != len(header):
                tabular = False
                break
            rows.append(cols)
    if not tabular:
        return {"ok": True, "name": name, "title": title, "tabular": False,
                "raw": "\n".join(lines), "header": header, "rows": []}
    return {"ok": True, "name": name, "title": title, "tabular": True,
            "header": header, "rows": rows, "n_rows": len(rows),
            "desc": _FILE_DESC.get(name, ""),
            "columns": _column_meta(name, header)}


# Factual per-column field specs (label / unit / description / input type / coded options)
# for the SWAT+ input files, from the SWAT+ I/O documentation. Drives the structured
# edit form; columns not listed fall back to header-derived labels.
_CODE_YN = [{"value": "0", "label": "0 — off"}, {"value": "1", "label": "1 — on"}]
_FIELD_META: dict[str, dict[str, dict]] = {
    "codes.bsn": {
        "pet": {"label": "PET method", "desc": "Potential evapotranspiration method.",
                "options": [{"value": "0", "label": "0 — read from file"}, {"value": "1", "label": "1 — Penman-Monteith"},
                            {"value": "2", "label": "2 — Priestley-Taylor"}, {"value": "3", "label": "3 — Hargreaves"}]},
        "event": {"label": "Rainfall/runoff", "desc": "Daily (0) or sub-daily (1).", "options": _CODE_YN},
        "crack": {"label": "Crack flow", "desc": "Crack-flow routing in soils.", "options": _CODE_YN},
        "rte_cha": {"label": "Channel routing", "desc": "Channel water-routing method.",
                    "options": [{"value": "0", "label": "0 — variable storage"}, {"value": "1", "label": "1 — Muskingum"}]},
        "nostress": {"label": "Plant stress", "desc": "Nutrient/water stress on plant growth.",
                     "options": [{"value": "0", "label": "0 — all stresses"}, {"value": "1", "label": "1 — no stress"},
                                 {"value": "2", "label": "2 — no nutrient stress"}]},
        "cn": {"label": "Daily curve number", "desc": "How CN is calculated.",
               "options": [{"value": "0", "label": "0 — soil moisture"}, {"value": "1", "label": "1 — plant ET"},
                           {"value": "2", "label": "2 — soil moisture (no depth)"}]},
        "gampt": {"label": "Infiltration", "desc": "Curve number (0) or Green-Ampt (1).",
                  "options": [{"value": "0", "label": "0 — curve number"}, {"value": "1", "label": "1 — Green-Ampt"}]},
        "tiledrain": {"label": "Tile drainage", "options": [{"value": "0", "label": "0 — off"}, {"value": "1", "label": "1 — Hooghoudt"}]},
        "carbon": {"label": "Carbon model", "options": [{"value": "0", "label": "0 — static"}, {"value": "1", "label": "1 — dynamic"}]},
    },
    "hydrology.hyd": {
        "lat_ttime": {"label": "Lateral flow travel time", "unit": "days"},
        "can_max": {"label": "Max canopy storage", "unit": "mm"},
        "esco": {"label": "Soil evaporation comp. (ESCO)", "unit": "0–1", "desc": "Soil-evaporation compensation factor."},
        "epco": {"label": "Plant uptake comp. (EPCO)", "unit": "0–1", "desc": "Plant-uptake compensation factor."},
        "perco": {"label": "Percolation coefficient", "unit": "0–1"},
        "cn3_swf": {"label": "CN3 soil-water factor", "unit": "0–1"},
        "latq_co": {"label": "Lateral-flow coefficient", "unit": "0–1"},
        "pet_co": {"label": "PET adjustment", "unit": "coef"},
        "bio_mix": {"label": "Biological mixing efficiency", "unit": "0–1"},
    },
    "topography.hyd": {
        "slp": {"label": "Slope", "unit": "m/m"}, "slp_len": {"label": "Slope length", "unit": "m"},
        "lat_len": {"label": "Lateral-flow length", "unit": "m"}, "dist_cha": {"label": "Distance to channel", "unit": "m"},
        "depos": {"label": "Deposition fraction", "unit": "0–1"},
    },
    "snow.sno": {
        "fall_tmp": {"label": "Snowfall temperature", "unit": "°C", "desc": "Precip below this falls as snow."},
        "melt_tmp": {"label": "Snowmelt base temperature", "unit": "°C"},
        "melt_max": {"label": "Max melt factor (Jun 21)", "unit": "mm/°C/day"},
        "melt_min": {"label": "Min melt factor (Dec 21)", "unit": "mm/°C/day"},
        "tmp_lag": {"label": "Snowpack temp lag", "unit": "0–1"},
        "snow_h2o": {"label": "Snow water equiv. for 100% cover", "unit": "mm"},
        "cov50": {"label": "Snow cover at 50%", "unit": "frac"},
        "snow_init": {"label": "Initial snow water", "unit": "mm"},
    },
    "irr.ops": {
        "amount": {"label": "Application amount", "unit": "mm"},
        "eff": {"label": "Irrigation efficiency", "unit": "0–1"},
        "surq": {"label": "Surface-runoff ratio", "unit": "0–1"},
    },
    "parameters.bsn": {
        "sw_init": {"label": "Initial soil water", "unit": "frac of FC"},
        "surq_lag": {"label": "Surface-runoff lag", "unit": "days"},
        "n_uptake": {"label": "N uptake distribution", "unit": "coef"},
        "p_uptake": {"label": "P uptake distribution", "unit": "coef"},
        "n_perc": {"label": "Nitrate percolation coef.", "unit": "0–1", "desc": "Fraction of NO₃ moving with percolating water."},
        "p_perc": {"label": "Phosphorus percolation coef.", "unit": "0–1"},
        "nperco_lchtile": {"label": "NO₃ leaching/tile coef.", "unit": "0–1"},
        "denit_exp": {"label": "Denitrification exponent", "unit": "coef", "desc": "Controls denitrification rate."},
        "denit_frac": {"label": "Denitrification threshold", "unit": "frac", "desc": "Soil-water frac triggering denitrification."},
        "orgn_min": {"label": "Organic-N mineralization", "unit": "coef"},
        "cn_froz": {"label": "Frozen-soil CN adjustment", "unit": "coef"},
        "co2": {"label": "Atmospheric CO₂", "unit": "ppm"},
        "plaps": {"label": "Precip lapse rate", "unit": "mm/km"},
        "tlaps": {"label": "Temperature lapse rate", "unit": "°C/km"},
        "n_fix_max": {"label": "Max N fixation", "unit": "kg/ha/day"},
        "petco_pmpt": {"label": "PET coefficient (P-T)", "unit": "coef"},
    },
    "nutrients.sol": {
        "nitrate": {"label": "Initial soil nitrate", "unit": "mg/kg", "desc": "Starting NO₃-N concentration."},
        "lab_p": {"label": "Labile phosphorus", "unit": "mg/kg"},
        "exp_co": {"label": "N/P depth-decay coef.", "unit": "coef"},
        "fr_hum_act": {"label": "Active humus fraction", "unit": "0–1"},
        "hum_c_n": {"label": "Humus C:N ratio", "unit": "ratio"},
        "hum_c_p": {"label": "Humus C:P ratio", "unit": "ratio"},
        "inorgp": {"label": "Inorganic P", "unit": "mg/kg"},
    },
    "fertilizer.frt": {
        "min_n": {"label": "Mineral N fraction", "unit": "0–1", "desc": "Fraction of fertilizer that is mineral N."},
        "min_p": {"label": "Mineral P fraction", "unit": "0–1"},
        "org_n": {"label": "Organic N fraction", "unit": "0–1"},
        "org_p": {"label": "Organic P fraction", "unit": "0–1"},
        "nh3_n": {"label": "Ammonium fraction of mineral N", "unit": "0–1"},
        "pathogens": {"label": "Pathogens", "type": "text"},
    },
    "aquifer.aqu": {
        "no3_n": {"label": "Initial aquifer nitrate", "unit": "mg/L", "desc": "Groundwater NO₃-N concentration."},
        "sol_p": {"label": "Soluble phosphorus", "unit": "mg/L"},
        "alpha_bf": {"label": "Baseflow recession (α)", "unit": "1/day", "desc": "Baseflow alpha factor."},
        "bf_max": {"label": "Max baseflow", "unit": "mm"},
        "revap": {"label": "Revap coefficient", "unit": "0–1", "desc": "Water moving from aquifer to root zone."},
        "revap_min": {"label": "Revap threshold depth", "unit": "mm"},
        "rchg_dp": {"label": "Deep-aquifer recharge frac.", "unit": "0–1"},
        "spec_yld": {"label": "Specific yield", "unit": "0–1"},
        "hl_no3n": {"label": "NO₃ half-life", "unit": "days"},
        "dep_bot": {"label": "Depth to aquifer bottom", "unit": "m"},
        "dep_wt": {"label": "Initial water-table depth", "unit": "m"},
        "flo_min": {"label": "Water-table threshold for flow", "unit": "m"},
    },
    "plants.plt": {
        "plnt_typ": {"label": "Plant type", "options": [
            {"value": "warm_annual", "label": "Warm-season annual"},
            {"value": "cold_annual", "label": "Cold-season annual"},
            {"value": "perennial", "label": "Perennial"},
            {"value": "warm_annual_tuber", "label": "Warm-season annual tuber"},
            {"value": "cold_annual_tuber", "label": "Cold-season annual tuber"},
            {"value": "tree", "label": "Tree"}]},
        "days_mat": {"label": "Days to maturity", "unit": "days"},
        "bm_e": {"label": "Radiation-use efficiency", "unit": "(kg/ha)/(MJ/m²)"},
        "harv_idx": {"label": "Harvest index", "unit": "0–1", "desc": "Fraction of biomass that is yield."},
        "lai_pot": {"label": "Potential max LAI", "unit": "m²/m²"},
        "can_ht_max": {"label": "Max canopy height", "unit": "m"},
        "rt_dp_max": {"label": "Max root depth", "unit": "m"},
        "tmp_opt": {"label": "Optimal growth temp.", "unit": "°C"},
        "tmp_base": {"label": "Base growth temp.", "unit": "°C", "desc": "Growth stops below this."},
        "frac_n_yld": {"label": "N fraction in yield", "unit": "0–1"},
        "frac_p_yld": {"label": "P fraction in yield", "unit": "0–1"},
        "usle_c_min": {"label": "Min USLE-C factor", "unit": "0–1"},
    },
    "time.sim": {
        "day_start": {"label": "Start day", "unit": "Julian", "desc": "0 = Jan 1."},
        "yrc_start": {"label": "Start year", "unit": "year"},
        "day_end": {"label": "End day", "unit": "Julian", "desc": "0 = Dec 31."},
        "yrc_end": {"label": "End year", "unit": "year"},
        "step": {"label": "Time step", "desc": "Steps per day (0 = daily).", "options": [
            {"value": "0", "label": "0 — daily"}, {"value": "1", "label": "1 — hourly"}, {"value": "24", "label": "24 — hourly"}]},
    },
    "print.prt": {
        "nyskip": {"label": "Warm-up years skipped", "unit": "years", "desc": "Years excluded from output."},
        "day_start": {"label": "Print start day", "unit": "Julian"},
        "yrc_start": {"label": "Print start year", "unit": "year"},
        "day_end": {"label": "Print end day", "unit": "Julian"},
        "yrc_end": {"label": "Print end year", "unit": "year"},
        "interval": {"label": "Print interval", "unit": "days"},
    },
}

# Merge in the bulk field metadata mined from the official SWAT+ Editor (labels/units/
# descriptions/coded dropdowns) for the remaining input files, validated column-by-column
# against real file headers. Hand-authored entries above win on any key collision.
_META_JSON = Path(__file__).with_name("field_metadata.json")
try:
    _bulk = json.loads(_META_JSON.read_text(encoding="utf-8"))
    for _fname, _cols in _bulk.items():
        _dst = _FIELD_META.setdefault(_fname, {})
        for _col, _m in _cols.items():
            _dst.setdefault(_col, _m)
except (OSError, ValueError) as _exc:
    logger.warning("Could not load bulk field metadata: %s", _exc)

_NUMERIC_HINT = ("amt", "amount", "eff", "mm", "temp", "tmp", "co", "fr", "frac", "num", "_z", "bd", "awc",
                 "clay", "silt", "sand", "ph", "slp", "len", "dep", "lat", "lon", "elev", "area")


def _column_meta(name: str, header: list[str]) -> list[dict]:
    """Per-column display metadata for the structured edit form."""
    reg = _FIELD_META.get(name, {})
    out = []
    for col in header:
        m = reg.get(col, {})
        label = m.get("label") or col.replace("_", " ").strip().title()
        typ = "select" if m.get("options") else ("number" if any(h in col.lower() for h in _NUMERIC_HINT) else "text")
        out.append({"col": col, "label": label, "unit": m.get("unit", ""),
                    "desc": m.get("desc", ""), "type": typ, "options": m.get("options")})
    return out


def _fmt_table(title: str, header: list[str], rows: list[list[str]]) -> str:
    widths = []
    for i, h in enumerate(header):
        w = len(str(h))
        for r in rows:
            if i < len(r):
                w = max(w, len(str(r[i])))
        widths.append(max(w, 8))

    def fmt(cells: list) -> str:
        return "  ".join(str(cells[i] if i < len(cells) else "").rjust(widths[i]) for i in range(len(header)))

    out = [title, fmt(header)]
    out += [fmt(r) for r in rows]
    return "\n".join(out) + "\n"


def write_file(farm_id: str, name: str, title: str = "", header: Optional[list] = None,
               rows: Optional[list] = None, raw: Optional[str] = None) -> dict[str, Any]:
    path = _safe_path(farm_id, name)
    if not path.exists():
        return {"ok": False, "error": "File not found"}
    # Backup before writing.
    try:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    except OSError as exc:
        logger.debug("Backup failed for %s: %s", name, exc)

    if raw is not None:
        path.write_text(raw if raw.endswith("\n") else raw + "\n", encoding="utf-8")
        return {"ok": True, "name": name, "mode": "raw"}

    if header is None or rows is None:
        return {"ok": False, "error": "Provide either raw text or header+rows"}
    # Validate row widths.
    for r in rows:
        if len(r) != len(header):
            return {"ok": False, "error": f"Every row must have {len(header)} columns"}
    content = _fmt_table(title or f"{name}: edited by AI-SWAT+", header, rows)
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "name": name, "mode": "table", "n_rows": len(rows)}


# ---------------------------------------------------------------------------
# soils.sol — a nested (soil → layers) file. The SWAT+ Editor edits it with a
# soil-property form plus a per-layer sub-grid, so we parse/serialize it as a
# structured object instead of the flat tabular path.
# ---------------------------------------------------------------------------
def _soil_split(header: list[str]) -> tuple[list[str], list[str]]:
    """Split the combined soils.sol header into soil-level cols and layer cols."""
    tex_i = header.index("texture") if "texture" in header else 6
    return header[: tex_i + 1], header[tex_i + 1:]


def read_soil(farm_id: str) -> dict[str, Any]:
    """Parse soils.sol into {soils:[{<soil cols>, layers:[{<layer cols>}]}], meta}."""
    path = _safe_path(farm_id, "soils.sol")
    if not path.exists():
        return {"ok": False, "error": "File not found"}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 2:
        return {"ok": False, "error": "soils.sol is empty"}
    title = lines[0]
    header = lines[1].split()
    soil_cols, layer_cols = _soil_split(header)
    nly_i = soil_cols.index("nly") if "nly" in soil_cols else 1

    soils: list[dict] = []
    i = 2
    n = len(lines)
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        rec = lines[i].split()
        soil = {c: (rec[j] if j < len(rec) else "") for j, c in enumerate(soil_cols)}
        try:
            nly = int(float(rec[nly_i])) if nly_i < len(rec) else 0
        except ValueError:
            nly = 0
        layers = []
        for k in range(nly):
            li = i + 1 + k
            if li >= n:
                break
            lt = lines[li].split()
            layers.append({c: (lt[m] if m < len(lt) else "") for m, c in enumerate(layer_cols)})
        soil["layers"] = layers
        soils.append(soil)
        i += 1 + len(layers)

    return {
        "ok": True, "name": "soils.sol", "title": title,
        "soil_cols": _column_meta("soils.sol", soil_cols),
        "layer_cols": _column_meta("soils.sol", layer_cols),
        "soils": soils,
    }


def write_soil(farm_id: str, soils: list[dict], title: str = "") -> dict[str, Any]:
    """Serialize the structured soils back to soils.sol (column-aligned, free-format)."""
    path = _safe_path(farm_id, "soils.sol")
    if not path.exists():
        return {"ok": False, "error": "File not found"}
    # Recover the canonical header/column order from the existing file.
    existing = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header = existing[1].split() if len(existing) > 1 else []
    if not header:
        return {"ok": False, "error": "Cannot determine soils.sol header"}
    soil_cols, layer_cols = _soil_split(header)
    nly_i = soil_cols.index("nly") if "nly" in soil_cols else 1

    # Build cell matrices so column widths line up across soil and layer rows.
    soil_rows: list[list[str]] = []
    layer_map: list[list[list[str]]] = []  # per-soil list of layer cell-lists
    for s in soils:
        layers = s.get("layers") or []
        row = []
        for j, c in enumerate(soil_cols):
            if j == nly_i:
                row.append(str(len(layers)))            # nly always = actual layer count
            else:
                row.append(str(s.get(c, "")).strip())
        soil_rows.append(row)
        layer_map.append([[str(ly.get(c, "")).strip() for c in layer_cols] for ly in layers])

    # Column widths: soil columns from soil rows; layer columns from all layer rows.
    swid = [max(len(soil_cols[j]), 8) for j in range(len(soil_cols))]
    for r in soil_rows:
        for j in range(len(soil_cols)):
            swid[j] = max(swid[j], len(r[j]) if j < len(r) else 0)
    lwid = [max(len(layer_cols[j]), 8) for j in range(len(layer_cols))]
    for lm in layer_map:
        for lr in lm:
            for j in range(len(layer_cols)):
                lwid[j] = max(lwid[j], len(lr[j]) if j < len(lr) else 0)

    def join_soil(cells: list[str]) -> str:
        return "  ".join(cells[j].rjust(swid[j]) for j in range(len(soil_cols)))

    def join_layer(cells: list[str]) -> str:
        # Indent past the soil columns so layer values sit under the layer header.
        pad = " " * (sum(swid) + 2 * len(soil_cols))
        return pad + "  ".join(cells[j].rjust(lwid[j]) for j in range(len(layer_cols)))

    title = title or (existing[0] if existing else "soils.sol: edited by AI-SWAT+")
    out = [title, "  ".join(
        [soil_cols[j].rjust(swid[j]) for j in range(len(soil_cols))]
        + [layer_cols[j].rjust(lwid[j]) for j in range(len(layer_cols))]
    )]
    for si, row in enumerate(soil_rows):
        out.append(join_soil(row))
        for lr in layer_map[si]:
            out.append(join_layer(lr))

    try:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    except OSError as exc:
        logger.debug("Backup failed for soils.sol: %s", exc)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"ok": True, "name": "soils.sol", "n_soils": len(soils)}
