"""Farm readiness checks for farmer onboarding."""

from __future__ import annotations



from pathlib import Path

from typing import Any, Optional



import config

from db import db_one

from services import data_service, pyswat_facade



MANIFEST_NAME = "data_manifest.json"





def _weather_ok(txtinout: str) -> bool:

    tio = Path(txtinout)

    marker = tio / ".weather_source"

    if marker.exists() and marker.read_text(encoding="utf-8").strip() == "open-meteo":

        return (tio / "farm_weather.pcp").exists() and (tio / "farm_weather.tem").exists()

    weather_files = list(tio.glob("*.pcp")) + list(tio.glob("*.tem"))

    return len(weather_files) > 0 and (tio / "weather-sta.cli").exists()





def _read_gis_manifest(farm_id: str) -> Optional[dict]:

    manifest = config.farm_gis_dir(farm_id) / MANIFEST_NAME

    if not manifest.exists():

        return None

    try:

        import json

        return json.loads(manifest.read_text(encoding="utf-8"))

    except Exception:

        return None


def _has_verified_gis_manifest(farm_id: str) -> bool:

    data = _read_gis_manifest(farm_id)

    return bool(data) and bool(data.get("verified")) and bool(data.get("sources"))


# Builds where the real datasets are applied directly from the field's coordinates
# (gSSURGO dominant soil + gridMET daily weather) — these ARE verified map layers even
# without a downloaded-layer manifest, so they must not be flagged "less accurate".
_GROUNDED_SOURCES = ("gssurgo_rev62", "online", "online_verified")


def _is_grounded_build(farm: dict, txtinout: Path) -> bool:

    return (farm.get("data_source") or "").strip().lower() in _GROUNDED_SOURCES and _weather_ok(str(txtinout))





def _is_complete_uploaded_project(farm: dict, txtinout: Path, validation: dict) -> bool:
    """Uploaded TxtInOut zip with weather — self-contained, no separate GIS download needed."""
    if not validation.get("valid"):
        return False
    source = (farm.get("data_source") or "").strip().lower()
    if source not in ("upload", "upload_verified"):
        return False
    return _weather_ok(str(txtinout))


def _simulation_data_allowed(farm_id: str, farm: dict, txtinout: Path, validation: dict) -> tuple[bool, str]:

    if not validation.get("valid"):

        return False, validation.get("error") or "Field model files are missing or invalid."



    source = (farm.get("data_source") or "").strip().lower()

    if source == "demo":

        return False, "Demo/sample project cannot be used for farm simulations. Download real map data on Maps or upload a field model zip in Setup."



    if not _weather_ok(str(txtinout)):

        return False, "Weather data is missing. Re-download map data on Maps or upload a complete TxtInOut zip with weather files."



    if _is_complete_uploaded_project(farm, txtinout, validation):

        return True, ""



    if source in ("online", "online_verified"):

        if not _has_verified_gis_manifest(farm_id):

            return False, "Downloaded map layers are incomplete or unverified. Open Maps and download data again."



    if source in ("upload", "upload_verified"):

        if not _has_verified_gis_manifest(farm_id):

            return False, "Uploaded GIS layers are incomplete. Re-import your files or upload a complete TxtInOut zip."



    return True, ""




