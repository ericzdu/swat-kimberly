"""
LangGraph Tools — All farm operations exposed as tool-callable functions.
"""
import time
import tempfile
import os
import base64
import json
import logging
from typing import Optional

from langchain_core.tools import tool

from db import (
    db_one, save_setting, get_setting,
    create_farm, get_farms, delete_farm,
)
from services.swat_service import swat
from services.gis_service import gis_service
from services.hru_generator import hru_generator, export_txtinout

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Farm Tools
# ---------------------------------------------------------------------------

@tool
def list_farms() -> list[dict]:
    """Return all farms. Use this to find a farm by name or get farm IDs."""
    return get_farms()


@tool
def create_farm_tool(
    name: str,
    location: str = "",
    soil_type: str = "",
    txtinout_path: str = "",
) -> dict:
    """Create a new farm. Returns the created farm record."""
    if not name.strip():
        return {"error": "Farm name is required"}
    return create_farm(name=name, location=location, soil_type=soil_type, txtinout_path=txtinout_path)


@tool
def delete_farm_tool(farm_id: str) -> dict:
    """Delete a farm by its ID."""
    delete_farm(farm_id)
    return {"ok": True, "farm_id": farm_id}


@tool
def get_farm_context(farm_id: str) -> dict:
    """Get full context for a farm: name, location, soil type, TxtInOut path."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"error": f"Farm {farm_id} not found"}
    return farm


@tool
def find_farm_by_name(name: str) -> dict:
    """Find a farm by name (partial match). Returns farm_id and name."""
    farms = get_farms()
    matches = [f for f in farms if name.lower() in f.get("name", "").lower()]
    if not matches:
        return {"error": f"No farm found matching '{name}'"}
    if len(matches) == 1:
        return matches[0]
    return {"farms": matches, "message": f"Multiple farms match '{name}': {', '.join(f['name'] for f in matches)}"}


# ---------------------------------------------------------------------------
# Simulation Tools
# ---------------------------------------------------------------------------

@tool
def run_simulation(
    farm_id: str,
    sim_type: str = "irrigation",
    begin_date: str = "01-Jan-2024",
    end_date: str = "31-Dec-2024",
) -> str:
    """Start a SWAT+ simulation. Returns the simulation_id — use poll_simulation to get results."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return f"ERROR: Farm {farm_id} not found"
    result = swat.create(
        farm_id=farm_id,
        txtinout_path=farm.get("txtinout_path") or "",
        sim_type=sim_type,
        params={},
        begin_date=begin_date,
        end_date=end_date,
    )
    return result.job_id


