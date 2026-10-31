"""Autonomous field setup — boundary, datasets, SWAT+ TxtInOut, crop, first run."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Optional

from db import db_one, update_farm
from services import crop_service, data_service, insights_service, readiness_service
from services import data_download_service, pyswat_facade
from services.swat_service import swat
from utils.text import safe_text


def _geocode(query: str) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "No location provided"}

    coord_match = re.match(
        r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$",
        query,
    )
    if coord_match:
        a = float(coord_match.group(1))
        b = float(coord_match.group(2))
        if abs(a) <= 90 and abs(b) <= 180:
            lat, lon = a, b
        elif abs(b) <= 90 and abs(a) <= 180:
            lat, lon = b, a
        else:
            return {"ok": False, "error": "Coordinates out of range"}
        return {"ok": True, "lat": lat, "lon": lon, "label": f"{lat:.5f}, {lon:.5f}"}

    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AI-SWAT+/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": safe_text(str(exc))}
    if not data:
        return {"ok": False, "error": f"Could not find location: {query}"}
    item = data[0]
    return {
        "ok": True,
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "label": item.get("display_name", query),
    }


def _box_boundary(lat: float, lon: float, delta: float = 0.004) -> dict:
    """Approximate field polygon (~400–500 m) centered on a point."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"source": "ai_swat_geocode"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lon - delta, lat - delta],
                    [lon + delta, lat - delta],
                    [lon + delta, lat + delta],
                    [lon - delta, lat + delta],
                    [lon - delta, lat - delta],
                ]],
            },
        }],
    }


def get_field_dataset_status(farm_id: str) -> dict[str, Any]:
    """What data exists for this field and what is still missing."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"ok": False, "error": "Farm not found"}

    boundary = data_download_service.get_boundary_status(farm_id)
    readiness = readiness_service.get_farm_readiness(farm_id)
    inventory = data_service.get_farm_data_inventory(farm_id)
    crop = crop_service.get_crop_settings(farm_id)
    validation = inventory.get("txtinout_validation") or {}
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    complete_upload = readiness_service._is_complete_uploaded_project(farm, txtinout, validation)

    gis_files = inventory.get("gis_files") or []
    file_names = {f.get("name") for f in gis_files if isinstance(f, dict)}

    def gis_ready(standard_name: str, alt_names: tuple[str, ...] = ()) -> bool:
        if complete_upload:
            return True
        return standard_name in file_names or any(n in file_names for n in alt_names)

    datasets = {
        "boundary": {
            "ready": boundary.get("has_boundary", False) or gis_ready("boundary.geojson"),
            "area_ha": boundary.get("area_ha"),
            "detail": (
                "Included in uploaded SWAT+ project" if complete_upload and boundary.get("has_boundary")
                else "Farm outline on map" if boundary.get("has_boundary") or gis_ready("boundary.geojson")
                else "Missing — draw on Maps or give a location"
            ),
        },
        "elevation": {
            "ready": gis_ready("dem.tif"),
            "detail": "Included in uploaded project" if complete_upload else "DEM from online download",
        },
        "soil": {
            "ready": gis_ready("soil.geojson", ("soils.sol",)),
            "detail": farm.get("soil_type") or ("Included in uploaded project" if complete_upload else "From SoilGrids when downloaded"),
        },
        "landuse": {
            "ready": gis_ready("landuse.tif") or complete_upload,
            "detail": "Included in uploaded project" if complete_upload else "Rasterized from your boundary (cropland)",
        },
        "weather": {
            "ready": gis_ready("weather_openmeteo.json") or readiness_service._weather_ok(str(txtinout)),
            "detail": (
                "SWAT+ weather files in uploaded project (pcp/tem)"
                if readiness_service._weather_ok(str(txtinout))
                else "Daily weather from Open-Meteo archive"
                if gis_ready("weather_openmeteo.json")
                else "Missing weather"
            ),
        },
        "field_model": {
            "ready": any(c.get("id") == "txtinout" and c.get("status") == "ok" for c in readiness.get("checks", [])),
            "detail": "SWAT+ TxtInOut built for this field",
        },
        "crop": {
            "ready": crop.get("configured", False) or crop_service.crop_in_txtinout(txtinout),
            "detail": (
                f"{crop.get('crop_label')} planted {crop.get('planting_date')}"
                if crop.get("configured")
                else (
                    f"{crop_service.read_crop_from_txtinout(txtinout).get('crop_label', 'Crop')} in uploaded project"
                    if crop_service.crop_in_txtinout(txtinout)
                    else "Crop type and planting date not set"
                )
            ),
        },
    }

    missing = [k for k, v in datasets.items() if not v.get("ready")]
    return {
        "ok": True,
        "farm_id": farm_id,
        "farm_name": farm.get("name"),
        "location": farm.get("location") or "",
        "ready_to_simulate": readiness.get("ready_to_simulate", False),
        "setup_complete": bool(farm.get("setup_complete")),
        "datasets": datasets,
        "missing": missing,
        "maps_url": f"/gis?farm={farm_id}",
        "setup_url": f"/setup?farm={farm_id}",
    }


def set_field_boundary_from_location(
    farm_id: str,
    location_hint: str = "",
) -> dict[str, Any]:
    """Geocode a place name or coordinates and save an approximate field boundary."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"ok": False, "error": "Farm not found"}

    query = (location_hint or farm.get("location") or farm.get("name") or "").strip()
    if not query:
        return {
            "ok": False,
            "error": "No location. Tell me your city, address, or lat/lon, or draw the field on Maps.",
            "maps_url": f"/gis?farm={farm_id}",
        }

    geo = _geocode(query)
    if not geo.get("ok"):
        return {"ok": False, "error": geo.get("error"), "maps_url": f"/gis?farm={farm_id}"}

    boundary = _box_boundary(geo["lat"], geo["lon"])
    saved = data_download_service.save_boundary(farm_id, boundary)
    if farm.get("location") != geo.get("label"):
        update_farm(farm_id, location=geo.get("label", query)[:200])

    return {
        "ok": True,
        "message": f"Saved approximate field boundary near {geo.get('label')}. Refine the outline on Maps if needed.",
        "center": saved.get("center"),
        "area_ha": saved.get("area_ha"),
        "maps_url": f"/gis?farm={farm_id}",
        "note": "Boundary is a starter rectangle — user can redraw on Maps for exact shape.",
    }


