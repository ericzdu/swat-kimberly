"""Backward-compatible /api/simulate aliases → /api/swat."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import db_one
from services import pyswat_facade
from services.swat_service import swat

router = APIRouter(prefix="/api/simulate", tags=["simulation-legacy"])


class SimCreate(BaseModel):
    farm_id: str
    simulation_type: str = "irrigation"
    begin_date: str = "01-Jan-2024"
    end_date: str = "31-Dec-2024"
    parameters: dict = {}


@router.get("/engine")
def simulation_engine_status():
    return swat.engine_status()


@router.post("")
def create_simulation(req: SimCreate):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (req.farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = swat.start_run(
        farm_id=req.farm_id,
        begin_date=req.begin_date,
        end_date=req.end_date,
        warmup_years=req.parameters.get("warmup_years", 2),
        parameters=req.parameters.get("parameters", []),
        print_prt_control=req.parameters.get("print_prt_control") or pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
        scenario=req.simulation_type,
    )
    if result.status == "failed":
        raise HTTPException(status_code=422, detail=result.error)
    return {"simulation_id": result.job_id, "status": result.status}


@router.get("/farm/{farm_id}")
def list_farm_simulations(farm_id: str, limit: int = 20):
    return swat.list_for_farm(farm_id, limit=limit)


@router.get("/{sim_id}")
def get_simulation_status(sim_id: str):
    return swat.status(sim_id)
