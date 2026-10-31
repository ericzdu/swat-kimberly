"""Parse a SWAT+ run's mgt_out.txt into a structured management timeline:
crop growing periods (plant -> harvest, with biomass) plus discrete irrigation
and fertilizer/manure events across the full simulation. Feeds the run-timeline
visualization in the canvas.
"""
from __future__ import annotations

import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_OPS = {"PLANT", "PLANT_ALREADY_GROWING", "HARV/KILL", "IRRIGATE", "FERT",
        "TILLAGE", "GRAZE", "PEST_APPLY", "BURN"}
# crop code -> friendly label (icons are added on the frontend where UTF-8 is safe)
CROP_LABELS = {
    "corn": "Corn", "csil": "Corn silage", "soyb": "Soybeans", "wwht": "Winter wheat",
    "barl": "Barley", "alfa": "Alfalfa", "past": "Pasture", "frst": "Forest",
}


def _mgt_out_path(run_id: str) -> Path | None:
    out = config.run_output_dir(run_id)
    for c in (out / "mgt_out.txt", out / "workspace" / "TxtInOut" / "mgt_out.txt"):
        if c.is_file():
            return c
    return None


def _iso(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


# Daily series to surface from each output file (field -> present only if in header).
_WB_FIELDS = ["precip", "irr", "et", "pet", "sw_ave", "perc", "surq_gen", "wateryld", "snomlt", "latq"]
_PW_FIELDS = ["bioms", "lai", "yield", "residue", "strsw", "strsn", "strstmp", "strsa",
              "percn", "tmpav", "tmx", "tmn", "solarad", "phubas0"]
_NB_FIELDS = ["fertn", "nuptake", "denit", "gwsoiln", "fixn", "no3atmo"]


def _read_day_file(path: Path, wanted: list[str]) -> dict[str, dict[str, float]]:
    """Column-map a SWAT+ daily output file -> {iso_date: {field: value}} for wanted fields."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if len(lines) < 3:
        return {}
    header = lines[1].split()
    col = {n: header.index(n) for n in wanted if n in header}
    date_col = {k: header.index(k) for k in ("yr", "mon", "day") if k in header}
    if len(date_col) < 3:
        return {}
    out: dict[str, dict[str, float]] = {}
    hi = max(list(col.values()) + list(date_col.values()))
    for row in lines[2:]:
        f = row.split()
        if len(f) <= hi:
            continue
        try:
            date = _iso(f[date_col["yr"]], f[date_col["mon"]], f[date_col["day"]])
        except (ValueError, KeyError):
            continue
        rec: dict[str, float] = {}
        for name, i in col.items():
            try:
                rec[name] = float(f[i])
            except ValueError:
                pass
        out[date] = rec
    return out


def _daily_series(run_id: str) -> list[dict]:
    """Merge daily water-balance, plant/stress and nitrogen files into per-day records."""
    out = config.run_output_dir(run_id)
    roots = [out, out / "workspace" / "TxtInOut"]

    def find(name: str) -> Path | None:
        for r in roots:
            p = r / name
            if p.is_file():
                return p
        return None

    merged: dict[str, dict[str, float]] = {}
    for fname, fields in (("hru_wb_day.txt", _WB_FIELDS),
                          ("hru_pw_day.txt", _PW_FIELDS),
                          ("hru_nb_day.txt", _NB_FIELDS)):
        p = find(fname)
        if not p:
            continue
        for date, rec in _read_day_file(p, fields).items():
            merged.setdefault(date, {}).update(rec)

    return [{"date": d, **merged[d]} for d in sorted(merged)]


def build_timeline(run_id: str) -> dict:
    path = _mgt_out_path(run_id)
    if not path:
        return {"ok": False, "error": "No management log (mgt_out.txt) for this run."}

    crops: list[dict] = []          # {crop, label, icon, plant, harvest, biomass_kgha}
    events: list[dict] = []         # {date, type, amount, unit, label, crop}
    open_plant: dict[str, dict] = {}  # crop -> pending plant record
    irr_total = 0.0
    min_d, max_d = None, None

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines()[2:]:
        f = raw.split()
        if len(f) < 6:
            continue
        try:
            date = _iso(f[1], f[2], f[3])
        except (ValueError, IndexError):
            continue
        min_d = date if min_d is None or date < min_d else min_d
        max_d = date if max_d is None or date > max_d else max_d

        # field 5 is either the operation (FERT) or a crop/impl name; find the op token
        if f[4] in _OPS:
            op, name, num0 = f[4], None, 5
        elif len(f) > 5 and f[5] in _OPS:
            op, name, num0 = f[5], f[4], 6
        else:
            continue
        if op.startswith("PLANT"):  # PLANT / PLANT_ALREADY_GROWING -> a plant start
            op = "PLANT"

        def num(i: int, default: float = 0.0) -> float:
            try:
                return float(f[num0 + i])
            except (ValueError, IndexError):
                return default

        op_var = num(7)          # applied amount (mm for irrigation, kg/ha for fert)
        biomass = num(3)         # plant_bioms column

        if op == "PLANT":
            open_plant.setdefault(name or "crop", {"plant": date})  # keep first (ignore daily repeats)
        elif op == "HARV/KILL":
            key = name or "crop"
            rec = open_plant.pop(key, {"plant": None})
            # op_var on a HARV/KILL row is pl_yield%m — the harvested yield, which is
            # NOT the same as standing biomass. Exposing both lets the UI show the
            # realised harvest index (yield / biomass) against the crop's parameter.
            crops.append({"crop": key, "label": CROP_LABELS.get(key, key.title()),
                          "plant": rec.get("plant"), "harvest": date,
                          "biomass_kgha": round(biomass, 1),
                          "yield_kgha": round(op_var, 1)})
        elif op == "IRRIGATE":
            irr_total += op_var
            events.append({"date": date, "type": "irrigation", "amount": round(op_var, 1),
                           "unit": "mm", "label": "Irrigation"})
        elif op == "FERT":
            events.append({"date": date, "type": "fertilizer", "amount": round(op_var, 1),
                           "unit": "kg/ha", "label": "Manure / fertilizer"})
        else:
            events.append({"date": date, "type": op.lower(), "amount": round(op_var, 1),
                           "unit": "", "label": op.title()})

    # any plant never harvested within the window -> show as still growing
    for key, rec in open_plant.items():
        crops.append({"crop": key, "label": CROP_LABELS.get(key, key.title()),
                      "plant": rec.get("plant"), "harvest": None, "biomass_kgha": None})

    # Daily series defines the authoritative REPORTED window (mgt_out also logs the
    # skipped spin-up year); clip crops + events to it so the charts and bands align.
    daily = _daily_series(run_id)
    win0 = daily[0]["date"] if daily else min_d
    win1 = daily[-1]["date"] if daily else max_d

    def overlaps(c: dict) -> bool:
        p, h = c.get("plant"), c.get("harvest")
        if h and h < win0:
            return False
        if p and p > win1:
            return False
        return True

    crops = [c for c in crops if overlaps(c)]
    events = [e for e in events if win0 <= e["date"] <= win1]
    crops.sort(key=lambda c: c.get("plant") or c.get("harvest") or "")
    events.sort(key=lambda e: e["date"])
    irr_events = [e for e in events if e["type"] == "irrigation"]
    fert_events = [e for e in events if e["type"] == "fertilizer"]

    def dsum(field: str) -> float:
        return round(sum(r.get(field, 0.0) for r in daily), 2)

    def dmax(field: str) -> float:
        return round(max((r.get(field, 0.0) for r in daily), default=0.0), 1)

    def dmean(field: str, rows: list[dict]) -> float:
        vals = [r.get(field, 0.0) for r in rows]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    grow_days = [r for r in daily if r.get("bioms", 0) > 1]
    def stress_days(field: str, thr: float = 0.5) -> int:  # >0.5 = meaningfully limiting
        return sum(1 for r in grow_days if r.get(field, 0.0) > thr)

    applied = dsum("fertn")
    uptake = dsum("nuptake")
    leached = round(dsum("percn") + dsum("gwsoiln"), 2)
    harvested = [c for c in crops if c.get("biomass_kgha")]
    yield_kgha = max((c["biomass_kgha"] for c in harvested), default=dmax("bioms"))
    sw_start = round(daily[0].get("sw_ave", 0.0), 1) if daily else 0.0
    sw_end = round(daily[-1].get("sw_ave", 0.0), 1) if daily else 0.0

    totals = {
        "precip_mm": dsum("precip"), "irr_mm": dsum("irr"), "et_mm": dsum("et"),
        "pet_mm": dsum("pet"), "perc_mm": dsum("perc"), "surq_mm": dsum("surq_gen"),
        "latq_mm": dsum("latq"),
        "fertn_kgha": applied, "fixn_kgha": dsum("fixn"), "nuptake_kgha": uptake,
        "denit_kgha": dsum("denit"), "leached_kgha": leached,
        "sw_start": sw_start, "sw_end": sw_end, "sw_delta": round(sw_end - sw_start, 1),
        "yield_kgha": round(yield_kgha, 1), "peak_bioms": dmax("bioms"),
        "nue_pct": round(uptake / applied * 100, 1) if applied > 0 else None,
    } if daily else {}

    stress = {
        "water_days": stress_days("strsw"), "n_days": stress_days("strsn"),
        "temp_days": stress_days("strstmp"), "aeration_days": stress_days("strsa"),
        "mean_strsw": dmean("strsw", grow_days), "mean_strsn": dmean("strsn", grow_days),
        "grow_days": len(grow_days),
    } if daily else {}

    return {
        "ok": True,
        "run_id": run_id,
        "start": win0,
        "end": win1,
        "crops": crops,
        "events": events,
        "series": daily,
        "totals": totals,
        "stress": stress,
        "summary": {
            "irrigation_events": len(irr_events),
            "irrigation_total_mm": round(irr_total, 1) if not daily else totals.get("irr_mm", 0),
            "fertilizer_events": len(fert_events),
            "fertilizer_total_kgha": round(sum(e["amount"] for e in fert_events), 1),
            "harvests": len(harvested),
            "crops": sorted({c["label"] for c in crops}),
        },
    }
