"""Download DEM, soil, and weather for a farm boundary from public web APIs."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.transform import from_bounds
from shapely.geometry import mapping, shape

import config
import shutil
from db import db_exec
from services import pyswat_facade
from services.gis_service import compute_slope, gis_service, load_geotiff
from services.hru_generator import export_txtinout, hru_generator
from services.swat_weather import apply_openmeteo_to_txtinout
from utils.text import safe_text

logger = logging.getLogger(__name__)

MANIFEST_NAME = "data_manifest.json"
BOUNDARY_NAME = "boundary.geojson"

# Demo template files we copy — never copy weather from another location.
SWAT_TEMPLATE_SKIP = {
    "hru-data.hru", "fig.dat", "sol.dat", "lu.dat", "mgt.dat", "bsn",
    "routing.unit", "precip.dat", "temp.dat",
    "pcp.cli", "tmp.cli", "weather-sta.cli", "weather-wgn.cli",
    "tfccpcp.pcp", "tfcctmp.tem", "time.sim", "farm_weather.pcp", "farm_weather.tem",
    ".weather_source",
}
SWAT_TEMPLATE_SKIP_DIRS = {"wgn", "output", "SWIFT"}
DEM_NAME = "dem.tif"
SOIL_NAME = "soil.geojson"
LANDUSE_NAME = "landuse.tif"
WEATHER_NAME = "weather_openmeteo.json"


def _http_json(url: str, timeout: int = 20, retries: int = 1) -> dict:
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-SWAT+/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _http_post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "AI-SWAT+/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_boundary(farm_id: str, geojson: dict) -> dict[str, Any]:
    gis_dir = config.farm_gis_dir(farm_id)
    gis_dir.mkdir(parents=True, exist_ok=True)
    path = gis_dir / BOUNDARY_NAME
    path.write_text(json.dumps(geojson), encoding="utf-8")
    gdf = gpd.GeoDataFrame.from_features(geojson.get("features", [geojson]), crs="EPSG:4326")
    bounds = gdf.total_bounds.tolist()
    center = ((bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2)
    return {
        "ok": True,
        "path": str(path),
        "bounds": {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]},
        "center": {"lat": center[0], "lon": center[1]},
        "area_ha": float(gdf.to_crs(3857).area.sum() / 10000),
    }


def load_boundary(farm_id: str) -> Optional[dict]:
    path = config.farm_gis_dir(farm_id) / BOUNDARY_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_boundary_status(farm_id: str) -> dict[str, Any]:
    geojson = load_boundary(farm_id)
    if not geojson:
        return {"has_boundary": False, "message": "No farm boundary saved yet."}
    gdf = gpd.GeoDataFrame.from_features(geojson.get("features", []), crs="EPSG:4326")
    bounds = gdf.total_bounds
    return {
        "has_boundary": True,
        "bounds": {
            "west": float(bounds[0]),
            "south": float(bounds[1]),
            "east": float(bounds[2]),
            "north": float(bounds[3]),
        },
        "area_ha": float(gdf.to_crs(3857).area.sum() / 10000),
    }


def _fetch_dem_opentopo(bounds: tuple, out_path: Path) -> bool:
    api_key = os.environ.get("OPENTOPOGRAPHY_API_KEY", "").strip()
    if not api_key:
        return False
    west, south, east, north = bounds
    params = urllib.parse.urlencode({
        "demtype": "SRTMGL1",
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    })
    url = f"https://portal.opentopography.org/API/globaldem?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AI-SWAT+/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out_path.write_bytes(resp.read())
    return out_path.exists() and out_path.stat().st_size > 1000


def _write_dem_grid(bounds: tuple, out_path: Path, elevations: list[float], grid: int) -> None:
    west, south, east, north = bounds
    if len(elevations) != grid * grid:
        raise ValueError(f"Expected {grid * grid} elevations, got {len(elevations)}")
    arr = np.array(elevations, dtype=np.float32).reshape(grid, grid)
    transform = from_bounds(west, south, east, north, grid, grid)
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=grid,
        width=grid,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(arr, 1)


def _fetch_dem_open_meteo(bounds: tuple, out_path: Path, grid: int = 10) -> bool:
    """Real elevation from Copernicus DEM 2021 via Open-Meteo (no API key)."""
    west, south, east, north = bounds
    lats = np.linspace(south, north, grid)
    lons = np.linspace(west, east, grid)
    lat_list = [float(lat) for lat in lats for lon in lons]
    lon_list = [float(lon) for lat in lats for lon in lons]

    elevations: list[float] = []
    chunk = 100
    try:
        for i in range(0, len(lat_list), chunk):
            lat_batch = lat_list[i:i + chunk]
            lon_batch = lon_list[i:i + chunk]
            params = urllib.parse.urlencode({
                "latitude": ",".join(f"{x:.6f}" for x in lat_batch),
                "longitude": ",".join(f"{x:.6f}" for x in lon_batch),
            })
            url = f"https://api.open-meteo.com/v1/elevation?{params}"
            data = _http_json(url, timeout=45)
            batch_ele = data.get("elevation")
            if not batch_ele or len(batch_ele) != len(lat_batch):
                return False
            elevations.extend(float(e) for e in batch_ele)
        _write_dem_grid(bounds, out_path, elevations, grid)
        return out_path.exists() and out_path.stat().st_size > 100
    except Exception as exc:
        logger.warning("Open-Meteo elevation failed: %s", exc)
        return False


def _fetch_dem_required(bounds: tuple, out_path: Path) -> str:
    """Download real elevation — fail if no API succeeds."""
    if _fetch_dem_opentopo(bounds, out_path):
        return "OpenTopography SRTM (30 m)"
    if _fetch_dem_open_meteo(bounds, out_path, grid=10):
        return "Open-Meteo Copernicus DEM (90 m)"
    if _fetch_dem_open_elevation(bounds, out_path, grid=10):
        return "Open-Elevation API"
    raise RuntimeError(
        "Could not download elevation for your area. Check your internet connection and try again. "
        "Optional: set OPENTOPOGRAPHY_API_KEY for higher-resolution SRTM (free at opentopography.org)."
    )


def _fetch_dem_open_elevation(bounds: tuple, out_path: Path, grid: int = 12) -> bool:
    west, south, east, north = bounds
    lats = np.linspace(south, north, grid)
    lons = np.linspace(west, east, grid)
    locations = [
        {"latitude": float(lat), "longitude": float(lon)}
        for lat in lats for lon in lons
    ]
    elevations: list[float] = []
    chunk = 50
    try:
        for i in range(0, len(locations), chunk):
            batch = locations[i:i + chunk]
            data = _http_post_json(
                "https://api.open-elevation.com/api/v1/lookup",
                {"locations": batch},
                timeout=20,
            )
            elevations.extend(float(r.get("elevation", 0)) for r in data.get("results", []))
    except Exception as exc:
        logger.warning("Open-Elevation failed: %s", exc)
        return False

    if len(elevations) != grid * grid:
        return False

    _write_dem_grid(bounds, out_path, elevations, grid)
    return True


def _fetch_soilgrids(bounds: tuple, out_path: Path) -> str:
    west, south, east, north = bounds
    lon = (west + east) / 2
    lat = (south + north) / 2
    url = (
        "https://rest.isric.org/soilgrids/v2.0/properties/query?"
        f"lon={lon}&lat={lat}&property=clay&depth=0-5cm&value=mean"
    )
    data = _http_json(url, timeout=45, retries=3)
    clay_val = (
        data.get("properties", {}).get("layers", [{}])[0]
        .get("depths", [{}])[0].get("values", {}).get("mean")
    )
    if clay_val is None:
        raise ValueError("SoilGrids returned no clay data for this location.")
    clay = float(clay_val)
    if clay > 35:
        soil_label = "Clay"
    elif clay < 15:
        soil_label = "Sand"
    else:
        soil_label = "Loam"

    poly = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "SOIL_ID": soil_label,
                "soil": soil_label,
                "source": "SoilGrids/ISRIC",
                "clay_pct": clay,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south], [east, north], [west, north], [west, south],
                ]],
            },
        }],
    }
    out_path.write_text(json.dumps(poly), encoding="utf-8")
    return soil_label


def _create_landuse_from_boundary(gdf: gpd.GeoDataFrame, dem_path: Path, out_path: Path) -> None:
    """Rasterize the user-drawn field boundary as cropland (NLCD 82)."""
    with rasterio.open(dem_path) as src:
        grid = (src.height, src.width)
        transform = src.transform
        crs = src.crs
    gdf_proj = gdf.to_crs(crs)
    shapes = [(geom, 82) for geom in gdf_proj.geometry if geom and not geom.is_empty]
    if not shapes:
        raise ValueError("Farm boundary geometry is empty.")
    arr = rio_features.rasterize(
        shapes,
        out_shape=grid,
        transform=transform,
        fill=0,
        dtype=np.int16,
    )
    if not np.any(arr):
        raise ValueError("Land use raster is empty — check your farm boundary.")
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=grid[0],
        width=grid[1],
        count=1,
        dtype="int16",
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(arr, 1)


def _dem_mean_elevation(dem_path: Path) -> float:
    with rasterio.open(dem_path) as src:
        data = src.read(1, masked=True)
    if data.count() == 0:
        raise ValueError("DEM has no valid elevation values.")
    return float(np.ma.mean(data))


def _write_data_manifest(gis_dir: Path, sources: list[str], center: tuple[float, float]) -> None:
    manifest = {
        "verified": True,
        "sources": sources,
        "center_lat": center[0],
        "center_lon": center[1],
    }
    (gis_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _fetch_weather(lat: float, lon: float, out_path: Path) -> dict:
    url = (
        "https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        "&start_date=2020-01-01&end_date=2024-12-31"
        "&daily=precipitation_sum,temperature_2m_max,temperature_2m_min"
        "&timezone=auto"
    )
    data = _http_json(url, timeout=60)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    daily = data.get("daily", {})
    precip = daily.get("precipitation_sum", [])
    return {
        "source": "Open-Meteo",
        "days": len(precip),
        "total_precip_mm": float(sum(p for p in precip if p is not None)),
    }


def fetch_online_data(farm_id: str) -> dict[str, Any]:
    boundary = load_boundary(farm_id)
    if not boundary:
        return {
            "ok": False,
            "error": "No farm boundary saved. Open Maps, draw your field outline, and click Save boundary.",
        }

    gdf = gpd.GeoDataFrame.from_features(boundary.get("features", []), crs="EPSG:4326")
    if gdf.empty:
        return {"ok": False, "error": "Boundary is empty. Draw at least 3 points on the map."}

    bounds = tuple(gdf.total_bounds)
    west, south, east, north = bounds
    if east - west < 0.0005 or north - south < 0.0005:
        return {"ok": False, "error": "Boundary is too small. Zoom in and draw a larger area."}

    gis_dir = config.farm_gis_dir(farm_id)
    gis_dir.mkdir(parents=True, exist_ok=True)
    dem_path = gis_dir / DEM_NAME
    soil_path = gis_dir / SOIL_NAME
    lu_path = gis_dir / LANDUSE_NAME
    weather_path = gis_dir / WEATHER_NAME
    watershed_path = gis_dir / "watershed.geojson"

    sources: list[str] = []
    try:
        dem_source = _fetch_dem_required(bounds, dem_path)
        sources.append(dem_source)
    except Exception as exc:
        return {"ok": False, "error": safe_text(str(exc))}

    try:
        soil_label = _fetch_soilgrids(bounds, soil_path)
        sources.append(f"SoilGrids/ISRIC ({soil_label})")
    except Exception as exc:
        return {"ok": False, "error": safe_text(f"Could not download soil data from SoilGrids: {exc}")}

    try:
        _create_landuse_from_boundary(gdf, dem_path, lu_path)
        sources.append("Land use from saved farm boundary (cropland)")
    except Exception as exc:
        return {"ok": False, "error": safe_text(f"Could not build land use layer: {exc}")}

    center_lat = (south + north) / 2
    center_lon = (west + east) / 2
    try:
        weather_summary = _fetch_weather(center_lat, center_lon, weather_path)
        if weather_summary.get("days", 0) < 30:
            raise ValueError("Weather archive returned too few days.")
        sources.append("Open-Meteo (daily weather archive)")
    except Exception as exc:
        return {"ok": False, "error": safe_text(f"Could not download weather from Open-Meteo: {exc}")}

    gdf.to_file(watershed_path, driver="GeoJSON")
    _write_data_manifest(gis_dir, sources, (center_lat, center_lon))

    return {
        "ok": True,
        "farm_id": farm_id,
        "soil_type": soil_label,
        "weather": weather_summary,
        "sources": sources,
        "files": {
            "dem": str(dem_path),
            "soil": str(soil_path),
            "landuse": str(lu_path),
            "watershed": str(watershed_path),
            "weather": str(weather_path),
        },
        "message": "Downloaded elevation, soil, land use, and weather for your farm area.",
    }


def _load_layers_into_gis(gis_dir: Path) -> list[str]:
    loaded: list[str] = []
    dem_path = gis_dir / DEM_NAME
    soil_path = gis_dir / SOIL_NAME
    lu_path = gis_dir / LANDUSE_NAME
    ws_path = gis_dir / "watershed.geojson"

    if dem_path.exists():
        data, transform, bounds, crs = load_geotiff(str(dem_path))
        gis_service.data.dem = data
        gis_service.data.dem_transform = transform
        gis_service.data.dem_bounds = bounds
        gis_service.data.crs = crs
        gis_service.data.slope = compute_slope(data, transform)
        gis_service.data.slope_transform = transform
        gis_service.data.center = ((bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2)
        loaded.append("dem")

    if soil_path.exists():
        gis_service.data.soil = gpd.read_file(soil_path)
        if gis_service.data.soil.crs:
            gis_service.data.soil = gis_service.data.soil.to_crs("EPSG:4326")
        loaded.append("soil")

    if lu_path.exists():
        data, transform, bounds, crs = load_geotiff(str(lu_path))
        gis_service.data.landuse = data
        gis_service.data.landuse_transform = transform
        gis_service.data.landuse_crs = crs
        loaded.append("landuse")

    if ws_path.exists():
        gis_service.data.watershed = gpd.read_file(ws_path)
        if gis_service.data.watershed.crs:
            gis_service.data.watershed = gis_service.data.watershed.to_crs("EPSG:4326")
        loaded.append("watershed")

    return loaded


def _copy_swat_support_templates(out_dir: Path) -> list[str]:
    """Copy structural SWAT+ templates only — never weather from another location."""
    demo = config.demo_txtinout_source()
    if not demo.is_dir():
        raise RuntimeError("SWAT+ template project missing — cannot build field model.")
    copied: list[str] = []
    for item in demo.iterdir():
        if item.name in SWAT_TEMPLATE_SKIP or item.name in SWAT_TEMPLATE_SKIP_DIRS:
            continue
        dest = out_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
            copied.append(item.name)
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
            copied.append(item.name + "/")
    return copied


def _upgrade_file_cio_to_rev62(out_dir: Path) -> bool:
    """Make a rev-61 file.cio readable by the rev-62 engine.

    Rev-62 added a 3rd `input_basin` component (carbon.bsn). Rev-61 editors write
    only 2 file tokens on the `basin` line (codes.bsn parameters.bsn). Rev-62's
    readcio_read under-fills `in_basin`, so its list-directed read spills onto the
    NEXT line and shifts every later token — corrupting the weather path fields
    (in_path_tmp) and crashing cli_tmeas (`ts` dim-2 = 0). Padding the basin line
    to 3 file tokens realigns the whole file. Idempotent.
    """
    cio = out_dir / "file.cio"
    if not cio.exists():
        return False
    lines = cio.read_text(encoding="utf-8", errors="replace").splitlines()
    changed = False
    for i, line in enumerate(lines):
        toks = line.split()
        if toks and toks[0] == "basin" and len(toks) < 4:
            # label + codes.bsn + parameters.bsn (+ carbon slot -> null)
            while len(toks) < 4:
                toks.append("null")
            lines[i] = f"{toks[0]:<18}{toks[1]:<18}{toks[2]:<18}{toks[3]:<18}"
            changed = True
            break
    if changed:
        cio.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def build_farm_model_from_downloads(farm_id: str) -> dict[str, Any]:
    gis_dir = config.farm_gis_dir(farm_id)
    manifest_path = gis_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": "No verified map download. Fetch online data first."}
    if not (gis_dir / DEM_NAME).exists():
        return {"ok": False, "error": "No downloaded map data. Fetch online data first."}
    weather_json = gis_dir / WEATHER_NAME
    if not weather_json.exists():
        return {"ok": False, "error": "Weather download missing. Re-run map data download."}

    loaded = _load_layers_into_gis(gis_dir)
    if "dem" not in loaded or "soil" not in loaded or "landuse" not in loaded:
        return {"ok": False, "error": "DEM, soil, or land use layer missing. Re-run fetch online data."}

    result = hru_generator.generate(gis_service, lu_threshold=0.001, soil_threshold=0.001)
    if not result.success:
        return {"ok": False, "error": result.error or "HRU generation failed"}

    out_dir = config.farm_txtinout_dir(farm_id)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_txtinout(hru_generator.hru_gdf, str(out_dir))
    try:
        support = _copy_swat_support_templates(out_dir)
    except Exception as exc:
        return {"ok": False, "error": safe_text(str(exc))}

    # The demo project is rev-61 format; the engine is rev-62. Upgrade file.cio so
    # the basin line has the rev-62 carbon.bsn slot (else weather reading crashes).
    _upgrade_file_cio_to_rev62(out_dir)

    boundary = load_boundary(farm_id)
    gdf = gpd.GeoDataFrame.from_features(boundary.get("features", []), crs="EPSG:4326")
    center_lat = float(gdf.geometry.centroid.y.iloc[0])
    center_lon = float(gdf.geometry.centroid.x.iloc[0])
    elev_m = _dem_mean_elevation(gis_dir / DEM_NAME)
    try:
        weather_info = apply_openmeteo_to_txtinout(
            weather_json, out_dir, center_lat, center_lon, elev_m,
        )
    except Exception as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        return {"ok": False, "error": safe_text(f"Could not write SWAT+ weather files: {exc}")}

    from services import crop_service
    crop_service.apply_saved_crop_to_txtinout(farm_id)

    db_exec(
        "UPDATE farms SET txtinout_path = ?, data_source = ? WHERE id = ?",
        (str(out_dir), "online_verified", farm_id),
    )

    validation = pyswat_facade.validate_txtinout(out_dir)
    return {
        "ok": bool(result.hru_count and validation.get("valid")),
        "hru_count": result.hru_count,
        "txtinout_path": str(out_dir),
        "validation": validation,
        "layers_loaded": loaded,
        "support_files": support,
        "weather": weather_info,
        "message": "Farm field model built from verified downloaded maps and weather.",
        "error": None if validation.get("valid") else validation.get("error"),
    }


def fetch_and_build_farm(farm_id: str) -> dict[str, Any]:
    """Download online layers and build TxtInOut in one step."""
    from services import readiness_service
    blocked, reason = readiness_service.should_block_online_rebuild(farm_id)
    if blocked:
        return {"ok": False, "error": reason}
    fetch = fetch_online_data(farm_id)
    if not fetch.get("ok"):
        return fetch
    build = build_farm_model_from_downloads(farm_id)
    if not build.get("ok"):
        return {
            "ok": False,
            "error": build.get("error") or "Could not build field model from downloaded data.",
            "fetch": fetch,
            "build": build,
        }
    return {
        "ok": True,
        "message": "Downloaded map data and built your farm field model.",
        "hru_count": build.get("hru_count"),
        "sources": fetch.get("sources"),
        "fetch": fetch,
        "build": build,
    }
