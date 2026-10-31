"""
Farm-scoped LangChain tools for the LangGraph ReAct agent.

Tools are bound to the selected farm_id so the LLM does not need to guess IDs.
"""
from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.tools import tool

from db import create_farm, db_one, get_farms
import config
from services import data_service, insights_service, pyswat_facade, readiness_service
from services import pyswat_facade
from services.swat_service import swat


def _poll_run(run_id: str, max_wait: int = 120) -> dict[str, Any]:
    for _ in range(max(1, max_wait // 3)):
        status = swat.status(run_id)
        state = status.get("status", "")
        if state == "completed":
            return status
        if state in ("failed", "cancelled", "not_found"):
            return {"error": status.get("error") or f"Simulation {state}", "status": state}
        time.sleep(3)
    return {"error": "Simulation timed out", "run_id": run_id}


def _run_and_wait(farm_id: str, scenario: str, max_wait: int = 120) -> dict[str, Any]:
    readiness = readiness_service.get_farm_readiness(farm_id)
    if not readiness.get("ready_to_simulate"):
        return {"error": readiness.get("block_reason") or "Farm not ready — complete real map and weather data first."}

    period = readiness.get("simulation_period") or {}
    begin = period.get("begin", "01-Jan-2024")
    end = period.get("end", "31-Dec-2024")

    job = swat.start_run(
        farm_id=farm_id,
        begin_date=begin,
        end_date=end,
        warmup_years=2,
        parameters=[],
        print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
        scenario=scenario,
    )
    if job.status == "failed":
        return {"error": job.error or "Failed to start simulation"}

    result = _poll_run(job.job_id, max_wait=max_wait)
    output = result.get("output_summary") or result.get("outputs") or {}
    return {
        "run_id": job.job_id,
        "status": result.get("status", "completed"),
        "output_summary": output,
        "error": result.get("error"),
    }


def build_farm_tools(farm_id: str) -> list:
    """Create LangChain tools scoped to one farm."""

    @tool
    def get_current_farm_info() -> dict:
        """Get name, location, soil type, and data source for the farmer's selected farm."""
        farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
        if not farm:
            return {"error": "Farm not found"}
        return {
            "id": farm["id"],
            "name": farm["name"],
            "location": farm.get("location"),
            "soil_type": farm.get("soil_type"),
            "data_source": farm.get("data_source"),
            "setup_complete": bool(farm.get("setup_complete")),
        }

    @tool
    def check_farm_data_ready() -> dict:
        """Check whether field model, weather, and maps are ready. Use before running simulations."""
        return readiness_service.get_farm_readiness(farm_id)

    @tool
    def get_latest_farm_insights() -> dict:
        """Get irrigation, fertilizer, drought, and yield insights from the latest completed simulation."""
        return insights_service.get_farm_insights(farm_id)

    @tool
    def explain_last_simulation_results() -> str:
        """Explain the latest simulation results in plain language for the farmer."""
        insights = insights_service.get_farm_insights(farm_id)
        if not insights.get("has_data"):
            return "No simulation results yet. Use run_irrigation_analysis or complete Setup first."
        lines = [
            f"**{insights.get('farm_name', 'Farm')} - latest results**",
            f"Irrigation: {insights['irrigation']['headline']} - {insights['irrigation']['detail']}",
            f"Fertilizer: {insights['fertilizer']['headline']} - {insights['fertilizer']['detail']}",
            f"Water quality (nitrate): {insights['nitrate']['headline']} - {insights['nitrate']['detail']}",
            f"Drought risk: {insights['drought_risk']['headline']}",
            f"Yield: {insights['yield']['headline']}",
        ]
        return "\n".join(lines)

    @tool
    def run_irrigation_analysis() -> str:
        """Run SWAT+ water model and return an irrigation recommendation. Use when farmer asks about watering or soil moisture."""
        result = _run_and_wait(farm_id, "irrigation")
        if result.get("error") and not result.get("output_summary"):
            return f"Could not run analysis: {result['error']}"
        output = result.get("output_summary") or {}
        if not output.get("water_balance"):
            insights = insights_service.build_insights(output)
            if insights.get("has_data"):
                return insights["irrigation"]["advice"] or insights["irrigation"]["headline"]
            return f"Simulation finished but water data missing. {result.get('error', '')}"
        advice = insights_service.interpret_irrigation(output)
        wb = output.get("water_balance", {})
        return (
            f"{advice['advice']}\n\n"
            f"Soil moisture: {wb.get('soil_moisture_mm', 0):.0f} mm | "
            f"ET: {wb.get('et_mm', 0):.0f} mm | Precip: {wb.get('precip_mm', 0):.0f} mm"
        )

    @tool
    def run_fertilizer_analysis() -> str:
        """Run SWAT+ and return fertilizer / nutrient advice. Use when farmer asks about nitrogen, phosphorus, or fertilizing."""
        result = _run_and_wait(farm_id, "fertilizer")
        if result.get("error") and not result.get("output_summary"):
            return f"Could not run analysis: {result['error']}"
        output = result.get("output_summary") or {}
        advice = insights_service.interpret_fertilizer(output)
        nb = output.get("nutrient_balance") or {}
        return (
            f"{advice['advice']}\n\n"
            f"N: {nb.get('nitrogen_kgha', 0):.0f} kg/ha | P: {nb.get('phosphorus_kgha', 0):.0f} kg/ha"
        )

    @tool
    def run_nitrate_analysis() -> str:
        """Run SWAT+ and return a nitrate / water-quality assessment. Use when the farmer asks about nitrate, water quality, nitrogen leaching, groundwater contamination, runoff pollution, or nutrient loss to streams."""
        result = _run_and_wait(farm_id, "nitrate")
        if result.get("error") and not result.get("output_summary"):
            return f"Could not run analysis: {result['error']}"
        output = result.get("output_summary") or {}
        advice = insights_service.interpret_nitrate(output)
        nit = output.get("nitrate") or {}
        stream = nit.get("stream") or {}
        conc = stream.get("mean_no3_mgL")
        conc_txt = f" | Est. stream nitrate: {conc:.1f} mg/L (limit 10)" if conc is not None else ""
        return (
            f"{advice['headline']}. {advice['advice']}\n\n"
            f"N leached to groundwater: {nit.get('leached_to_groundwater_kgha', 0):.1f} kg/ha | "
            f"Total N loss: {nit.get('total_no3_loss_kgha', 0):.1f} kg/ha{conc_txt}"
        )

    @tool
    def run_yield_analysis() -> str:
        """Run SWAT+ and estimate crop yield. Use when farmer asks about expected harvest."""
        farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
        from services import crop_service
        txtinout = data_service.resolve_farm_txtinout(farm_id, farm) if farm else None
        if farm and not crop_service.is_crop_configured(farm) and not (txtinout and crop_service.crop_in_txtinout(txtinout)):
            return crop_service.crop_setup_message(farm_id)
        result = _run_and_wait(farm_id, "yield")
        if result.get("error") and not result.get("output_summary"):
            return f"Could not run analysis: {result['error']}"
        output = result.get("output_summary") or {}
        advice = insights_service.interpret_yield(output)
        return advice["advice"] or advice["headline"]

    @tool
    def start_swat_simulation(simulation_type: str = "irrigation") -> str:
        """Start a SWAT+ simulation in the background. simulation_type: irrigation, fertilizer, or yield. Returns run_id for wait_for_simulation."""
        readiness = readiness_service.get_farm_readiness(farm_id)
        if not readiness.get("ready_to_simulate"):
            return "ERROR: Farm not ready for simulation"
        period = readiness.get("simulation_period") or {}
        job = swat.start_run(
            farm_id=farm_id,
            begin_date=period.get("begin", "01-Jan-2024"),
            end_date=period.get("end", "31-Dec-2024"),
            warmup_years=2,
            parameters=[],
            print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
            scenario=simulation_type,
        )
        if job.status == "failed":
            return f"ERROR: {job.error}"
        return job.job_id

    @tool
    def wait_for_simulation(run_id: str, max_wait_seconds: int = 120) -> str:
        """Wait for a simulation run_id to finish. Returns JSON with output_summary (water_balance, nutrient_balance, yield_kgha)."""
        result = _poll_run(run_id, max_wait=max_wait_seconds)
        payload = {
            "status": result.get("status"),
            "run_id": run_id,
            "output_summary": result.get("output_summary") or result.get("outputs"),
            "error": result.get("error"),
        }
        return json.dumps(payload, default=str)

    @tool
    def list_all_farms() -> list:
        """List all farms in the system."""
        return get_farms()

    @tool
    def create_new_field(
        name: str,
        location: str = "",
        user_confirmed: bool = False,
        transfer_from_current_field: bool = True,
    ) -> dict:
        """Create a new farm/field in AI-SWAT+. Ask the user first. Only set user_confirmed=True after they explicitly agree (yes, create it, go ahead, sure). Uploaded files and SWAT+ setup on the current field are copied to the new field by default."""
        clean_name = (name or "").strip()
        if not clean_name:
            return {"ok": False, "error": "Field name is required."}
        if not user_confirmed:
            loc = f" near {location.strip()}" if location.strip() else ""
            from services import file_ingest_service
            pending = file_ingest_service.field_has_transferable_data(farm_id)
            extra = ""
            if pending.get("should_transfer"):
                extra = " Their uploads/SWAT+ setup on the current field will move to the new field."
            return {
                "ok": False,
                "needs_permission": True,
                "proposed_name": clean_name,
                "message": (
                    f"Ask the user to confirm creating a new field named '{clean_name}'{loc}.{extra} "
                    "Call again with user_confirmed=True only after they say yes."
                ),
            }
        farm = create_farm(name=clean_name, location=(location or "").strip())
        transfer = None
        if transfer_from_current_field and farm_id != farm["id"]:
            from services import file_ingest_service
            if file_ingest_service.field_has_transferable_data(farm_id).get("should_transfer"):
                transfer = file_ingest_service.copy_field_setup(farm_id, farm["id"])
        msg = f"Created field '{farm['name']}'. The app will switch to this field."
        if transfer and transfer.get("ok"):
            msg = transfer.get("message") or msg
        elif transfer and not transfer.get("ok"):
            msg += f" Note: could not copy prior uploads ({transfer.get('error', 'unknown')})."
        return {
            "ok": True,
            "farm_id": farm["id"],
            "farm_name": farm["name"],
            "location": farm.get("location") or "",
            "transfer": transfer,
            "message": msg,
        }

    @tool
    def copy_field_setup_from(source_field: str) -> dict:
        """Copy inbox, GIS, and TxtInOut from another field (by name or id) into the current field. Use when uploads or import went to the wrong field."""
        from services import file_ingest_service
        hint = (source_field or "").strip()
        if not hint:
            return {"ok": False, "error": "Source field name or id required."}
        source_id = None
        for f in get_farms():
            if f["id"] == hint or f["name"].lower() == hint.lower():
                source_id = f["id"]
                break
        if not source_id:
            low = hint.lower()
            for f in get_farms():
                if low in f["name"].lower():
                    source_id = f["id"]
                    break
        if not source_id:
            return {"ok": False, "error": f"No field found matching '{source_field}'."}
        return file_ingest_service.copy_field_setup(source_id, farm_id)

    @tool
    def get_farm_setup_guide() -> dict:
        """Get step-by-step setup instructions when the farm is not ready. Use when farmer asks how to set up or what is missing."""
        readiness = readiness_service.get_farm_readiness(farm_id)
        return {
            "ready_to_simulate": readiness.get("ready_to_simulate"),
            "setup_complete": readiness.get("setup_complete"),
            "checks": readiness.get("checks"),
            "setup_guide": readiness.get("setup_guide"),
            "hint": "Tell the farmer the next step in plain language. Mention Maps for drawing boundaries and downloading data. For yield, mention Setup → Crop details in this app — never QSWAT+.",
        }

    @tool
    def get_farm_crop_settings() -> dict:
        """Get crop type and planting date for this farm. Use before yield analysis or when farmer asks about crop setup."""
        from services import crop_service
        return crop_service.get_crop_settings(farm_id)

    @tool
    def save_farm_crop_settings(crop_type: str, planting_date: str) -> str:
        """Save crop and planting date in AI-SWAT+ Setup (YYYY-MM-DD). crop_type: corn, wheat, soybeans, cotton, alfalfa, sorghum, barley."""
        from services import crop_service
        result = crop_service.save_crop_settings(farm_id, crop_type, planting_date)
        if not result.get("ok"):
            return f"ERROR: {result.get('error')}"
        return result.get("message", "Crop saved.")

    @tool
    def apply_crop_rotation(blocks: list[str], irrigation: str = "medium") -> dict:
        """Apply a multi-year crop rotation to this field's SWAT+ model.

        blocks: the rotation in order, one entry per block as "crop:years".
          ["corn:5", "alfalfa:4"]                        -> 9-year rotation
          ["corn:3", "potato:1", "sugarbeet:1", "wheat:1"] -> 6-year rotation
        Crops: corn, corn silage, alfalfa, potato, sugar beet, spring wheat,
        winter wheat, soybean, barley.
        irrigation: "high", "medium" or "low" (auto-irrigation tier).

        This rewrites the management schedule so SWAT+ actually plants and harvests
        each crop in sequence. Use it whenever the farmer describes a rotation —
        do NOT tell them to edit files by hand. Start a simulation afterwards.
        """
        from services import management_service

        alias = {
            "corn": "corn", "maize": "corn", "grain corn": "corn",
            "corn silage": "csil", "silage": "csil", "silage corn": "csil", "csil": "csil",
            "alfalfa": "alfa", "alfa": "alfa", "lucerne": "alfa",
            "potato": "pota", "potatoes": "pota", "pota": "pota",
            "sugar beet": "sgbt", "sugarbeet": "sgbt", "sugarbeets": "sgbt", "beet": "sgbt", "sgbt": "sgbt",
            "wheat": "wwht", "winter wheat": "wwht", "wwht": "wwht",
            "spring wheat": "swht", "swht": "swht",
            "soybean": "soyb", "soybeans": "soyb", "soy": "soyb", "soyb": "soyb",
            "barley": "barl", "barl": "barl",
        }

        rotation: list[str] = []
        parsed: list[str] = []
        for blk in blocks or []:
            raw = str(blk).strip()
            if not raw:
                continue
            name, _, yrs = raw.partition(":")
            key = name.strip().lower()
            code = alias.get(key) or alias.get(key.rstrip("s"))
            if not code:
                return {"error": f"Unknown crop '{name.strip()}'. Supported: {', '.join(sorted(set(alias)))}"}
            try:
                n = max(1, int(float(yrs or 1)))
            except ValueError:
                n = 1
            rotation.extend([code] * n)
            parsed.append(f"{code}x{n}")

        if not rotation:
            return {"error": 'No rotation given. Pass blocks like ["corn:5", "alfalfa:4"].'}
        if len(rotation) > 30:
            return {"error": f"Rotation is {len(rotation)} years; keep it to 30 or fewer."}

        tio = config.farm_txtinout_dir(farm_id)
        if not (tio / "file.cio").exists():
            return {"error": "This field has no built model yet — build the field first."}

        result = management_service.apply_management(
            tio, crops=rotation, irrigation_tier=irrigation,
        )
        if not result.get("ok", True) or result.get("error"):
            return {"error": result.get("error") or "Could not apply the rotation."}
        return {
            "ok": True,
            "rotation_years": len(rotation),
            "sequence": rotation,
            "blocks": parsed,
            "irrigation_tier": irrigation,
            "next": "Now start the simulation, then report yield, water and nitrogen.",
        }

    @tool
    def set_simulation_years(years: int) -> dict:
        """Rebuild this field's model to cover a different number of simulation years.

        Use when the run is too short for what the farmer wants to see — e.g. a
        9-year rotation needs at least 9 years, and comparing rotations fairly needs
        whole cycles of each (18 years covers 9x2 and 6x3).

        This re-fetches that many years of weather and rebuilds the project, so it
        takes a couple of minutes and RESETS management — re-apply the crop rotation
        afterwards with apply_crop_rotation, then run.
        """
        from services import build_project_service

        try:
            n = int(years)
        except (TypeError, ValueError):
            return {"error": "years must be a whole number"}
        if n < 1 or n > 30:
            return {"error": "Choose between 1 and 30 years (the stable weather window ends 2013)."}

        result = build_project_service.build_field_for_farm(farm_id, {"sim_years": n})
        if not result.get("ok"):
            return {"error": result.get("error") or "Could not rebuild the field for that period."}
        y = result.get("sim_years") or []
        soil = (result.get("soil") or {}).get("soil")
        return {
            "ok": True,
            "years": n,
            "period": f"{y[0]}-{y[1]}" if len(y) == 2 else None,
            "soil": soil,
            "weather": (result.get("weather") or {}).get("source"),
            "next": "Management was reset — call apply_crop_rotation again, then start the simulation.",
        }

    @tool
    def load_demo_farm_data() -> str:
        """Demo data is disabled — farms must use real map downloads or upload a field model zip in Setup."""
        return (
            "ERROR: Demo/sample projects are not allowed. "
            "Guide the farmer to Maps to draw their field and download real data, "
            "or upload a field model zip in Setup."
        )

    @tool
    def inspect_uploaded_field_files() -> dict:
        """List and classify files the user uploaded to this farm's inbox (zip, DEM, soil, weather CSV, boundary, etc.)."""
        from services import file_ingest_service
        return file_ingest_service.inspect_inbox(farm_id)

    @tool
    def import_uploaded_field_data_for_swat() -> dict:
        """Sort uploaded inbox files into DEM/soil/boundary/weather, build SWAT+ TxtInOut. Use after user uploads data files."""
        from services import file_ingest_service
        return file_ingest_service.import_inbox_for_swat(farm_id, run_build=True)

    @tool
    def setup_field_from_uploaded_files(run_first_simulation: bool = False) -> dict:
        """Full pipeline from uploaded files: inspect, classify, populate SWAT+ datasets, build model, optional first run."""
        from services import file_ingest_service
        return file_ingest_service.setup_from_uploaded_files(farm_id, run_first_simulation=run_first_simulation)

    @tool
    def get_field_dataset_status() -> dict:
        """List what map/weather/model data exists for this field and what is still missing. Use when user asks about data or setup status."""
        from services import field_setup_service
        return field_setup_service.get_field_dataset_status(farm_id)

    @tool
    def set_field_boundary_from_location(location_hint: str = "") -> dict:
        """Geocode a place name, address, or lat/lon and save an approximate field boundary. Use when user points you to a location but has not drawn on the map yet."""
        from services import field_setup_service
        return field_setup_service.set_field_boundary_from_location(farm_id, location_hint)

    @tool
    def auto_setup_field_for_swat(
        crop_type: str = "",
        planting_date: str = "",
        location_hint: str = "",
        run_first_simulation: bool = True,
    ) -> dict:
        """Fully set up this field for SWAT+: boundary (from location if needed), download DEM/soil/weather, build TxtInOut, set crop, run first simulation. Use when user says set up my field, prepare for SWAT, populate dataset, or similar."""
        from services import field_setup_service
        return field_setup_service.auto_setup_field_for_swat(
            farm_id,
            crop_type=crop_type,
            planting_date=planting_date,
            location_hint=location_hint,
            run_first_simulation=run_first_simulation,
        )

    @tool
    def fetch_online_map_data() -> str:
        """Download elevation, soil, and weather for the saved farm boundary and build the SWAT+ field model. NEVER use when the user uploaded a complete SWAT+ zip — that would replace their project."""
        from services import data_download_service, readiness_service
        blocked, reason = readiness_service.should_block_online_rebuild(farm_id)
        if blocked:
            return f"BLOCKED: {reason}"
        status = data_download_service.get_boundary_status(farm_id)
        if not status.get("has_boundary"):
            return (
                "No farm boundary saved yet. Use set_field_boundary_from_location with a place name, "
                "or tell the farmer to draw the outline on Maps."
            )
        result = data_download_service.fetch_and_build_farm(farm_id)
        if not result.get("ok"):
            return f"Setup failed: {result.get('error')}"
        sources = result.get("sources") or []
        return (
            f"Downloaded and formatted real data for SWAT+: {', '.join(sources)}. "
            f"Built {result.get('hru_count', 0)} field zones (TxtInOut). "
            "Field model is ready for simulation."
        )

    @tool
    def get_field_data_provenance() -> dict:
        """Explain whether simulations use the uploaded SWAT+ project or online-downloaded data. Use when user asks if results are accurate."""
        from services import crop_service, file_ingest_service
        farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
        if not farm:
            return {"error": "Farm not found"}
        txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
        validation = pyswat_facade.validate_txtinout(txtinout)
        readiness = readiness_service.get_farm_readiness(farm_id)
        inbox = file_ingest_service.inspect_inbox(farm_id)
        hru_count = 0
        hru_path = txtinout / "hru-data.hru"
        if hru_path.exists():
            hru_count = sum(
                1 for ln in hru_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip() and not ln.strip().startswith("hru-data") and not ln.strip().startswith("id")
                and "|" in ln and ln.strip()[0].isdigit()
            )
        source = farm.get("data_source") or ""
        uploaded = readiness_service._is_complete_uploaded_project(farm, txtinout, validation)
        weather_in_txtinout = readiness_service._weather_ok(str(txtinout))
        return {
            "farm_name": farm.get("name"),
            "data_source": source,
            "uploaded_swat_project": uploaded,
            "weather_in_txtinout": weather_in_txtinout,
            "hru_count": hru_count,
            "ready_to_simulate": readiness.get("ready_to_simulate"),
            "inbox_has_swat_zip": (inbox.get("summary") or {}).get("has_complete_txtinout"),
            "crop": crop_service.get_crop_settings(farm_id),
            "note": (
                "Simulations use the SWAT+ TxtInOut on disk. If online download ran after upload, "
                "your original zip may have been replaced — re-import from inbox."
            ),
        }

    @tool
    def get_boundary_status() -> dict:
        """Check whether the farmer has drawn and saved a farm boundary on the map."""
        from services import data_download_service
        return data_download_service.get_boundary_status(farm_id)

    @tool
    def assess_field_data_and_confidence() -> dict:
        """Report what data this field has (source + quality), the calibration state, WHICH results
        can be produced now and AT WHAT CONFIDENCE (high/moderate/low/directional), and exactly what
        data the farmer should provide to improve accuracy. ALWAYS consult this BEFORE giving any
        numeric result, so you state honest confidence and never present uncalibrated absolute
        nitrate/nutrient/yield numbers as fact."""
        from services import confidence_service
        return confidence_service.assess_field_data_and_confidence(farm_id)

    @tool
    def run_calibration_check(
        variable: str = "streamflow",
        sim_file: str = "channel_sd_mon.txt",
        obs_file: str = "",
        sim_col: str = "flo_out",
        obs_col: str = "discharge",
    ) -> dict:
        """Compare the latest simulation against the farmer's uploaded MEASURED data and report model
        skill (NSE, PBIAS, KGE, R2). Records the calibration state so confidence reflects it. Use when
        the farmer has uploaded observed streamflow/water-quality data and wants to know how accurate
        the model is. If no measured data exists, it returns an instruction to upload it — never fake
        a calibration result."""
        from services import confidence_service, data_service, readiness_service

        last = readiness_service._last_completed_run(farm_id)
        if not last:
            return {"ok": False, "error": "No completed simulation yet. Run the model first, then calibrate."}

        obs = obs_file
        if not obs:
            inv = data_service.get_farm_data_inventory(farm_id)
            obs_candidates = [
                f for f in (inv.get("observed_files") or [])
                if not f.get("is_dir") and f.get("name") != confidence_service.CALIBRATION_FILE
            ]
            if not obs_candidates:
                return {
                    "ok": False,
                    "needs_data": True,
                    "message": "No measured data uploaded. To calibrate, the farmer should upload measured "
                               "monthly streamflow (discharge) — for their field or a nearby USGS gauge — as a "
                               "CSV with a date column and a value column. Then run this check again.",
                }
            obs = obs_candidates[0]["path"]

        indicators = ["NSE", "PBIAS", "KGE", "R2"]
        try:
            metrics = swat.compute_metrics(
                farm_id=farm_id,
                sim_file=sim_file,
                obs_file=obs,
                indicators=indicators,
                sim_col=sim_col,
                obs_col=obs_col,
                date_format="%Y-%m-%d",
                run_id=last.get("run_id"),
            )
        except Exception as exc:
            return {"ok": False, "error": f"Calibration check could not run: {exc}"}

        confidence_service.record_calibration(farm_id, variable, indicators, metrics, sim_file, obs)
        assessment = confidence_service.assess_field_data_and_confidence(farm_id)
        return {
            "ok": True,
            "variable": variable,
            "metrics": metrics,
            "calibration_state": assessment.get("calibration_state"),
            "confidence_after": confidence_service.output_confidence(assessment, "irrigation"),
            "streamflow_confidence": next(
                (o.get("confidence") for o in assessment.get("outputs", []) if o.get("id") == "streamflow"),
                None,
            ),
            "note": "Interpret NSE/PBIAS with Moriasi bands: NSE>0.5 and |PBIAS|<25 is satisfactory for "
                    "monthly streamflow. Report the numbers honestly to the farmer.",
        }

    # --- Generative-UI: thin no-op marker tools. They do NO work; they signal the
    # UI to render a widget. The farmer's answer returns as a normal message next turn.
    @tool
    def request_choice(question: str, options: list[str]) -> dict:
        """Show the farmer a set of tappable choice buttons instead of asking them to type.
        Use for short either/or or pick-one questions (2-5 options). The farmer's pick
        comes back to you as their next message."""
        opts = [{"id": str(i), "label": str(o)} for i, o in enumerate(options) if str(o).strip()]
        return {"__widget__": {"kind": "choice", "interactive": True, "placement": "canvas",
                               "title": question,
                               "payload": {"question": question, "options": opts, "multi": False}}}

    @tool
    def request_confirm(title: str, detail: str = "") -> dict:
        """Show a confirm/deny prompt before a notable action (create field, run a long
        model, overwrite data). Use instead of asking 'are you sure?' in prose."""
        return {"__widget__": {"kind": "confirm", "interactive": True, "placement": "canvas",
                               "title": title,
                               "payload": {"title": title, "detail": detail,
                                           "confirmLabel": "Yes, go ahead", "denyLabel": "No"}}}

    @tool
    def request_field_map(search_hint: str = "") -> dict:
        """Open an interactive MAP in the canvas so the farmer can find their location and DRAW
        their field boundary. Use this whenever you need the field's boundary/location and it is
        not set yet (setting up a new field, "set up my field", "draw my field"). search_hint is a
        place name/address/coords from the farmer's message to center the map on (optional).
        After they save, you'll get their boundary and can download data + build the model."""
        return {"__widget__": {"kind": "map-draw", "interactive": True, "placement": "canvas",
                               "title": "Draw your field boundary",
                               "prompt": "Search your location, click the corners of your field to outline it, then Save.",
                               "submit_label": "Save boundary",
                               "payload": {"mode": "draw", "searchHint": search_hint, "allowDownload": True}}}

    @tool
    def request_crop_form() -> dict:
        """Show a small form in the canvas for the farmer to set their crop type and planting date
        (required before yield estimates). Use instead of asking for crop/date in prose."""
        return {"__widget__": {"kind": "form", "interactive": True, "placement": "canvas",
                               "title": "Set your crop", "submit_label": "Save crop",
                               "payload": {"submit_action": "save_farm_crop_settings", "fields": [
                                   {"id": "crop_type", "type": "select", "label": "Crop", "required": True,
                                    "options": [{"value": c, "label": c.title()} for c in
                                                ("corn", "soybeans", "wheat", "cotton", "alfalfa", "sorghum", "barley")]},
                                   {"id": "planting_date", "type": "date", "label": "Planting date", "required": True},
                               ]}}}

    @tool
    def request_dataset_status() -> dict:
        """Show the farmer a visual checklist of what field data is ready vs still missing.
        Use when they ask what's set up / what's missing, or before setup steps."""
        readiness = readiness_service.get_farm_readiness(farm_id)
        return {"__widget__": {"kind": "checklist", "interactive": False, "placement": "canvas",
                               "title": "Field data checklist",
                               "payload": {"checks": readiness.get("checks", []), "showProgress": True}}}

    @tool
    def request_swat_editor(section: str = "run") -> dict:
        """Open the SWAT+ Editor panel in the canvas for manual control (parameters, print settings,
        run controls, crop, calibration). section: run | parameters | print | crop | calibration.
        Use when a power user wants to adjust the model directly (e.g. 'change CN2 and re-run')."""
        return {"__widget__": {"kind": "swat-editor-panel", "interactive": False, "placement": "canvas",
                               "title": "SWAT+ Editor", "payload": {"section": section}}}

    @tool
    def query_field_data(topic: str = "") -> dict:
        """Look up this field's model INPUTS and OUTPUTS so you can quote EXACT numbers:
        soil, crops, location, and the latest run's rainfall, irrigation, ET, nitrogen
        applied / taken up / leached, yield, N-use-efficiency, and crop-stress days — each with
        units. ALWAYS call this before stating any value; never guess or estimate. `topic`
        (optional) narrows it: water | nitrogen | yield | soil | crop | stress. Also returns
        `chartable_fields` (daily-series field names) to feed show_chart / show_table."""
        from services import field_data_service as fd
        snap = fd.snapshot(farm_id)
        vals = snap.get("values", {})
        groups = {
            "water": {"precip_mm", "irr_mm", "et_mm", "pet_mm", "perc_mm", "surq_mm", "latq_mm",
                      "sw_start", "sw_end", "sw_delta", "irrigation", "weather"},
            "nitrogen": {"fertn_kgha", "nuptake_kgha", "leached_kgha", "denit_kgha", "fixn_kgha", "nue_pct", "manure"},
            "yield": {"yield_kgha", "peak_bioms"}, "soil": {"soil"},
            "crop": {"crops", "period", "manure", "irrigation"},
            "stress": {"water_days", "n_days", "temp_days", "aeration_days"},
            "weather": {"weather", "precip_mm", "et_mm", "pet_mm"},
            "irrigation": {"irrigation", "irr_mm", "sw_start", "sw_end", "sw_delta"},
            "inputs": {"location", "soil", "crops", "manure", "irrigation", "weather", "period"},
        }
        t = (topic or "").lower().strip()
        if t in groups:
            keep = groups[t] | {"location", "soil", "crops", "period"}
            vals = {k: v for k, v in vals.items() if k in keep}
        return {"has_run": snap.get("has_run"),
                "period": f"{snap.get('start')} to {snap.get('end')}" if snap.get("start") else None,
                "values": vals, "chartable_fields": snap.get("chartable_fields", []),
                "note": None if snap.get("has_run") else "No completed run yet — run an analysis first; only inputs are available."}

    @tool
    def show_chart(title: str, fields: list[str], chart_type: str = "line", aggregate: str = "month") -> dict:
        """GENERATE a custom chart in the canvas from the run's daily data. Use whenever the
        farmer asks to see / plot / graph / compare values over time (e.g. 'plot soil moisture',
        'show nitrogen applied vs leached by year', 'chart rainfall and irrigation'). `fields` =
        one or more field names from query_field_data's chartable_fields (e.g. ['fertn','nuptake',
        'percn'] or ['precip','irr','et']). chart_type: line | bar | area. aggregate: day | month |
        year (use year for long runs). The chart is interactive (hover, toggle series, switch type)."""
        from services import field_data_service as fd
        data = fd.series(farm_id, list(fields or []), aggregate if aggregate in ("day", "month", "year") else "month")
        if not data.get("series") or not data.get("x"):
            return {"error": "No run data to chart yet — run an analysis first."}
        ct = chart_type if chart_type in ("line", "bar", "area") else "line"
        return {"__widget__": {"kind": "chart", "interactive": False, "placement": "canvas",
                               "title": title or "Chart",
                               "payload": {"variant": "custom", "chart_type": ct, "agg": data["agg"],
                                           "x": data["x"], "series": data["series"]}}}

    @tool
    def show_table(title: str, fields: list[str] | None = None, aggregate: str = "year",
                   columns: list[str] | None = None, rows: list | None = None) -> dict:
        """Show a sortable TABLE in the canvas. TWO ways to use it:
        (1) Run time-series: pass `fields` (from chartable_fields) + aggregate (month|year) for a
        period-by-period breakdown (e.g. 'table of yearly yield and nitrogen leached').
        (2) Values you already have: pass `columns` + `rows` directly to tabulate ANY comparison you
        assembled (e.g. a nitrogen budget, corn vs soybean). Use real numbers from your tools, never
        invented ones. (For the SOIL profile use show_soil_profile instead.)"""
        if columns and rows:
            return {"__widget__": {"kind": "table", "interactive": False, "placement": "canvas",
                                   "title": title or "Data table",
                                   "payload": {"columns": list(columns), "rows": list(rows), "sortable": True}}}
        from services import field_data_service as fd
        agg = aggregate if aggregate in ("month", "year") else "year"
        data = fd.series(farm_id, list(fields or []), agg)
        if not data.get("series") or not data.get("x"):
            return {"error": "No run data to tabulate yet — run an analysis first."}
        cols = ["Period"] + [s["label"] + (f" ({s['unit']})" if s["unit"] else "") for s in data["series"]]
        trows = [[x] + [s["data"][i] for s in data["series"]] for i, x in enumerate(data["x"])]
        return {"__widget__": {"kind": "table", "interactive": False, "placement": "canvas",
                               "title": title or "Data table",
                               "payload": {"columns": cols, "rows": trows, "sortable": True}}}

    @tool
    def show_soil_profile() -> dict:
        """Show the field's ACTUAL soil profile — layer-by-layer, read straight from its soils.sol —
        as a table in the canvas, and read the real numbers to answer the question. Use for ANY soil
        question (layers, texture, water-holding capacity, organic matter, bulk density, drainage, pH).
        Quote ONLY the values returned here; NEVER describe the soil from general knowledge."""
        from services import field_data_service as fd
        prof = fd.soil_profile(farm_id)
        if not prof.get("layers"):
            return {"error": "No soil file for this field yet — build the field model first."}
        cols = ["Layer", "Depth (cm)", "Bulk density (g/cm3)", "Avail. water (mm/mm)", "Ksat (mm/hr)",
                "Organic matter (%)", "Clay (%)", "Silt (%)", "Sand (%)", "pH", "CaCO3 (%)"]
        rows = [[f"L{i}", L["depth_cm"], L["bd"], L["awc"], L["ksat_mm_hr"], L["organic_matter_pct"],
                 L["clay_pct"], L["silt_pct"], L["sand_pct"], L["ph"], L["caco3_pct"]]
                for i, L in enumerate(prof["layers"], 1)]
        title = (f"Soil profile — {prof.get('display_name')} · {prof.get('n_layers')} layers "
                 f"· hydrologic group {prof.get('hyd_grp')}")
        return {"__widget__": {"kind": "table", "interactive": False, "placement": "canvas",
                               "title": title, "payload": {"columns": cols, "rows": rows, "sortable": True}},
                "soil_name": prof.get("display_name"), "hydrologic_group": prof.get("hyd_grp"),
                "total_depth_cm": round(prof.get("total_depth_mm", 0) / 10), "layers": prof["layers"]}

    return [
        request_choice,
        request_confirm,
        request_field_map,
        request_crop_form,
        request_dataset_status,
        request_swat_editor,
        query_field_data,
        show_chart,
        show_table,
        show_soil_profile,
        get_current_farm_info,
        check_farm_data_ready,
        get_farm_setup_guide,
        get_farm_crop_settings,
        save_farm_crop_settings,
        apply_crop_rotation,
        set_simulation_years,
        inspect_uploaded_field_files,
        import_uploaded_field_data_for_swat,
        setup_field_from_uploaded_files,
        get_field_dataset_status,
        get_field_data_provenance,
        assess_field_data_and_confidence,
        run_calibration_check,
        set_field_boundary_from_location,
        auto_setup_field_for_swat,
        get_boundary_status,
        load_demo_farm_data,
        fetch_online_map_data,
        get_latest_farm_insights,
        explain_last_simulation_results,
        run_irrigation_analysis,
        run_fertilizer_analysis,
        run_nitrate_analysis,
        run_yield_analysis,
        start_swat_simulation,
        wait_for_simulation,
        list_all_farms,
        create_new_field,
        copy_field_setup_from,
    ]