def _default_planting_date() -> str:
    today = date.today()
    year = today.year if today.month <= 10 else today.year + 1
    return f"{year}-04-15"


def _poll_simulation(run_id: str, max_wait: int = 180) -> dict[str, Any]:
    import time
    for _ in range(max(1, max_wait // 3)):
        status = swat.status(run_id)
        state = status.get("status", "")
        if state == "completed":
            return status
        if state in ("failed", "cancelled", "not_found"):
            return {"error": status.get("error") or f"Simulation {state}", "status": state}
        time.sleep(3)
    return {"error": "Simulation timed out", "run_id": run_id}


def auto_setup_field_for_swat(
    farm_id: str,
    crop_type: str = "",
    planting_date: str = "",
    location_hint: str = "",
    run_first_simulation: bool = True,
) -> dict[str, Any]:
    """
    End-to-end: locate field → download real datasets → build TxtInOut → crop → optional first SWAT+ run.
    """
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"ok": False, "error": "Farm not found"}

    steps: list[dict[str, Any]] = []

    boundary = data_download_service.get_boundary_status(farm_id)
    if not boundary.get("has_boundary"):
        loc_result = set_field_boundary_from_location(farm_id, location_hint)
        steps.append({"step": "boundary", **loc_result})
        if not loc_result.get("ok"):
            return {
                "ok": False,
                "error": loc_result.get("error"),
                "steps": steps,
                "next_action": "Open Maps and draw your field, or provide a clearer location (city, address, or lat/lon).",
                "maps_url": f"/gis?farm={farm_id}",
            }
        boundary = data_download_service.get_boundary_status(farm_id)

    readiness = readiness_service.get_farm_readiness(farm_id)
    if not readiness.get("ready_to_simulate"):
        build = data_download_service.fetch_and_build_farm(farm_id)
        steps.append({
            "step": "download_and_build",
            "ok": build.get("ok", False),
            "hru_count": build.get("hru_count"),
            "sources": (build.get("fetch") or {}).get("sources") if isinstance(build.get("fetch"), dict) else build.get("sources"),
            "error": build.get("error"),
            "message": build.get("message"),
        })
        if not build.get("ok"):
            return {
                "ok": False,
                "error": build.get("error") or "Could not download or build field model.",
                "steps": steps,
                "maps_url": f"/gis?farm={farm_id}",
            }
        if build.get("fetch", {}).get("soil_type"):
            update_farm(farm_id, soil_type=build["fetch"]["soil_type"])
        elif build.get("soil_type"):
            update_farm(farm_id, soil_type=build["soil_type"])
        readiness = readiness_service.get_farm_readiness(farm_id)

    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not crop_service.is_crop_configured(farm):
        ct = (crop_type or "corn").strip().lower()
        pd = (planting_date or _default_planting_date()).strip()
        crop_result = crop_service.save_crop_settings(farm_id, ct, pd)
        steps.append({"step": "crop", **crop_result})
        if not crop_result.get("ok"):
            return {"ok": False, "error": crop_result.get("error"), "steps": steps}

    status = get_field_dataset_status(farm_id)
    steps.append({"step": "status", "datasets": status.get("datasets"), "missing": status.get("missing")})

    sim_result: Optional[dict[str, Any]] = None
    if run_first_simulation and status.get("ready_to_simulate") and not farm.get("setup_complete"):
        period = readiness.get("simulation_period") or {}
        job = swat.start_run(
            farm_id=farm_id,
            begin_date=period.get("begin", "01-Jan-2020"),
            end_date=period.get("end", "31-Dec-2024"),
            warmup_years=2,
            parameters=[],
            print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
            scenario="irrigation",
        )
        if job.status == "failed":
            steps.append({"step": "simulation", "ok": False, "error": job.error})
        else:
            finished = _poll_simulation(job.job_id)
            sim_result = finished
            ok = finished.get("status") == "completed"
            steps.append({
                "step": "simulation",
                "ok": ok,
                "run_id": job.job_id,
                "error": finished.get("error"),
            })
            if ok:
                update_farm(farm_id, setup_complete=True)
                insights = insights_service.get_farm_insights(farm_id)
                steps.append({
                    "step": "insights",
                    "irrigation": insights.get("irrigation", {}).get("headline"),
                    "has_data": insights.get("has_data"),
                })

    final = get_field_dataset_status(farm_id)
    return {
        "ok": True,
        "message": (
            "Field is set up with real elevation, soil, land use, and weather. "
            "SWAT+ model is ready."
            + (" First simulation completed." if any(s.get("step") == "simulation" and s.get("ok") for s in steps) else "")
        ),
        "farm_name": farm.get("name"),
        "ready_to_simulate": final.get("ready_to_simulate"),
        "setup_complete": final.get("setup_complete"),
        "datasets": final.get("datasets"),
        "steps": steps,
        "setup_url": f"/setup?farm={farm_id}",
        "maps_url": f"/gis?farm={farm_id}",
        "chat_hint": "User can now ask about irrigation, fertilizer, or yield for this field.",
    }