@tool
def poll_simulation(sim_id: str, max_wait: int = 45) -> dict:
    """Poll a simulation until it completes or fails. Returns full output summary with water_balance, nutrient_balance, yield_kgha."""
    for i in range(max_wait // 3):
        status = swat.status(sim_id)
        s = status.get("status", "")
        if s == "completed":
            return status
        if s == "failed":
            return {"error": status.get("error", "Simulation failed")}
        time.sleep(3)
    return {"error": "Simulation timed out", "simulation_id": sim_id}


@tool
def interpret_irrigation_results(output: dict) -> str:
    """Given simulation output, produce a farmer-ready irrigation recommendation."""
    from services.insights_service import interpret_irrigation
    i = interpret_irrigation(output)
    wb = output.get("water_balance", {})
    return (
        f"**Irrigation Analysis**\n\n"
        f"- Precipitation: {wb.get('precip_mm', 0):.0f} mm\n"
        f"- Evapotranspiration: {wb.get('et_mm', 0):.0f} mm\n"
        f"- Runoff: {wb.get('runoff_mm', 0):.0f} mm\n"
        f"- Deep Percolation: {wb.get('deep_perc_mm', 0):.0f} mm\n"
        f"- Soil Moisture: {wb.get('soil_moisture_mm', 0):.0f} mm\n\n"
        f"**Recommendation: {i['headline']}**"
    )


@tool
def interpret_fertilizer_results(output: dict) -> str:
    """Given simulation output, produce a farmer-ready fertilizer recommendation."""
    from services.insights_service import interpret_fertilizer
    i = interpret_fertilizer(output)
    nb = output.get("nutrient_balance", {})
    return (
        f"**Nutrient Balance**\n\n"
        f"- Nitrogen (N): {nb.get('nitrogen_kgha', 0):.0f} kg/ha\n"
        f"- Phosphorus (P): {nb.get('phosphorus_kgha', 0):.0f} kg/ha\n\n"
        f"**{i['advice']}**"
    )


@tool
def interpret_yield_results(output: dict) -> str:
    """Given simulation output, produce a yield projection."""
    from services.insights_service import interpret_yield
    i = interpret_yield(output)
    return f"**Yield Projection**\n\n**{i['headline']}**\n\n{i['detail']}"


# ---------------------------------------------------------------------------
# GIS / HRU Tools
# ---------------------------------------------------------------------------

@tool
def upload_gis_files(
    dem: Optional[str] = None,
    soil: Optional[str] = None,
    landuse: Optional[str] = None,
    watershed: Optional[str] = None,
) -> dict:
    """Load GIS files from base64-encoded bytes.

    Args:
        dem: DEM GeoTIFF as base64 string (optional)
        soil: Soil shapefile as base64 string (optional)
        landuse: Land use GeoTIFF as base64 string (optional)
        watershed: Watershed shapefile as base64 string (optional)

    Returns:
        dict with message summary and geojson of loaded layers
    """
    tmp_paths = {}

    def decode_file(data_b64: Optional[str], suffix: str) -> Optional[str]:
        if not data_b64:
            return None
        try:
            bytes_data = base64.b64decode(data_b64)
            fd, path = tempfile.mkstemp(suffix=suffix)
            os.write(fd, bytes_data)
            os.close(fd)
            tmp_paths[suffix] = path
            return path
        except Exception as e:
            logger.warning(f"Failed to decode GIS file: {e}")
            return None

    dem_path = decode_file(dem, ".tif")
    soil_path = decode_file(soil, ".shp")
    landuse_path = decode_file(landuse, ".tif")
    watershed_path = decode_file(watershed, ".shp")

    status_parts = []
    geojson = None

    try:
        if dem_path:
            from services.gis_service import load_geotiff
            data, transform, bounds, crs = load_geotiff(dem_path)
            gis_service.data.dem = data
            gis_service.data.dem_transform = transform
            gis_service.data.dem_bounds = bounds
            gis_service.data.crs = crs
            status_parts.append(f"DEM: {data.shape}")

        if soil_path:
            from services.gis_service import load_shapefile
            gdf = load_shapefile(soil_path)
            gis_service.data.soil = gdf
            status_parts.append(f"Soil: {len(gdf)} polygons")

        if landuse_path:
            from services.gis_service import load_geotiff
            data, transform, bounds, crs = load_geotiff(landuse_path)
            gis_service.data.landuse = data
            gis_service.data.landuse_transform = transform
            gis_service.data.landuse_crs = crs
            status_parts.append(f"Landuse: {data.shape}")

        if watershed_path:
            from services.gis_service import load_shapefile
            gdf = load_shapefile(watershed_path)
            gis_service.data.watershed = gdf
            status_parts.append(f"Watershed: {len(gdf)} polygons")

        if gis_service.data.dem_bounds:
            b = gis_service.data.dem_bounds
            gis_service.data.center = ((b[1] + b[3]) / 2, (b[0] + b[2]) / 2)

        if gis_service.data.soil is not None:
            try:
                geojson = json.loads(gis_service.data.soil.to_json())
            except Exception:
                pass

    finally:
        for path in tmp_paths.values():
            try:
                os.unlink(path)
            except Exception:
                pass

    return {
        "message": "; ".join(status_parts) if status_parts else "No data loaded",
        "geojson": geojson,
    }


@tool
def generate_hrus_tool(
    lu_threshold: float = 1.0,
    soil_threshold: float = 1.0,
) -> dict:
    """Generate HRUs from currently loaded GIS data (DEM + soil + land use must be loaded first via upload_gis_files)."""
    result = hru_generator.generate(
        gis_service,
        lu_threshold=lu_threshold,
        soil_threshold=soil_threshold,
    )
    if result.success:
        return {
            "success": True,
            "hru_count": result.hru_count,
            "geojson": result.geojson,
        }
    return {"success": False, "error": result.error}


@tool
def export_txtinout_tool(output_dir: str) -> dict:
    """Export generated HRUs to a TxtInOut folder. Run generate_hrus_tool first."""
    if hru_generator.hru_gdf is None or len(hru_generator.hru_gdf) == 0:
        return {"success": False, "error": "Generate HRUs first"}
    try:
        created = export_txtinout(hru_generator.hru_gdf, output_dir)
        return {"success": True, "files": list(created.keys())}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_gis_status() -> dict:
    """Return what's currently loaded in GIS service: DEM, soil, landuse, watershed."""
    data = gis_service.data
    return {
        "has_dem": data.dem is not None,
        "has_soil": data.soil is not None,
        "has_landuse": data.landuse is not None,
        "has_watershed": data.watershed is not None,
        "has_hrus": hru_generator.hru_gdf is not None and len(hru_generator.hru_gdf) > 0,
        "hru_count": len(hru_generator.hru_gdf) if hru_generator.hru_gdf is not None else 0,
        "center": data.center,
    }


# ---------------------------------------------------------------------------
# System / Settings Tools
# ---------------------------------------------------------------------------

@tool
def get_system_status() -> dict:
    """Get health status of all LLM providers."""
    from services.llm_service import provider_health
    return provider_health()


@tool
def get_provider_models(provider: str) -> list[str]:
    """Get available models for a provider."""
    from services.llm_service import PROVIDER_MODELS, list_ollama_models
    if provider == "ollama":
        return [m["name"] for m in list_ollama_models()]
    return PROVIDER_MODELS.get(provider, [])


@tool
def save_api_keys(
    groq: str = "",
    openai: str = "",
    anthropic: str = "",
    openrouter: str = "",
    minimax: str = "",
) -> dict:
    """Save API keys for LLM providers. Only non-empty values overwrite existing keys."""
    keys = {"groq": groq, "openai": openai, "anthropic": anthropic, "openrouter": openrouter, "minimax": minimax}
    for k, v in keys.items():
        if v:
            save_setting(f"api_key_{k}", v)
    return {"ok": True}


@tool
def get_saved_settings() -> dict:
    """Get current provider and model settings."""
    return {
        "provider": get_setting("provider", "ollama"),
        "model": get_setting("model", ""),
    }


@tool
def save_settings(provider: str, model: str) -> dict:
    """Save the active LLM provider and model."""
    save_setting("provider", provider)
    save_setting("model", model)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Tool List (for binding)
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    list_farms,
    create_farm_tool,
    delete_farm_tool,
    get_farm_context,
    find_farm_by_name,
    run_simulation,
    poll_simulation,
    interpret_irrigation_results,
    interpret_fertilizer_results,
    interpret_yield_results,
    upload_gis_files,
    generate_hrus_tool,
    export_txtinout_tool,
    get_gis_status,
    get_system_status,
    get_provider_models,
    save_api_keys,
    get_saved_settings,
    save_settings,
]
