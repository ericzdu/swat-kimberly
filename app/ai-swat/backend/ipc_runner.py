"""
AI-SWAT+ IPC Runner — Replaces FastAPI, communicates over stdio JSON-RPC.
All business logic is imported from existing backend modules.
"""
import sys
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from db import db_one, init_db, save_setting, get_setting, create_farm, get_farms, delete_farm
from services.llm_service import llm, PROVIDERS, PROVIDER_MODELS, PROVIDER_LABELS
from services.swat_service import swat
from services.chat_service import run_agent_chat
from services.gis_service import gis_service
from services.hru_generator import hru_generator, export_txtinout
from services.map_viewer import map_html, hru_map_html


def send_response(req_id, result):
    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def send_error(req_id, code, message):
    response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def handle_request(req):
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    try:
        if method == "ping":
            send_response(req_id, {"pong": True})

        # ---- Chat (LangGraph Agent) ----
        elif method == "chat.send":
            result = run_agent_chat(
                farm_id=params.get("farm_id", ""),
                message=params["message"],
                provider=params.get("provider"),
                model=params.get("model"),
                session_id=params.get("session_id"),
            )
            send_response(req_id, result)

        # ---- Simulation (keep as-is, used by React if needed) ----
        elif method == "sim.create":
            farm = db_one("SELECT * FROM farms WHERE id = ?", (params["farm_id"],))
            if not farm:
                send_error(req_id, -32000, "Farm not found")
                return
            result = swat.create(
                farm_id=params["farm_id"],
                txtinout_path=farm.get("txtinout_path") or "",
                sim_type=params.get("simulation_type", "irrigation"),
                params=params.get("parameters", {}),
                begin_date=params.get("begin_date", "01-Jan-2024"),
                end_date=params.get("end_date", "31-Dec-2024"),
            )
            send_response(req_id, {"simulation_id": result.job_id, "status": result.status})

        elif method == "sim.status":
            send_response(req_id, swat.status(params["simulation_id"]))

        # ---- System ----
        elif method == "system.providers":
            ollama_models = llm.get_ollama_models()
            result_out = []
            for p in PROVIDERS:
                models = []
                if p == "ollama":
                    models = [m["name"] for m in ollama_models]
                else:
                    models = PROVIDER_MODELS.get(p, [])
                has_key = bool(get_setting(f"api_key_{p}", ""))
                result_out.append({"id": p, "label": PROVIDER_LABELS[p], "models": models, "has_api_key": has_key})
            send_response(req_id, result_out)

        elif method == "system.health":
            send_response(req_id, llm.health())

        elif method == "system.test":
            result_out = llm.test_provider(params["provider"], params.get("model", ""))
            send_response(req_id, result_out)

        elif method == "system.getSettings":
            send_response(req_id, {
                "provider": get_setting("provider", "ollama"),
                "model": get_setting("model", ""),
            })

        elif method == "system.saveSettings":
            save_setting("provider", params["provider"])
            save_setting("model", params["model"])
            send_response(req_id, {"ok": True})

        elif method == "system.saveKeys":
            for k, v in params.items():
                if v:
                    save_setting(f"api_key_{k}", v)
            send_response(req_id, {"ok": True})

        # ---- Farms (passthrough, no LLM needed) ----
        elif method == "farms.list":
            send_response(req_id, get_farms())

        elif method == "farms.create":
            farm = create_farm(
                name=params["name"],
                location=params.get("location", ""),
                soil_type=params.get("soil_type", ""),
                txtinout_path=params.get("txtinout_path", ""),
            )
            send_response(req_id, farm)

        elif method == "farms.delete":
            delete_farm(params["farm_id"])
            send_response(req_id, {"ok": True})

        elif method == "data.inboxUpload":
            import base64
            from services import file_ingest_service
            farm_id = params.get("farm_id", "")
            farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
            if not farm:
                send_error(req_id, -32000, "Farm not found")
                return
            filename = params.get("filename") or "upload.bin"
            content_b64 = params.get("content_b64") or ""
            try:
                content = base64.b64decode(content_b64)
            except Exception as exc:
                send_error(req_id, -32000, f"Invalid file data: {exc}")
                return
            result = file_ingest_service.save_upload_to_inbox(farm_id, filename, content)
            send_response(req_id, result)

        # ---- GIS (passthrough, no LLM needed) ----
        elif method == "gis.upload":
            # Handled in agent via upload_gis_files tool — but also exposed directly
            send_response(req_id, {
                "message": "Use chat to upload GIS files: 'upload my DEM file'",
                "geojson": None,
            })

        elif method == "gis.generateHrus":
            result_out = hru_generator.generate(
                gis_service,
                lu_threshold=params.get("lu_threshold", 1.0),
                soil_threshold=params.get("soil_threshold", 1.0),
            )
            if result_out.success:
                send_response(req_id, {"success": True, "hru_count": result_out.hru_count, "geojson": result_out.geojson})
            else:
                send_response(req_id, {"success": False, "error": result_out.error})

        elif method == "gis.export":
            output_path = params.get("output_path", "")
            if hru_generator.hru_gdf is None or len(hru_generator.hru_gdf) == 0:
                send_error(req_id, -32000, "Generate HRUs first")
                return
            try:
                created = export_txtinout(hru_generator.hru_gdf, output_path)
                send_response(req_id, {"success": True, "files": list(created.keys())})
            except Exception as e:
                send_error(req_id, -32000, str(e))

        elif method == "gis.mapHtml":
            html = map_html(gis_service)
            send_response(req_id, html)

        elif method == "gis.hruMapHtml":
            html = hru_map_html(hru_generator.hru_gdf, center=gis_service.data.center)
            send_response(req_id, html)

        elif method == "gis.gisStatus":
            data = gis_service.data
            send_response(req_id, {
                "has_dem": data.dem is not None,
                "has_soil": data.soil is not None,
                "has_landuse": data.landuse is not None,
                "has_watershed": data.watershed is not None,
                "has_hrus": hru_generator.hru_gdf is not None and len(hru_generator.hru_gdf) > 0,
                "hru_count": len(hru_generator.hru_gdf) if hru_generator.hru_gdf is not None else 0,
                "center": data.center,
            })

        else:
            send_error(req_id, -32601, f"Method not found: {method}")

    except Exception as e:
        logger.exception(f"Error handling {method}")
        send_error(req_id, -32603, str(e))


def main():
    init_db()
    logger.info("IPC runner started, listening on stdin")

    buffer = ''
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            handle_request(req)
        except json.JSONDecodeError:
            sys.stderr.write(f"non-json-input: {line[:200]}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
