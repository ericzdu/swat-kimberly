"""GIS upload, HRU generation, and TxtInOut export routes."""
import json
import os
import tempfile

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/gis", tags=["gis"])


class HruParams(BaseModel):
    lu_threshold: float = 1.0
    soil_threshold: float = 1.0
    slope_classes: str = ""


@router.post("/upload")
async def gis_upload(
    dem: UploadFile = File(None),
    soil: UploadFile = File(None),
    landuse: UploadFile = File(None),
    watershed: UploadFile = File(None),
):
    from services.gis_service import gis_service, load_geotiff, load_shapefile

    status_parts = []
    geojson = None

    try:
        if dem:
            with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
                f.write(await dem.read())
                tmp_path = f.name
            try:
                data, transform, bounds, crs = load_geotiff(tmp_path)
                gis_service.data.dem = data
                gis_service.data.dem_transform = transform
                gis_service.data.dem_bounds = bounds
                gis_service.data.crs = crs
                status_parts.append(f"DEM: {data.shape}, {bounds}")
            finally:
                os.unlink(tmp_path)

        if soil:
            with tempfile.NamedTemporaryFile(suffix=".shp", delete=False) as f:
                f.write(await soil.read())
                tmp_path = f.name
            try:
                gdf = load_shapefile(tmp_path)
                gis_service.data.soil = gdf
                status_parts.append(f"Soil: {len(gdf)} polygons")
            finally:
                os.unlink(tmp_path)

        if landuse:
            with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
                f.write(await landuse.read())
                tmp_path = f.name
            try:
                data, transform, bounds, crs = load_geotiff(tmp_path)
                gis_service.data.landuse = data
                gis_service.data.landuse_transform = transform
                gis_service.data.landuse_crs = crs
                status_parts.append(f"Landuse: {data.shape}")
            finally:
                os.unlink(tmp_path)

        if watershed:
            with tempfile.NamedTemporaryFile(suffix=".shp", delete=False) as f:
                f.write(await watershed.read())
                tmp_path = f.name
            try:
                gdf = load_shapefile(tmp_path)
                gis_service.data.watershed = gdf
                status_parts.append(f"Watershed: {len(gdf)} polygons")
            finally:
                os.unlink(tmp_path)

        if gis_service.data.dem_bounds:
            b = gis_service.data.dem_bounds
            gis_service.data.center = ((b.top + b.bottom) / 2, (b.left + b.right) / 2)

        if gis_service.data.soil is not None:
            try:
                geojson = json.loads(gis_service.data.soil.to_json())
            except Exception:
                pass

    except Exception as exc:
        return {"message": f"Error: {exc}", "geojson": None}

    return {
        "message": "; ".join(status_parts) if status_parts else "No data loaded",
        "geojson": geojson,
    }


@router.post("/generate_hrus")
def gis_generate_hrus(params: HruParams):
    from services.gis_service import gis_service
    from services.hru_generator import hru_generator

    try:
        result = hru_generator.generate(
            gis_service,
            lu_threshold=params.lu_threshold,
            soil_threshold=params.soil_threshold,
        )
        if result.success:
            return {"success": True, "hru_count": result.hru_count, "geojson": result.geojson}
        return {"success": False, "error": result.error}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/export")
def gis_export(body: dict):
    from services.hru_generator import export_txtinout, hru_generator

    output_path = body.get("output_path", "")
    try:
        if hru_generator.hru_gdf is None or len(hru_generator.hru_gdf) == 0:
            return {"success": False, "error": "Generate HRUs first"}
        created = export_txtinout(hru_generator.hru_gdf, output_path)
        return {"success": True, "files": list(created.keys())}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/geocode")
def geocode_place(q: str = "", limit: int = 6):
    """Search places by name (proxies OpenStreetMap Nominatim)."""
    import json
    import re
    import urllib.parse
    import urllib.request

    query = (q or "").strip()
    if not query:
        return {"results": [], "error": "Enter a place name or coordinates"}

    # Coordinate patterns: "39.8, -98.5" or "39.8 -98.5"
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
            return {"results": [], "error": "Coordinates out of range (lat -90..90, lon -180..180)"}
        return {
            "results": [{
                "lat": lat,
                "lon": lon,
                "label": f"Coordinates {lat:.5f}, {lon:.5f}",
                "kind": "coordinates",
            }],
        }

    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": min(limit, 10)})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AI-SWAT+/1.0 (farm maps)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"results": [], "error": str(exc)}

    results = [
        {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "label": item.get("display_name", query),
            "kind": item.get("type", "place"),
        }
        for item in data
    ]
    return {"results": results}