def should_block_online_rebuild(farm_id: str) -> tuple[bool, str]:
    """Prevent online download from replacing a complete uploaded SWAT+ project."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return False, ""
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    validation = pyswat_facade.validate_txtinout(txtinout)
    if _is_complete_uploaded_project(farm, txtinout, validation):
        return True, (
            "This field has a complete uploaded SWAT+ project (TxtInOut + weather). "
            "Use setup_field_from_uploaded_files — not fetch_online_map_data."
        )
    try:
        from services import file_ingest_service
        inbox = file_ingest_service.inspect_inbox(farm_id)
        if (inbox.get("summary") or {}).get("has_complete_txtinout"):
            return True, (
                "The inbox has a complete SWAT+ zip. "
                "Use setup_field_from_uploaded_files to import it."
            )
    except Exception:
        pass
    return False, ""




def get_farm_readiness(farm_id: str) -> dict[str, Any]:

    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))

    if not farm:

        return {"error": "Farm not found", "ready_to_simulate": False}



    inventory = data_service.get_farm_data_inventory(farm_id)

    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)

    validation = inventory.get("txtinout_validation") or {}

    period = pyswat_facade.read_simulation_period(txtinout) if validation.get("valid") else {}



    period_label = ""

    if period.get("source"):

        begin = period.get("begin", "")[-4:]

        end = period.get("end", "")[-4:]

        if begin and end:

            period_label = f"{begin}-{end}"



    checks: list[dict[str, str]] = []



    if validation.get("valid"):

        checks.append({

            "id": "txtinout",

            "label": "Field model data",

            "status": "ok",

            "detail": period_label or validation.get("format", "ready"),

        })

    else:

        checks.append({

            "id": "txtinout",

            "label": "Field model data",

            "status": "missing",

            "detail": validation.get("error") or "Draw your field on Maps and download real map data, or upload a field model zip in Setup.",

        })



    if validation.get("valid") and _weather_ok(str(txtinout)):

        checks.append({"id": "weather", "label": "Weather data", "status": "ok", "detail": "Real daily weather included"})

    elif validation.get("valid"):

        checks.append({

            "id": "weather",

            "label": "Weather data",

            "status": "missing",

            "detail": "No verified weather files — re-download map data or upload TxtInOut with weather from Setup",

        })

    else:

        checks.append({"id": "weather", "label": "Weather data", "status": "missing", "detail": "n/a"})



    gis_manifest = _has_verified_gis_manifest(farm_id)

    gis_count = len(inventory.get("gis_files") or [])

    complete_upload = _is_complete_uploaded_project(farm, txtinout, validation)

    grounded_build = _is_grounded_build(farm, txtinout)

    if gis_manifest or complete_upload or grounded_build:

        if complete_upload and not gis_manifest:

            detail = "Included in uploaded SWAT+ project"

        elif gis_manifest:

            srcs = (_read_gis_manifest(farm_id) or {}).get("sources")

            detail = ", ".join(srcs) if srcs else "Verified soil, weather, and land layers"

        else:

            detail = "gSSURGO soil + gridMET weather grounded to the field location"

        checks.append({"id": "gis", "label": "Farm map layers", "status": "ok", "detail": detail})

    elif gis_count > 0:

        checks.append({

            "id": "gis",

            "label": "Farm map layers",

            "status": "warning",

            "detail": "GIS files present but not verified — re-download from Maps",

        })

    else:

        checks.append({

            "id": "gis",

            "label": "Farm map layers",

            "status": "missing",

            "detail": "Draw boundary on Maps and download elevation, soil, and weather",

        })



    obs_count = len(inventory.get("observed_files") or [])

    from services import crop_service
    crop_configured = crop_service.is_crop_configured(farm) or crop_service.crop_in_txtinout(txtinout)
    if crop_configured:
        if crop_service.is_crop_configured(farm):
            crop_label = _CROP_LABEL(farm)
            crop_detail = f"{crop_label} planted {farm.get('planting_date', '')}"
        else:
            inferred = crop_service.read_crop_from_txtinout(txtinout)
            crop_label = inferred.get("crop_label") or inferred.get("crop_type") or "Crop"
            crop_detail = f"{crop_label} from uploaded project"
        checks.append({
            "id": "crop",
            "label": "Crop details",
            "status": "ok",
            "detail": crop_detail,
        })
    else:
        checks.append({
            "id": "crop",
            "label": "Crop details",
            "status": "missing",
            "detail": "Set crop type and planting date in Setup (required for yield estimates)",
        })

    if obs_count > 0:

        checks.append({"id": "observed", "label": "Measured data", "status": "ok", "detail": f"{obs_count} file(s)"})

    else:

        checks.append({"id": "observed", "label": "Measured data", "status": "optional", "detail": "Not uploaded"})



    last_run = _last_completed_run(farm_id)

    allowed, block_reason = _simulation_data_allowed(farm_id, farm, txtinout, validation)



    return {

        "farm_id": farm_id,

        "farm_name": farm.get("name"),

        "setup_complete": bool(farm.get("setup_complete")),

        "data_source": farm.get("data_source") or "",

        "ready_to_simulate": allowed,

        "block_reason": block_reason if not allowed else "",

        "checks": checks,

        "last_run": last_run,

        "simulation_period": period if period.get("source") else None,

        "txtinout_path": str(txtinout),

        "setup_guide": build_setup_guide(farm_id, farm, checks, allowed),

    }





def _CROP_LABEL(farm: dict) -> str:
    from services.crop_service import _CROP_BY_ID
    cid = (farm.get("crop_type") or "").strip()
    return _CROP_BY_ID.get(cid, {}).get("label", cid or "Crop")


def build_setup_guide(

    farm_id: str,

    farm: dict,

    checks: list[dict],

    ready: bool,

) -> dict[str, Any]:

    """Plain-language next steps for advisor and UI."""

    from services.data_download_service import get_boundary_status



    boundary = get_boundary_status(farm_id)

    steps: list[dict[str, str]] = []



    if not boundary.get("has_boundary"):

        steps.append({

            "id": "boundary",

            "title": "Draw your farm on the map",

            "detail": "Open Maps, click around your field to outline it, then save the boundary.",

            "action": f"/gis?farm={farm_id}",

        })



    txtinout = next((c for c in checks if c["id"] == "txtinout"), None)

    if txtinout and txtinout["status"] == "missing":

        steps.append({

            "id": "field_model",

            "title": "Download real map data",

            "detail": "On Maps, save your boundary then download elevation (DEM), soil, land use, and weather for your area.",

            "action": f"/gis?farm={farm_id}",

        })



    weather = next((c for c in checks if c["id"] == "weather"), None)

    if weather and weather["status"] == "missing":

        steps.append({

            "id": "weather",

            "title": "Add weather for your field",

            "detail": "Re-run map download or upload a complete field model zip in Setup that includes weather files.",

            "action": f"/gis?farm={farm_id}",

        })



    crop = next((c for c in checks if c["id"] == "crop"), None)

    if crop and crop["status"] == "missing":

        steps.append({

            "id": "crop",

            "title": "Add crop details",

            "detail": "In Setup, choose your crop type and planting date. Everything is done in AI-SWAT+ — you do not need QSWAT+.",

            "action": f"/setup?farm={farm_id}",

        })



    if not ready:

        steps.append({

            "id": "wizard",

            "title": "Finish setup wizard",

            "detail": "Complete the checklist once real map and weather data are in place.",

            "action": f"/setup?farm={farm_id}",

        })

    elif not farm.get("setup_complete"):

        steps.append({

            "id": "first_run",

            "title": "Run your first simulation",

            "detail": "Open Setup and run the farm model to unlock full advisor tools.",

            "action": f"/setup?farm={farm_id}",

        })



    if ready and farm.get("setup_complete"):

        steps.append({

            "id": "advisor",

            "title": "Farm is ready",

            "detail": "Ask about irrigation, fertilizer, or yield.",

            "action": "/chat",

        })



    return {

        "next_step": steps[0] if steps else None,

        "steps": steps,

        "has_boundary": boundary.get("has_boundary", False),

        "quick_options": [

            "Draw boundary on Maps and download elevation, soil, land use, and weather",

            "Upload an existing field model zip in Setup",

        ],

    }





def _last_completed_run(farm_id: str) -> Optional[dict]:

    row = db_one(

        """SELECT id, status, created_at, completed_at FROM simulations

           WHERE farm_id = ? AND status = 'completed'

           ORDER BY completed_at DESC LIMIT 1""",

        (farm_id,),

    )

    if not row:

        return None

    return {

        "run_id": row["id"],

        "status": row["status"],

        "completed_at": row.get("completed_at"),

        "created_at": row.get("created_at"),

    }

