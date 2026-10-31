"""Data volume registration — large files on disk, paths via API."""
from __future__ import annotations

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

import config
from db import db_one, update_farm
from schemas.swat import GisPathsRegister, ObservedPathsRegister
from services import data_service, readiness_service

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/farms/{farm_id}")
def farm_data_inventory(farm_id: str):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return data_service.get_farm_data_inventory(farm_id)


@router.post("/farms/{farm_id}/gis")
def register_gis(farm_id: str, body: GisPathsRegister):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return data_service.register_gis_paths(farm_id, body.model_dump(exclude_none=True))


@router.post("/farms/{farm_id}/observed")
def register_observed(farm_id: str, body: ObservedPathsRegister):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return data_service.register_observed_paths(farm_id, body.files)


@router.post("/farms/{farm_id}/inbox/upload")
async def upload_to_inbox(farm_id: str, file: UploadFile = File(...)):
    from services import file_ingest_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    content = await file.read()
    return file_ingest_service.save_upload_to_inbox(farm_id, file.filename or "upload.bin", content)


@router.get("/farms/{farm_id}/inbox/inspect")
def inspect_farm_inbox(farm_id: str):
    from services import file_ingest_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return file_ingest_service.inspect_inbox(farm_id)


@router.post("/farms/{to_farm_id}/copy-setup")
def copy_farm_setup(to_farm_id: str, body: dict):
    from services import file_ingest_service
    from_farm_id = (body or {}).get("from_farm_id", "")
    if not from_farm_id:
        raise HTTPException(status_code=400, detail="from_farm_id required")
    to_farm = db_one("SELECT * FROM farms WHERE id = ?", (to_farm_id,))
    if not to_farm:
        raise HTTPException(status_code=404, detail="Destination farm not found")
    result = file_ingest_service.copy_field_setup(from_farm_id, to_farm_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Copy failed"))
    readiness = readiness_service.get_farm_readiness(to_farm_id)
    return {**result, "readiness": readiness}


@router.post("/farms/{farm_id}/inbox/import")
def import_farm_inbox(farm_id: str, body: dict | None = None):
    from services import file_ingest_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    run_sim = bool((body or {}).get("run_first_simulation"))
    if run_sim:
        result = file_ingest_service.setup_from_uploaded_files(farm_id, run_first_simulation=True)
    else:
        result = file_ingest_service.import_inbox_for_swat(farm_id, run_build=True)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Import failed"))
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {**result, "readiness": readiness}


@router.post("/farms/{farm_id}/upload")
async def upload_to_gis(
    farm_id: str,
    file: UploadFile = File(...),
    layer: str = "dem",
):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    dest_dir = config.farm_gis_dir(farm_id)
    content = await file.read()
    saved = data_service.save_upload(dest_dir, file.filename or "upload.bin", content)
    return {"farm_id": farm_id, "layer": layer, "path": saved}


@router.post("/farms/{farm_id}/txtinout")
async def upload_txtinout(farm_id: str, file: UploadFile = File(...)):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    content = await file.read()
    result = data_service.extract_txtinout_zip(farm_id, content)
    if not result.get("ready"):
        raise HTTPException(status_code=400, detail=result.get("validation", {}).get("error", "Invalid project"))
    update_farm(farm_id, txtinout_path=result["txtinout_dir"], data_source="upload")
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {**result, "readiness": readiness}


@router.post("/farms/{farm_id}/demo")
def load_demo_farm(farm_id: str):
    raise HTTPException(
        status_code=403,
        detail="Demo/sample data is disabled. Draw your field on Maps and download real elevation, soil, and weather, or upload a field model zip in Setup.",
    )



@router.get("/farms/{farm_id}/boundary")
def get_farm_boundary(farm_id: str):
    from services import data_download_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    geojson = data_download_service.load_boundary(farm_id)
    return {
        "farm_id": farm_id,
        "geojson": geojson,
        **data_download_service.get_boundary_status(farm_id),
    }


@router.post("/farms/{farm_id}/boundary")
def save_farm_boundary(farm_id: str, body: dict):
    from services import data_download_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    geojson = body.get("geojson") or body
    if not geojson.get("features") and geojson.get("type") != "Feature":
        raise HTTPException(status_code=400, detail="Send GeoJSON FeatureCollection")
    return data_download_service.save_boundary(farm_id, geojson)


@router.post("/farms/{farm_id}/fetch-online")
def fetch_online_farm_data(farm_id: str):
    from services import data_download_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = data_download_service.fetch_online_data(farm_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fetch failed"))
    if result.get("soil_type"):
        update_farm(farm_id, soil_type=result["soil_type"])
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {**result, "readiness": readiness}


@router.post("/farms/{farm_id}/build-model")
def build_farm_model(farm_id: str):
    from services import data_download_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = data_download_service.build_farm_model_from_downloads(farm_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Build failed"))
    update_farm(farm_id, txtinout_path=result.get("txtinout_path"), data_source="online")
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {**result, "readiness": readiness}


@router.post("/farms/{farm_id}/fetch-and-build")
def fetch_and_build_farm_data(farm_id: str, options: dict | None = Body(default=None)):
    """Build a complete, runnable project from the field boundary + the farmer's
    collected choices (rotation, manure, irrigation tier, sim length). gSSURGO
    dominant soil + management + auto-irrigation on rev-62; Galen defaults fill gaps."""
    from services import build_project_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = build_project_service.build_field_for_farm(farm_id, options)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Build failed"))
    soil = result.get("soil", {})
    update_farm(
        farm_id,
        txtinout_path=result.get("txtinout_path"),
        data_source="gssurgo_rev62",
        soil_type=(soil.get("soil") or "") if soil.get("ok") else "",
    )
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {**result, "readiness": readiness}


@router.get("/farms/{farm_id}/status")
def farm_data_status(farm_id: str):
    from services import farm_data_status as fds
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return fds.get_farm_data_status(farm_id)


@router.get("/farms/{farm_id}/files/preview")
def preview_farm_file(farm_id: str, zone: str, path: str):
    from services import farm_data_status as fds
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    try:
        return fds.preview_file(farm_id, zone, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/farms/{farm_id}/readiness")
def farm_readiness_alias(farm_id: str):
    result = readiness_service.get_farm_readiness(farm_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
