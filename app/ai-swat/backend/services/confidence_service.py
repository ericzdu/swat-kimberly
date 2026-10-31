"""
Field data & confidence self-assessment.

Synthesizes already-computed signals (readiness, dataset status, provenance,
calibration state) into ONE honest report: what data the field has, its
source/quality, what outputs can be produced now and at what confidence, the
calibration state, and exactly what to provide to raise accuracy.

Design principle: SYNTHESIZE, don't re-read. No new TxtInOut file-walking and
no new numeric code — calibration metrics come from the existing
swat_service.compute_metrics / pyswat_facade.compute_metrics.

Grounded in the reliability research: an uncalibrated single-farm run is not
trustworthy for absolute nutrient/nitrate/yield numbers (those are directional
until calibrated); watershed-scale monthly streamflow is the reliable,
calibratable signal.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)

CALIBRATION_FILE = "calibration.json"

# Moriasi (2007) satisfactory bar for calling streamflow "calibrated / high".
_NSE_OK = 0.5
_PBIAS_OK = 25.0

LEVEL_LABELS = {
    "high": "High confidence",
    "moderate": "Moderate confidence",
    "low": "Low — estimate",
    "directional": "Directional only",
    "unavailable": "Not available yet",
}

_OUTPUT_LABELS = {
    "water_balance": "Water balance",
    "streamflow": "Streamflow",
    "irrigation": "Irrigation timing",
    "drought": "Drought risk",
    "fertilizer": "Fertilizer / nutrients",
    "nitrate": "Nitrate / water quality",
    "yield": "Crop yield",
}

_KIND_TO_OUTPUT = {
    "irrigation": "irrigation",
    "fertilizer": "fertilizer",
    "nitrate": "nitrate",
    "yield": "yield",
    "drought": "drought",
    "drought_risk": "drought",
    "water_balance": "water_balance",
}


# --------------------------------------------------------------------------- #
# Calibration state (lightweight — one JSON per farm in the observed dir)
# --------------------------------------------------------------------------- #

def _calibration_path(farm_id: str) -> Path:
    return config.farm_observed_dir(farm_id) / CALIBRATION_FILE


def read_calibration(farm_id: str) -> Optional[dict]:
    path = _calibration_path(farm_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("calibration.json parse failed for %s: %s", farm_id, exc)
        return None


def record_calibration(
    farm_id: str,
    variable: str,
    indicators: list[str],
    metrics: Any,
    sim_file: str,
    obs_file: str,
) -> dict:
    """Persist a calibration record so confidence reflects it. Write-side only."""
    record = {
        "variable": variable,
        "indicators": indicators,
        "metrics": metrics,
        "sim_file": str(sim_file),
        "obs_file": str(obs_file),
        "calibrated_at": datetime.now().isoformat(),
    }
    path = _calibration_path(farm_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def _observed_files(farm_id: str) -> list[str]:
    from services import data_service

    inv = data_service.get_farm_data_inventory(farm_id)
    out = []
    for f in inv.get("observed_files") or []:
        if f.get("is_dir"):
            continue
        name = f.get("name", "")
        if name == CALIBRATION_FILE:
            continue
        out.append(name)
    return out


def read_calibration_state(farm_id: str) -> str:
    cal = read_calibration(farm_id)
    if cal and cal.get("metrics"):
        return "calibrated"
    if _observed_files(farm_id):
        return "observed_available_not_calibrated"
    return "uncalibrated"


def _metric_val(metrics: Any, *names: str) -> Optional[float]:
    if not isinstance(metrics, dict):
        return None
    lower = {str(k).lower(): v for k, v in metrics.items()}
    for n in names:
        if n.lower() in lower:
            v = lower[n.lower()]
            # metric may be a nested {value: x} or a scalar
            if isinstance(v, dict):
                v = v.get("value") or v.get("val")
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _calibrated_for(cal: Optional[dict], *variables: str) -> bool:
    if not cal or not cal.get("metrics"):
        return False
    v = (cal.get("variable") or "").lower()
    return any(x in v for x in variables)


def _streamflow_calibration_ok(cal: Optional[dict]) -> bool:
    if not _calibrated_for(cal, "streamflow", "flow", "discharge"):
        return False
    metrics = (cal or {}).get("metrics") or {}
    nse = _metric_val(metrics, "NSE", "nse", "nashsutcliffe")
    if nse is None or nse < _NSE_OK:
        return False
    pbias = _metric_val(metrics, "PBIAS", "pbias")
    if pbias is not None and abs(pbias) > _PBIAS_OK:
        return False
    return True


# --------------------------------------------------------------------------- #
# Assessment
# --------------------------------------------------------------------------- #

def _check(readiness: dict, cid: str) -> dict:
    for c in readiness.get("checks", []) or []:
        if c.get("id") == cid:
            return c
    return {}


def assess_field_data_and_confidence(
    farm_id: str,
    readiness: Optional[dict] = None,
) -> dict:
    """Unified data + confidence report for a field. Reuses readiness,
    dataset-status, provenance helpers, and calibration state."""
    from db import db_one
    from services import readiness_service, field_setup_service

    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"farm_id": farm_id, "error": "Farm not found", "outputs": [],
                "inputs": [], "can_produce_now": [], "data_to_improve": [],
                "overall_confidence": "low", "headline": "Farm not found."}

    if readiness is None:
        readiness = readiness_service.get_farm_readiness(farm_id)

    ready = bool(readiness.get("ready_to_simulate"))
    block = readiness.get("block_reason") or "Field is not ready to simulate yet."
    data_source = readiness.get("data_source") or ""

    dataset = field_setup_service.get_field_dataset_status(farm_id)
    datasets = dataset.get("datasets", {}) or {}

    def ds_ready(key: str) -> bool:
        return bool(datasets.get(key, {}).get("ready"))

    def ds_detail(key: str) -> str:
        return datasets.get(key, {}).get("detail", "") or ""

    gis_verified = readiness_service._has_verified_gis_manifest(farm_id)
    uploaded = data_source.strip().lower() in ("upload", "upload_verified")
    # A location-grounded build (gSSURGO soil + gridMET weather) is verified map data too;
    # per-layer quality stays gated by ds_ready(), so template layers aren't overstated.
    grounded_build = data_source.strip().lower() in ("gssurgo_rev62", "online", "online_verified")
    grounded_gis = gis_verified or uploaded or grounded_build

    cal = read_calibration(farm_id)
    cal_state = read_calibration_state(farm_id)
    obs_files = _observed_files(farm_id)

    weather_ok = _check(readiness, "weather").get("status") == "ok"
    weather_quality = "high" if weather_ok else "missing"

    def gis_quality(key: str) -> str:
        if not ds_ready(key):
            return "missing"
        return "high" if grounded_gis else "medium"

    crop_ready = ds_ready("crop")
    observed_quality = "high" if cal_state == "calibrated" else ("medium" if obs_files else "missing")

    inputs = [
        {"id": "weather", "present": weather_ok, "quality": weather_quality,
         "source": "Real daily weather (Open-Meteo)" if weather_ok else "none",
         "detail": _check(readiness, "weather").get("detail", "")},
        {"id": "elevation", "present": ds_ready("elevation"), "quality": gis_quality("elevation"),
         "source": ("verified" if grounded_gis else "unverified") if ds_ready("elevation") else "none",
         "detail": ds_detail("elevation")},
        {"id": "soil", "present": ds_ready("soil"), "quality": gis_quality("soil"),
         "source": ("verified" if grounded_gis else "unverified") if ds_ready("soil") else "none",
         "detail": ds_detail("soil")},
        {"id": "landuse", "present": ds_ready("landuse"), "quality": gis_quality("landuse"),
         "source": ("verified" if grounded_gis else "unverified") if ds_ready("landuse") else "none",
         "detail": ds_detail("landuse")},
        {"id": "boundary", "present": ds_ready("boundary"), "quality": gis_quality("boundary"),
         "source": "drawn/saved" if ds_ready("boundary") else "none",
         "detail": ds_detail("boundary")},
        {"id": "crop", "present": crop_ready, "quality": "high" if crop_ready else "missing",
         "source": data_source or "not set", "detail": ds_detail("crop")},
        {"id": "observed", "present": bool(obs_files), "quality": observed_quality,
         "source": "calibrated" if cal_state == "calibrated" else ("uploaded" if obs_files else "none"),
         "detail": f"{len(obs_files)} file(s)" if obs_files else "No measured data uploaded"},
    ]

    # Derived flags for output confidence
    core_gis_high = all(gis_quality(k) == "high" for k in ("elevation", "soil", "landuse"))
    weather_high = weather_quality == "high"
    streamflow_hi = _streamflow_calibration_ok(cal)
    nutrient_cal = _calibrated_for(cal, "nutrient", "nitrogen", "phosphorus", "fertilizer")
    nitrate_cal = _calibrated_for(cal, "nitrate", "no3")
    yield_cal = _calibrated_for(cal, "yield")

    NITRATE_CAVEAT = (
        "Uncalibrated single-farm nitrate is directional only — it shows the trend and "
        "responds correctly to changes, but the absolute mg/L is not validated. Upload monthly "
        "streamflow and run a calibration check to raise confidence."
    )

    def water_group_level() -> str:
        if not ready:
            return "unavailable"
        if weather_high and core_gis_high and cal_state == "calibrated":
            return "high"
        if not weather_high:
            return "low"
        return "moderate"

    wg = water_group_level()
    outputs = []

    def add(oid, level, can, basis):
        outputs.append({"id": oid, "label": _OUTPUT_LABELS.get(oid, oid),
                        "confidence": level, "can_produce": bool(can), "basis": basis})

    if not ready:
        for oid in ("water_balance", "streamflow", "irrigation", "drought", "fertilizer", "nitrate", "yield"):
            add(oid, "unavailable", False, block)
    else:
        add("water_balance", wg, True,
            "Physical water balance is robust even uncalibrated; quality tracks weather and map data.")
        add("irrigation", wg, True,
            "Soil-moisture / irrigation timing derives from the water balance.")
        add("drought", wg, True,
            "Drought risk derives from the simulated water balance.")
        add("streamflow", "high" if streamflow_hi else "moderate", True,
            "Streamflow is the reliable, calibratable signal — reaches high confidence only when "
            "calibrated to observed flow (NSE ≥ 0.5, |PBIAS| ≤ 25)." if not streamflow_hi
            else "Calibrated to observed streamflow within Moriasi satisfactory bounds.")
        add("fertilizer", "moderate" if nutrient_cal else "low", True,
            "Absolute nutrient balance is uncertain uncalibrated — use it directionally until "
            "calibrated on nutrient observations.")
        add("nitrate", "moderate" if nitrate_cal else "directional", True, NITRATE_CAVEAT)
        add("yield", "moderate" if yield_cal else "low", bool(crop_ready),
            "Crop parameters are uncalibrated — yield is a rough estimate." if crop_ready
            else "Set crop type and planting date first, then yield can be estimated.")

    can_produce_now = [o["id"] for o in outputs if o["can_produce"]]

    # What to provide next, highest-leverage first
    data_to_improve = []
    if ready and cal_state == "uncalibrated":
        data_to_improve.append({
            "id": "observed", "priority": 1,
            "ask": "Upload measured monthly streamflow (discharge) for your field or a nearby gauge",
            "improves": ["streamflow", "water_balance", "irrigation", "nitrate"],
            "how": "Measured flow lets the model be calibrated (NSE/PBIAS) — the single biggest jump in "
                   "trustworthiness, and the only way to move numbers from directional to validated.",
        })
    if ready and cal_state == "observed_available_not_calibrated":
        data_to_improve.append({
            "id": "calibrate", "priority": 1,
            "ask": "Run a calibration check against your uploaded measurements",
            "improves": ["streamflow", "water_balance"],
            "how": "Computes NSE/PBIAS so results carry a real confidence level instead of an estimate.",
        })
    if not weather_high:
        data_to_improve.append({
            "id": "weather", "priority": 2,
            "ask": "Download real daily weather for your field (Maps)",
            "improves": ["water_balance", "irrigation", "drought", "nitrate", "yield"],
            "how": "Real rainfall/temperature drive every water and nutrient result.",
        })
    if ready and not core_gis_high:
        data_to_improve.append({
            "id": "gis", "priority": 3,
            "ask": "Download verified elevation, soil, and land-use layers (Maps)",
            "improves": ["water_balance", "streamflow", "nitrate"],
            "how": "Verified terrain and soil make the field's response physically grounded.",
        })
    if not crop_ready:
        data_to_improve.append({
            "id": "crop", "priority": 4,
            "ask": "Set crop type and planting date (Setup)",
            "improves": ["yield"],
            "how": "Required before the model can estimate yield at all.",
        })
    # If not ready at all, the setup guide is the real to-do list.
    if not ready:
        guide = (readiness.get("setup_guide") or {}).get("steps") or []
        for step in guide[:3]:
            data_to_improve.append({
                "id": step.get("id", "setup"), "priority": 0,
                "ask": step.get("title", "Complete setup"),
                "improves": ["all"], "how": step.get("detail", ""),
            })
    data_to_improve.sort(key=lambda d: d.get("priority", 9))

    if streamflow_hi:
        overall = "high"
    elif ready and wg in ("moderate", "high"):
        overall = "moderate"
    else:
        overall = "low"

    headline = _headline(ready, block, cal_state, overall)

    return {
        "farm_id": farm_id,
        "farm_name": farm.get("name"),
        "data_source": data_source,
        "ready_to_simulate": ready,
        "provenance": {
            "uploaded_swat_project": uploaded,
            "weather_real": weather_ok,
            "gis_verified": gis_verified,
        },
        "calibration_state": cal_state,
        "calibration": cal,
        "inputs": inputs,
        "outputs": outputs,
        "can_produce_now": can_produce_now,
        "data_to_improve": data_to_improve,
        "overall_confidence": overall,
        "headline": headline,
    }


def _headline(ready: bool, block: str, cal_state: str, overall: str) -> str:
    if not ready:
        return f"Not ready to simulate — {block}"
    if cal_state == "calibrated":
        return "Calibrated to measured data — results carry validated confidence."
    if cal_state == "observed_available_not_calibrated":
        return "Measurements uploaded but not yet calibrated — run a calibration check to validate."
    return ("Uncalibrated: water-balance and irrigation are usable estimates; nitrate, nutrients, "
            "and yield are directional only until calibrated.")


def output_confidence(assessment: dict, kind: str) -> Optional[dict]:
    """Pick the confidence entry for an insight kind (irrigation/fertilizer/nitrate/yield/drought)."""
    oid = _KIND_TO_OUTPUT.get(kind, kind)
    for o in assessment.get("outputs", []) or []:
        if o.get("id") == oid:
            level = o.get("confidence", "low")
            return {"level": level, "label": LEVEL_LABELS.get(level, level), "note": o.get("basis", "")}
    return None


def compact_confidence_block(assessment: dict) -> str:
    """<=8-line text block injected into the agent's FARM CONTEXT every turn."""
    if assessment.get("error"):
        return ""
    lines = ["DATA STATE & CONFIDENCE:"]
    lines.append(f"- Calibration: {assessment.get('calibration_state', 'uncalibrated')}")
    prov = assessment.get("provenance", {})
    lines.append(
        f"- Weather: {'real' if prov.get('weather_real') else 'missing'} | "
        f"Map layers: {'verified' if prov.get('gis_verified') or prov.get('uploaded_swat_project') else 'unverified/missing'}"
    )
    # outputs grouped by confidence for the agent to speak accurately
    by_level: dict[str, list[str]] = {}
    for o in assessment.get("outputs", []) or []:
        if not o.get("can_produce"):
            continue
        by_level.setdefault(o["confidence"], []).append(o["id"])
    usable = [f"{lvl}: {', '.join(ids)}" for lvl, ids in by_level.items() if lvl in ("high", "moderate")]
    directional = by_level.get("directional", []) + by_level.get("low", [])
    if usable:
        lines.append("- Can state with confidence — " + " | ".join(usable))
    if directional:
        lines.append("- Directional/estimate only (do NOT present as fact): " + ", ".join(directional))
    if not assessment.get("ready_to_simulate"):
        lines.append("- NOT ready to simulate — ask for setup data before giving numbers.")
    improve = assessment.get("data_to_improve", [])
    if improve:
        lines.append(f"- To improve accuracy (ask the farmer): {improve[0]['ask']}")
    return "\n".join(lines)
