"""Farm CRUD routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from db import create_farm, delete_farm, db_one, get_farms, update_farm
from services import insights_service, readiness_service

router = APIRouter(prefix="/api/farms", tags=["farms"])


class FarmCreate(BaseModel):
    name: str
    location: str = ""
    soil_type: str = ""
    txtinout_path: str = ""
    data_source: str = ""


class FarmUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    soil_type: Optional[str] = None
    txtinout_path: Optional[str] = None
    setup_complete: Optional[bool] = None
    data_source: Optional[str] = None


@router.get("")
def list_farms():
    return get_farms()


@router.post("")
def add_farm(farm: FarmCreate):
    if not farm.name.strip():
        raise HTTPException(status_code=400, detail="Name required")
    return create_farm(
        farm.name, farm.location, farm.soil_type, farm.txtinout_path, farm.data_source
    )


@router.patch("/{farm_id}")
def patch_farm(farm_id: str, body: FarmUpdate):
    farm = update_farm(farm_id, **body.model_dump(exclude_none=True))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return farm


@router.get("/{farm_id}/readiness")
def farm_readiness(farm_id: str):
    result = readiness_service.get_farm_readiness(farm_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{farm_id}/insights")
def farm_insights(farm_id: str):
    result = insights_service.get_farm_insights(farm_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{farm_id}/crop")
def farm_crop_settings(farm_id: str):
    from services import crop_service
    result = crop_service.get_crop_settings(farm_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


class CropSettingsBody(BaseModel):
    crop_type: str
    planting_date: str


class AutoSetupBody(BaseModel):
    crop_type: str = ""
    planting_date: str = ""
    location_hint: str = ""
    run_first_simulation: bool = True


@router.post("/{farm_id}/auto-setup")
def auto_setup_farm_field(farm_id: str, body: AutoSetupBody):
    from services import field_setup_service
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = field_setup_service.auto_setup_field_for_swat(
        farm_id,
        crop_type=body.crop_type,
        planting_date=body.planting_date,
        location_hint=body.location_hint,
        run_first_simulation=body.run_first_simulation,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Setup failed"))
    return result


@router.get("/{farm_id}/dataset-status")
def farm_dataset_status(farm_id: str):
    from services import field_setup_service
    result = field_setup_service.get_field_dataset_status(farm_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.put("/{farm_id}/crop")
def save_farm_crop_settings(farm_id: str, body: CropSettingsBody):
    from services import crop_service
    result = crop_service.save_crop_settings(farm_id, body.crop_type, body.planting_date)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Could not save crop"))
    return result


@router.delete("/{farm_id}")
def remove_farm(farm_id: str):
    from services import field_service
    return field_service.delete_field(farm_id)
