"""Scenario shortcuts — run simulation and return farmer advice."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from typing import Literal

from pydantic import BaseModel, Field

from db import db_one, update_farm
from services import insights_service, pyswat_facade, readiness_service
from services.swat_service import swat

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

SCENARIO_MAP = {
    "irrigation": "irrigation",
    "fertilizer": "fertilizer",
    "nitrate": "nitrate",
    "yield": "yield",
}


class ScenarioRunRequest(BaseModel):
    farm_id: str
    scenario: Literal["irrigation", "fertilizer", "nitrate", "yield"] = "irrigation"
    begin_date: str = ""
    end_date: str = ""
    warmup_years: int = 2


@router.post("/run")
def run_scenario(req: ScenarioRunRequest) -> dict[str, Any]:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (req.farm_id,))
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    readiness = readiness_service.get_farm_readiness(req.farm_id)
    if not readiness.get("ready_to_simulate"):
        raise HTTPException(status_code=400, detail="Farm is not ready - complete setup first")

    period = readiness.get("simulation_period") or {}
    begin = req.begin_date or period.get("begin", "01-Jan-2024")
    end = req.end_date or period.get("end", "31-Dec-2024")

    result = swat.start_run(
        farm_id=req.farm_id,
        begin_date=begin,
        end_date=end,
        warmup_years=req.warmup_years,
        parameters=[],
        print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
        scenario=SCENARIO_MAP.get(req.scenario, req.scenario),
    )
    run_id = result.job_id

    output = None
    status = "running"
    for _ in range(60):
        time.sleep(2)
        st = swat.status(run_id)
        status = st.get("status", "running")
        if status == "completed":
            output = st.get("output_summary") or st.get("outputs")
            break
        if status in ("failed", "not_found", "cancelled"):
            raise HTTPException(status_code=500, detail=st.get("error") or "Simulation failed")

    if not output:
        raise HTTPException(status_code=504, detail="Simulation timed out")

    advice = insights_service.scenario_advice(req.scenario, output)
    insights = insights_service.build_insights(output)

    update_farm(req.farm_id, setup_complete=True)

    return {
        "run_id": run_id,
        "status": status,
        "scenario": req.scenario,
        "advice": advice,
        "output_summary": output,
        "insights": insights,
        "charts": {
            "water_balance": output.get("water_balance"),
            "nutrient_balance": output.get("nutrient_balance"),
            "nitrate": output.get("nitrate"),
            "nitrate_monthly": output.get("nitrate_monthly"),
            "daily_series": output.get("daily_series"),
            "yield_kgha": output.get("yield_kgha"),
        },
    }
