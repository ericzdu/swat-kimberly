"""SWAT+ model API — pySWATPlus-powered run, metrics, sensitivity."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from db import db_one
from schemas.swat import (
    EngineStatus,
    MetricsRequest,
    MetricsResponse,
    PrepareRequest,
    SensitivityJobResponse,
    SensitivityRequest,
    SwatRunRequest,
    SwatRunResponse,
    SwatRunStatus,
    TimeseriesRequest,
    TxtInOutValidation,
)
from services import data_service, pyswat_facade
from services.swat_service import swat

router = APIRouter(prefix="/api/swat", tags=["swat"])


@router.get("/engine", response_model=EngineStatus)
def engine_status():
    return swat.engine_status()


@router.get("/validate/{farm_id}", response_model=TxtInOutValidation)
def validate_txtinout(farm_id: str):
    result = swat.validate_farm_txtinout(farm_id)
    if result.get("error") == "Farm not found":
        raise HTTPException(status_code=404, detail="Farm not found")
    return result


@router.post("/run", response_model=SwatRunResponse)
def run_swat(req: SwatRunRequest):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (req.farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = swat.start_run(
        farm_id=req.farm_id,
        begin_date=req.begin_date,
        end_date=req.end_date,
        warmup_years=req.warmup_years,
        parameters=[p.model_dump() for p in req.parameters],
        print_prt_control=req.print_prt_control,
        scenario=req.scenario,
    )
    if result.status == "failed":
        raise HTTPException(status_code=422, detail=result.error)
    return SwatRunResponse(run_id=result.job_id, status=result.status)


@router.get("/runs/{run_id}", response_model=SwatRunStatus)
def get_run_status(run_id: str):
    data = swat.status(run_id)
    if data.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    return SwatRunStatus(
        run_id=run_id,
        status=data.get("status", "not_found"),
        progress=data.get("progress"),
        farm_id=data.get("farm_id"),
        job_type=data.get("job_type"),
        outputs=data.get("outputs"),
        output_summary=data.get("output_summary"),
        error=data.get("error"),
    )


@router.get("/runs/farm/{farm_id}")
def list_farm_runs(farm_id: str, limit: int = 20):
    return swat.list_for_farm(farm_id, limit=limit)


class RunLabel(BaseModel):
    label: str


@router.post("/runs/{run_id}/label")
def label_run(run_id: str, body: RunLabel):
    result = swat.set_label(run_id, body.label.strip())
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Run not found"))
    return result


class RerunBody(BaseModel):
    label: str | None = None


@router.post("/runs/{run_id}/rerun")
def rerun_run(run_id: str, body: RerunBody):
    result = swat.rerun(run_id, (body.label or None))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Re-run failed"))
    return result


@router.delete("/runs/{run_id}")
def cancel_run(run_id: str):
    return swat.cancel(run_id)


@router.get("/runs/{run_id}/files")
def list_run_files(run_id: str):
    return {"run_id": run_id, "files": swat.list_output_files(run_id)}


@router.get("/runs/{run_id}/timeline")
def get_run_timeline(run_id: str):
    """Structured management timeline (crop rotation periods + irrigation/fertilizer
    events) parsed from the run's mgt_out.txt, for the canvas timeline visualization."""
    from services import run_timeline_service
    result = run_timeline_service.build_timeline(run_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "No timeline"))
    return result


@router.get("/runs/{run_id}/download")
def download_run_outputs(run_id: str):
    out_dir = config.run_output_dir(run_id)
    if not out_dir.exists() or not any(out_dir.iterdir()):
        raise HTTPException(status_code=404, detail="No output files for this run")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out_dir.iterdir():
            if f.is_file():
                zf.write(f, arcname=f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=swat_run_{run_id}.zip"},
    )


@router.post("/runs/{run_id}/timeseries")
def get_timeseries(run_id: str, farm_id: str, req: TimeseriesRequest):
    try:
        data = swat.get_timeseries(
            farm_id=farm_id,
            run_id=run_id,
            sim_file=req.sim_file,
            begin_date=req.begin_date,
            end_date=req.end_date,
            has_units=req.has_units,
            ref_day=req.ref_day,
            apply_filter=req.apply_filter,
            usecols=req.usecols,
        )
        return {"run_id": run_id, "timeseries": data}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/metrics", response_model=MetricsResponse)
def compute_metrics(req: MetricsRequest):
    try:
        indicators = swat.compute_metrics(
            farm_id=req.farm_id,
            sim_file=req.sim_file,
            obs_file=req.obs_file,
            indicators=req.indicators,
            sim_col=req.sim_col,
            obs_col=req.obs_col,
            date_format=req.date_format,
            run_id=req.run_id,
            extract_sim=req.extract_sim,
        )
        return MetricsResponse(indicators=indicators, sim_file=req.sim_file, obs_file=req.obs_file)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sensitivity", response_model=SensitivityJobResponse)
def start_sensitivity(req: SensitivityRequest):
    farm = db_one("SELECT * FROM farms WHERE id = ?", (req.farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    result = swat.start_sensitivity(
        farm_id=req.farm_id,
        parameters=[p.model_dump() for p in req.parameters],
        sample_number=req.sample_number,
        extract_data=req.extract_data,
    )
    if result.status == "failed":
        raise HTTPException(status_code=422, detail=result.error)
    return SensitivityJobResponse(job_id=result.job_id, status=result.status)


@router.post("/prepare")
def prepare_txtinout(req: PrepareRequest):
    from services.gis_service import gis_service
    from services.hru_generator import export_txtinout, hru_generator

    farm = db_one("SELECT * FROM farms WHERE id = ?", (req.farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    out_dir = config.farm_txtinout_dir(req.farm_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = hru_generator.generate(
        gis_service,
        lu_threshold=req.lu_threshold,
        soil_threshold=req.soil_threshold,
    )
    if not result.success:
        raise HTTPException(status_code=422, detail=result.error or "HRU generation failed")

    created = export_txtinout(hru_generator.hru_gdf, str(out_dir))
    from db import db_exec

    db_exec("UPDATE farms SET txtinout_path = ? WHERE id = ?", (str(out_dir), req.farm_id))
    validation = pyswat_facade.validate_txtinout(out_dir)
    return {
        "success": True,
        "hru_count": result.hru_count,
        "txtinout_path": str(out_dir),
        "files": list(created.keys()),
        "validation": validation,
    }
