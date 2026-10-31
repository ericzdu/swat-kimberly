"""Single source of truth for a field's model INPUTS and OUTPUTS.

Backs the agent's data-reference / table / custom-chart tools so the numbers it
states in text and the numbers it plots in the canvas always come from the same
place. Resolves the latest completed run and reuses run_timeline_service (which
already parses the daily HRU outputs + totals + stress + crop timeline).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import config
from db import db_one
from services import run_timeline_service as rt

logger = logging.getLogger(__name__)

# Whole-run scalar outputs the agent can reference by key.
_TOTALS = [
    ("precip_mm", "Rainfall", "mm"), ("irr_mm", "Irrigation applied", "mm"),
    ("et_mm", "Crop water use (ET)", "mm"), ("pet_mm", "Potential ET", "mm"),
    ("perc_mm", "Deep percolation", "mm"), ("surq_mm", "Surface runoff", "mm"),
    ("latq_mm", "Lateral flow", "mm"),
    ("fertn_kgha", "Nitrogen applied", "kg/ha"), ("nuptake_kgha", "Nitrogen taken up by crop", "kg/ha"),
    ("leached_kgha", "Nitrogen leached to groundwater", "kg/ha"), ("denit_kgha", "Nitrogen denitrified", "kg/ha"),
    ("fixn_kgha", "Nitrogen fixed", "kg/ha"),
    ("yield_kgha", "Yield", "kg/ha"), ("peak_bioms", "Peak biomass", "kg/ha"), ("nue_pct", "N use efficiency", "%"),
    ("sw_start", "Soil water (start)", "mm"), ("sw_end", "Soil water (end)", "mm"), ("sw_delta", "Change in stored soil water", "mm"),
]
_STRESS = [
    ("water_days", "Days the crop was water-stressed", "days"),
    ("n_days", "Days the crop was nitrogen-short", "days"),
    ("temp_days", "Days of heat/cold stress", "days"),
    ("aeration_days", "Days waterlogged", "days"),
]
# Daily series fields the agent can chart, with friendly label + unit + flux/state.
SERIES_FIELDS: dict[str, tuple[str, str]] = {
    "precip": ("Rainfall", "mm"), "irr": ("Irrigation", "mm"), "et": ("Crop water use (ET)", "mm"),
    "pet": ("Potential ET", "mm"), "sw_ave": ("Soil moisture", "mm"), "perc": ("Deep percolation", "mm"),
    "surq_gen": ("Surface runoff", "mm"), "wateryld": ("Water yield", "mm"),
    "bioms": ("Biomass", "kg/ha"), "lai": ("Canopy (LAI)", ""), "yield": ("Yield", "kg/ha"),
    "strsw": ("Water stress", ""), "strsn": ("Nitrogen stress", ""), "strstmp": ("Temperature stress", ""),
    "percn": ("Nitrate leached", "kg/ha"), "fertn": ("Nitrogen applied", "kg/ha"),
    "nuptake": ("Nitrogen uptake", "kg/ha"), "denit": ("Denitrification", "kg/ha"),
    "gwsoiln": ("N to groundwater", "kg/ha"), "tmpav": ("Avg temperature", "°C"),
    "tmx": ("Max temperature", "°C"), "tmn": ("Min temperature", "°C"), "solarad": ("Solar radiation", "MJ/m²"),
}
_FLUX = {"precip", "irr", "et", "pet", "perc", "surq_gen", "wateryld", "percn", "fertn", "nuptake", "denit", "gwsoiln",
         "yield"}  # yield is a harvest-day spike -> SUM within a bucket, not average


def soil_profile(farm_id: str) -> dict:
    """Parse the field's ACTUAL soils.sol into layer-by-layer values (the real file,
    not general soil knowledge). Returns {name, display_name, hyd_grp, texture, n_layers,
    total_depth_mm, layers:[{depth_cm, bd, awc, ksat_mm_hr, organic_matter_pct, clay/silt/
    sand_pct, ph, caco3_pct, ...}]}."""
    p = Path(config.farm_txtinout_dir(farm_id)) / "soils.sol"
    if not p.is_file():
        return {"layers": []}
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"layers": []}
    if len(lines) < 4:
        return {"layers": []}
    hdr = lines[1].split()
    tex_i = hdr.index("texture") if "texture" in hdr else 6
    lcols = hdr[tex_i + 1:]  # dp bd awc soil_k carbon clay silt sand rock alb usle_k ec caco3 ph
    rec = lines[2].split()
    try:
        name, nly, hyd = rec[0], int(float(rec[1])), rec[2]
        dp_tot = float(rec[3])
    except (ValueError, IndexError):
        return {"layers": []}
    texture = rec[6] if len(rec) > 6 else ""

    layers: list[dict] = []
    top = 0.0
    for ln in lines[3:3 + nly]:
        v = ln.split()
        if len(v) < len(lcols):
            continue
        try:
            d = {lcols[i]: float(v[i]) for i in range(len(lcols))}
        except ValueError:
            continue
        bottom = d.get("dp", top)
        carbon = d.get("carbon", 0.0)
        layers.append({
            "depth_cm": f"{top / 10:.0f}–{bottom / 10:.0f}",
            "top_mm": round(top), "bottom_mm": round(bottom),
            "bd": round(d.get("bd", 0), 2), "awc": round(d.get("awc", 0), 3),
            "ksat_mm_hr": round(d.get("soil_k", 0), 1),
            "organic_carbon_pct": round(carbon, 2), "organic_matter_pct": round(carbon * 1.72, 2),
            "clay_pct": round(d.get("clay", 0), 1), "silt_pct": round(d.get("silt", 0), 1),
            "sand_pct": round(d.get("sand", 0), 1), "rock_pct": round(d.get("rock", 0), 1),
            "ph": round(d.get("ph", 0), 1), "caco3_pct": round(d.get("caco3", 0), 1),
        })
        top = bottom

    farm = db_one("SELECT soil_type FROM farms WHERE id = ?", (farm_id,)) or {}
    return {"name": name, "display_name": farm.get("soil_type") or name, "hyd_grp": hyd,
            "texture": texture, "n_layers": nly, "total_depth_mm": dp_tot, "layers": layers}


def _parse_irr_ops(tio: Path) -> dict:
    """Read the auto-irrigation config (sprinkler_med amount + efficiency) from irr.ops."""
    p = tio / "irr.ops"
    if not p.is_file():
        return {}
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        t = ln.split()
        if t and t[0] == "sprinkler_med" and len(t) >= 3:
            try:
                return {"amount_mm": round(float(t[1]), 2), "efficiency": round(float(t[2]), 2)}
            except ValueError:
                return {}
    return {}


def _parse_irr_trigger(tio: Path) -> float | None:
    """Read the soil-water fraction-of-field-capacity trigger from lum.dtl."""
    p = tio / "lum.dtl"
    if not p.is_file():
        return None
    import re
    m = re.search(r"soil_water\s+hru\s+0\s+fc\s+-\s+([\d.]+)", p.read_text(encoding="utf-8", errors="replace"))
    return round(float(m.group(1)), 2) if m else None


def _parse_weather(tio: Path) -> dict:
    """Read the weather source + station coords/elevation from the .pcp header."""
    for name in ("tfccpcp.pcp", "pcp1.pcp"):
        p = tio / name
        if not p.is_file():
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) < 3:
            continue
        src = "gridMET" if "gridmet" in lines[0].lower() else "station/template"
        meta = lines[2].split()
        try:
            return {"source": src, "years": int(float(meta[0])),
                    "lat": round(float(meta[2]), 3), "lon": round(float(meta[3]), 3),
                    "elev_m": round(float(meta[4]), 1)}
        except (ValueError, IndexError):
            return {"source": src}
    return {}


def field_inputs(farm_id: str) -> dict:
    """Labeled INPUT values the agent can reference: location, soil, crops + dates, manure,
    irrigation config, weather. Reads the actual project files (never general knowledge)."""
    tio = Path(config.farm_txtinout_dir(farm_id))
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,)) or {}
    prof = soil_profile(farm_id)
    rid = latest_run_id(farm_id)
    tl = rt.build_timeline(rid) if rid else {}
    crops = tl.get("crops") or []
    ferts = [e for e in (tl.get("events") or []) if e.get("type") == "fertilizer"]
    irr = _parse_irr_ops(tio)
    trig = _parse_irr_trigger(tio)
    wx = _parse_weather(tio)

    v: dict[str, dict] = {}

    def put(key, label, value):
        if value:
            v[key] = {"label": label, "value": value, "group": "input"}

    if farm.get("location"):
        put("location", "Location", farm["location"])
    if prof.get("layers"):
        top = prof["layers"][0]
        put("soil", "Soil (call show_soil_profile for the full table)",
            f"{prof['display_name']} — {prof['n_layers']} layers to {round(prof['total_depth_mm']/10)} cm, "
            f"hydrologic group {prof['hyd_grp']}; top layer {top['organic_matter_pct']}% organic matter, "
            f"available water {top['awc']} mm/mm, Ksat {top['ksat_mm_hr']} mm/hr")
    if crops:
        put("crops", "Crops & rotation",
            "; ".join(f"{c['label']} (plant {c['plant']}, harvest {c['harvest']})" for c in crops[:6]))
    if ferts:
        put("manure", "Manure / fertilizer",
            f"{len(ferts)} application(s); e.g. {ferts[0]['amount']} {ferts[0]['unit']} on {ferts[0]['date']}")
    if irr:
        trg = f" when soil water < {trig}×field capacity" if trig else ""
        put("irrigation", "Auto-irrigation",
            f"{irr.get('amount_mm')} mm at {irr.get('efficiency')} efficiency{trg}")
    if wx:
        put("weather", "Weather",
            f"{wx.get('source')} daily; station {wx.get('lat')}, {wx.get('lon')} at {wx.get('elev_m')} m elevation")
    return v


def latest_run_id(farm_id: str) -> str | None:
    row = db_one(
        """SELECT id FROM simulations
           WHERE farm_id = ? AND status = 'completed' AND results IS NOT NULL
           ORDER BY completed_at DESC LIMIT 1""",
        (farm_id,),
    )
    return row["id"] if row else None


def snapshot(farm_id: str) -> dict:
    """Labeled inputs + outputs for the latest run — the reference the agent quotes from."""
    rid = latest_run_id(farm_id)
    tl = rt.build_timeline(rid) if rid else {}
    totals = tl.get("totals") or {}
    stress = tl.get("stress") or {}
    crops = tl.get("crops") or []
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,)) or {}

    values: dict[str, dict] = {}

    def put(key, label, value, unit, group):
        if value is not None:
            values[key] = {"label": label, "value": value, "unit": unit, "group": group}

    # inputs (soil / crops / manure / irrigation / weather / location) from the real files
    for k, iv in field_inputs(farm_id).items():
        values[k] = {"label": iv["label"], "value": iv["value"], "unit": "", "group": "input"}
    if tl.get("start"):
        put("period", "Simulated period", f"{tl['start']} to {tl['end']}", "", "input")
    # outputs
    for k, label, unit in _TOTALS:
        put(k, label, totals.get(k), unit, "output")
    for k, label, unit in _STRESS:
        put(k, label, stress.get(k), unit, "output")

    return {
        "run_id": rid, "start": tl.get("start"), "end": tl.get("end"),
        "values": values,
        "crops": crops,
        "chartable_fields": [{"field": f, "label": lbl, "unit": u} for f, (lbl, u) in SERIES_FIELDS.items()],
        "has_run": bool(rid and totals),
    }


def _iso_to_bucket(d: str, agg: str) -> str:
    dt = date.fromisoformat(d)
    if agg == "year":
        return f"{dt.year}"
    if agg == "month":
        return f"{dt.year}-{dt.month:02d}"
    return d  # daily


def series(farm_id: str, fields: list[str], agg: str = "month") -> dict:
    """Aggregated daily series for the requested fields -> {x[], series[{field,label,unit,data[]}]}.
    Flux fields sum within a bucket; state fields average. agg: day|month|year."""
    rid = latest_run_id(farm_id)
    tl = rt.build_timeline(rid) if rid else {}
    raw = tl.get("series") or []
    requested = list(fields or [])
    valid = [f for f in requested if f in SERIES_FIELDS]
    if requested and not valid:  # caller asked for fields, none exist -> don't silently swap in defaults
        return {"run_id": rid, "agg": agg, "x": [], "series": [], "error":
                f"Unknown field(s) {requested}; pick from chartable_fields ({', '.join(sorted(SERIES_FIELDS))})."}
    fields = valid or ["precip", "irr", "et"]  # default only when NO fields were requested

    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in raw:
        b = _iso_to_bucket(r["date"], agg)
        if b not in buckets:
            buckets[b] = []
            order.append(b)
        buckets[b].append(r)

    out_series = []
    for f in fields:
        lbl, unit = SERIES_FIELDS[f]
        data = []
        for b in order:
            rows = buckets[b]
            vals = [float(r.get(f, 0) or 0) for r in rows]
            v = sum(vals) if f in _FLUX else (sum(vals) / len(vals) if vals else 0)
            data.append(round(v, 3))
        out_series.append({"field": f, "label": lbl, "unit": unit, "data": data})
    return {"run_id": rid, "agg": agg, "x": order, "series": out_series}
