"""
HRU Generator — Auto-create SWAT+ HRUs from GIS data.
Algorithm: Overlay soil + land use + slope → unique combinations → export to TxtInOut.
"""
import os
import uuid
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import geopandas as gpd
import rasterio
from rasterio import features
from shapely.geometry import shape, mapping
import pandas as pd

from services.gis_service import compute_slope

logger = logging.getLogger(__name__)


@dataclass
class HRUResult:
    success: bool
    hru_count: int
    geojson: Optional[dict] = None
    txtinout_path: Optional[str] = None
    error: Optional[str] = None
    details: Optional[dict] = None


# SWAT+ land use codes (simplified lookup)
SWAT_LU_CODES = {
    "corn": "CROR", "soybean": "SOYB", "wheat": "WHEF", "rice": "RICE",
    "cotton": "COTT", "alfalfa": "ALFA", "forest": "FRST", "grass": "GRASS",
    "urban": "URBN", "water": "WATR", "barren": "BARR",
}

# SWAT+ slope class definitions
SLOPE_CLASSES = [
    (0, 2, "1"),
    (2, 5, "2"),
    (5, 10, "3"),
    (10, 999, "4"),
]


def classify_slope(slope_percent: float) -> str:
    """Return SWAT+ slope class string."""
    for lo, hi, cls in SLOPE_CLASSES:
        if lo <= slope_percent < hi:
            return cls
    return "4"


def compute_unique_hrus(dem: np.ndarray, soil_gdf: gpd.GeoDataFrame,
                       landuse_arr: np.ndarray, landuse_transform,
                       slope_arr: np.ndarray, slope_transform,
                       soil_crs: str, landuse_crs: str,
                       slope_threshold: float = 0.0,
                       lu_threshold: float = 0.0,
                       soil_threshold: float = 0.0) -> gpd.GeoDataFrame:
    """
    Core HRU algorithm — overlay data layers and extract unique combinations.

    Returns GeoDataFrame of HRU polygons with properties:
    hru_id, landuse, soil, slope_class, area_ha
    """
    # Get common CRS
    if soil_crs and landuse_crs and soil_crs != landuse_crs:
        soil_gdf = soil_gdf.to_crs(landuse_crs)
        soil_crs = landuse_crs
    if soil_crs and landuse_crs and soil_crs != landuse_crs:
        landuse_crs = soil_crs

    # Determine target resolution from landuse raster
    if landuse_arr is not None and landuse_transform is not None:
        target_transform = landuse_transform
        target_shape = landuse_arr.shape
    elif dem is not None:
        # Fall back to DEM resolution
        target_shape = dem.shape
        target_transform = None  # will use bounds
    else:
        raise ValueError("Need either landuse raster or DEM to define grid resolution")

    rows, cols = target_shape

    # Create slope class grid
    slope_classes = np.zeros_like(slope_arr, dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            if not np.isnan(slope_arr[r, c]):
                slope_classes[r, c] = int(classify_slope(slope_arr[r, c]))

    # Rasterize soil polygons to the target grid
    if soil_gdf is not None and len(soil_gdf) > 0:
        # Get bounds from existing raster
        if landuse_transform:
            bounds = rasterio.transform.bounds(landuse_transform)
            out_shape = (rows, cols)
            new_transform = landuse_transform
        else:
            bounds = (0, 0, cols * 30, rows * 30)  # Assume 30m cells
            out_shape = (rows, cols)
            new_transform = rasterio.transform.from_bounds(*bounds, cols, rows)

        soil_codes = list(range(1, len(soil_gdf) + 1))
        soil_field = soil_gdf.columns[0] if len(soil_gdf.columns) > 0 else "id"

        soil_raster = features.rasterize(
            [(geom, code) for code, geom in zip(soil_codes, soil_gdf.geometry)],
            out_shape=out_shape,
            fill=0,
            transform=new_transform
        )

        # Map soil codes back to actual soil IDs
        soil_id_map = {code: soil_gdf.iloc[i].get(soil_field, f"SOIL{i}") for i, code in enumerate(soil_codes, 1)}
    else:
        soil_raster = np.zeros((rows, cols), dtype=np.int32)
        soil_id_map = {}

    # Stack layers into unique value grid
    if landuse_arr is not None:
        landuse_safe = np.nan_to_num(landuse_arr, nan=0).astype(np.int32)
    else:
        landuse_safe = np.ones((rows, cols), dtype=np.int32)

    unique_grid = (
        landuse_safe.astype(np.int64) * 1000000 +
        soil_raster.astype(np.int64) * 1000 +
        slope_classes.astype(np.int64)
    )

    # Count unique values and their areas
    unique_vals, counts = np.unique(unique_grid, return_counts=True)

    hru_records = []
    hru_id = 1

    # Get cell area (rough estimate from transform)
    if landuse_transform:
        cell_area = abs(landuse_transform[0] * landuse_transform[4])  # pixelsize_x * pixelsize_y
        cell_area_ha = cell_area / 10000
    else:
        cell_area_ha = 30 * 30 / 10000  # 30m default

    for val, count in zip(unique_vals, counts):
        if val == 0:
            continue

        landuse_code = int(val // 1000000)
        soil_code = int((val % 1000000) // 1000)
        slope_cls = int(val % 1000)

        # Filter by thresholds (convert count to approximate area %)
        total_cells = rows * cols
        area_percent = (count / total_cells) * 100

        if area_percent < max(lu_threshold, 0.1):
            continue

        area_ha = count * cell_area_ha

        # Look up soil name
        soil_name = soil_id_map.get(soil_code, f"SOIL{soil_code}")

        hru_records.append({
            "hru_id": hru_id,
            "landuse_code": landuse_code,
            "soil": soil_name,
            "slope_class": str(slope_cls),
            "area_ha": round(area_ha, 2),
            "cell_count": int(count),
            "area_percent": round(area_percent, 2),
        })
        hru_id += 1

    hru_gdf = gpd.GeoDataFrame(hru_records, crs=landuse_crs or "EPSG:4326")

    # Create simple polygon geometries (grid cells) for visualization
    # In a full implementation, we'd polygonize the actual grid
    # For now, assign centroids based on grid position
    if landuse_transform:
        landuse_bounds = rasterio.transform.bounds(landuse_transform)
        minx, miny, maxx, maxy = landuse_bounds
        pixel_width = (maxx - minx) / cols
        pixel_height = (maxy - miny) / rows

        centroids_x = []
        centroids_y = []
        for _, row in hru_gdf.iterrows():
            # Get first matching cell
            mask = unique_grid == (
                row["landuse_code"] * 1000000 +
                list(soil_id_map.keys())[list(soil_id_map.values()).index(row["soil"]) - 1] * 1000
                if row["soil"] in soil_id_map.values() else
                int(row["slope_class"])
            ) if False else 0  # Simplified - use row index
            idx = max(0, (hru_id - 2) % rows), max(0, (hru_id - 2) % cols)
            cx = minx + (idx[1] + 0.5) * pixel_width
            cy = maxy - (idx[0] + 0.5) * pixel_height
            centroids_x.append(cx)
            centroids_y.append(cy)

        from shapely.geometry import Point
        hru_gdf["geometry"] = [Point(x, y) for x, y in zip(centroids_x, centroids_y)]

    return hru_gdf


def polygonize_hrus(unique_grid: np.ndarray, transform,
                    slope_threshold: float = 0.0) -> gpd.GeoDataFrame:
    """
    Convert the unique combination grid to actual polygon geometries.
    Uses rasterio.features.polygonize.
    """
    valid = unique_grid != 0
    if not valid.any():
        return gpd.GeoDataFrame()

    shapes = list(features.shapes(unique_grid, transform=transform, mask=valid))

    if not shapes:
        return gpd.GeoDataFrame()

    polygons = []
    for geom, val in shapes:
        landuse_code = int(val // 1000000)
        soil_code = int((val % 1000000) // 1000)
        slope_cls = int(val % 1000)

        polygons.append({
            "hru_id": 0,  # Will be renumbered
            "landuse_code": landuse_code,
            "soil_code": soil_code,
            "slope_class": str(slope_cls),
            "geometry": shape(geom)
        })

    gdf = gpd.GeoDataFrame(polygons, crs="EPSG:4326")
    gdf_proj = gdf.to_crs(3857)
    gdf["area_ha"] = gdf_proj.geometry.area / 10000

    return gdf


def assign_lu_names(hru_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Try to assign human-readable land use names from codes."""
    for idx, row in hru_gdf.iterrows():
        code = row.get("landuse_code", 0)
        # Try common NLCD-like codes
        lu_names = {
            11: "Open Water", 12: "Perennial Ice/Snow", 21: "Developed Open",
            22: "Developed Low", 23: "Developed Medium", 24: "Developed High",
            41: "Deciduous Forest", 42: "Evergreen Forest", 43: "Mixed Forest",
            52: "Shrub/Scrub", 71: "Grassland", 81: "Pasture", 82: "Cultivated Crops",
            90: "Woody Wetlands", 95: "Emergent Wetlands",
        }
        hru_gdf.at[idx, "landuse"] = lu_names.get(int(code), f"LU{code}")

    if "landuse" not in hru_gdf.columns:
        hru_gdf["landuse"] = hru_gdf["landuse_code"].apply(lambda x: f"LU{x}")

    return hru_gdf


def export_txtinout(hru_gdf: gpd.GeoDataFrame, output_dir: str,
                   watershed_name: str = "Watershed") -> Dict[str, str]:
    """
    Export HRUs to a minimal TxtInOut folder structure for SWAT+.
    Creates all required text files.
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "wgn"), exist_ok=True)

    created = {}

    # ---- bsn (basin parameters) ----
    bsn = f"""Title: {watershed_name}
| Basin Parameters
0          {watershed_name}     | subbasin: 1 {watershed_name}
    1.0     | sub_basin_inft  | default: 1.0
    0.0     | sub_basin_lu    | default: 0.0
    0.0     | sub_basin_soil  | default: 0.0
    0.0     | sub_basin_slp   | default: 0.0
    0.0     | sub_basin_own   | default: 0.0
    0       | sub_snow        | default: 0
    0       | sub_urb_frac    | default: 0
    0       | sub_urb_lu      | default: 0
    0       | sub_pwd_fr_m2   | default: 0
"""
    bsn_path = os.path.join(output_dir, "bsn")
    with open(bsn_path, "w") as f:
        f.write(bsn)
    created["bsn"] = bsn_path

    # ---- hru-data.hru ----
    hru_lines = ["her.hru |          | subbasin        |   hru | slope | luse  | soil  |       mgt_id |       rot_id |  sol_id |  olt |  flod |  filter |  drain |  pothole |  urb_ro |  sed_min |  sed_org |  atmo_dep |  user_def |      geo_id |  latitude |   altitude |  sub_basin_inft |  sub_basin_lu |  sub_basin_soil |  sub_basin_slp |  sub_basin_own |  sub_snow |  sub_urb_frac |  sub_urb_lu"]
    hru_lines.append("her.hru |          | subbasin        |   hru | slope | luse  | soil  |       mgt_id |       rot_id |  sol_id |  olt |  flod |  filter |  drain |  pothole |  urb_ro |  sed_min |  sed_org |  atmo_dep |  user_def |      geo_id |  latitude |   altitude |  sub_basin_inft |  sub_basin_lu |  sub_basin_soil |  sub_basin_slp |  sub_basin_own |  sub_snow |  sub_urb_frac |  sub_urb_lu")
    hru_lines.append("her.hru |          | subbasin        |   hru | slope | luse  | soil  |       mgt_id |       rot_id |  sol_id |  olt |  flod |  filter |  drain |  pothole |  urb_ro |  sed_min |  sed_org |  atmo_dep |  user_def |      geo_id |  latitude |   altitude |  sub_basin_inft |  sub_basin_lu |  sub_basin_soil |  sub_basin_slp |  sub_basin_own |  sub_snow |  sub_urb_frac |  sub_urb_lu")

    lat_base = 40.0
    for i, row in hru_gdf.iterrows():
        hru_id = row.get("hru_id", i + 1)
        lu = row.get("landuse", "AGRL").upper()[:4].ljust(4)
        soil = row.get("soil", "0001")[:8].ljust(8)
        slp = row.get("slope_class", "1")
        area = row.get("area_ha", 1.0)
        lat = lat_base + (i * 0.001)

        # Format: subbasin(1) hru-id slope lu soil mgt_id rot_id sol_id ...
        line = (
            f"  1.{hru_id:03d}    |           1 |     1.{hru_id:03d} |    {slp} | "
            f"{lu} | {soil} |        1 |        1 |     1 |  0 |  0 |      0 | "
            f"     0 |       0 |       0 |       0 |       0 |       0 |       0 | "
            f"       0 |          1 | {lat:.4f} |    0.0 |           1 |           0 "
            f"|           0 |           0 |           0 |      0 |           0 |           0"
        )
        hru_lines.append(line)

    hru_path = os.path.join(output_dir, "hru-data.hru")
    with open(hru_path, "w") as f:
        f.write("\n".join(hru_lines))
    created["hru-data.hru"] = hru_path

    # ---- fig.dat (topography) ----
    fig_lines = ["her.fg |          | subbasin        |   hru | slope |  elev  |  slope_len |  lat_len"]
    fig_lines.append("her.fg |          | subbasin        |   hru | slope |  elev  |  slope_len |  lat_len")
    for i, row in hru_gdf.iterrows():
        hru_id = row.get("hru_id", i + 1)
        slp = row.get("slope_class", "1")
        fig_lines.append(f"  1.{hru_id:03d}    |           1 |     1.{hru_id:03d} |    {slp} |   0.05 |   0.10 |  50.0")

    fig_path = os.path.join(output_dir, "fig.dat")
    with open(fig_path, "w", encoding="utf-8") as f:
        f.write("\n".join(fig_lines))
    created["fig.dat"] = fig_path

    # ---- sol.dat (soil — simplified) ----
    sol_data = {}
    for i, row in hru_gdf.iterrows():
        soil = row.get("soil", f"SOIL{i+1}")
        if soil not in sol_data:
            sol_data[soil] = len(sol_data) + 1

    sol_lines = ["her.sol |          | subbasin        |   hru | soil"]
    sol_lines.append("her.sol |          | subbasin        |   hru | soil")
    for i, row in hru_gdf.iterrows():
        hru_id = row.get("hru_id", i + 1)
        soil = row.get("soil", f"SOIL{i+1}")[:8]
        sol_id = sol_data.get(soil, 1)
        sol_lines.append(f"  1.{hru_id:03d}    |           1 |     1.{hru_id:03d} |     {sol_id}")

    sol_path = os.path.join(output_dir, "sol.dat")
    with open(sol_path, "w") as f:
        f.write("\n".join(sol_lines))
    created["sol.dat"] = sol_path

    # ---- lu.dat ----
    lu_codes = {}
    for i, row in hru_gdf.iterrows():
        lu = row.get("landuse", "AGRL")[:4].upper()
        if lu not in lu_codes:
            lu_codes[lu] = len(lu_codes) + 1

    lu_lines = ["her.lu |          | subbasin        |   hru | luse"]
    lu_lines.append("her.lu |          | subbasin        |   hru | luse")
    for i, row in hru_gdf.iterrows():
        hru_id = row.get("hru_id", i + 1)
        lu = row.get("landuse", "AGRL")[:4].upper()
        lu_id = lu_codes.get(lu, 1)
        lu_lines.append(f"  1.{hru_id:03d}    |           1 |     1.{hru_id:03d} |    {lu_id}")

    lu_path = os.path.join(output_dir, "lu.dat")
    with open(lu_path, "w") as f:
        f.write("\n".join(lu_lines))
    created["lu.dat"] = lu_path

    # ---- mgt.dat (management — default) ----
    mgt_lines = ["her.mgt |          | subbasin        |   hru | mgt"]
    mgt_lines.append("her.mgt |          | subbasin        |   hru | mgt")
    for i in range(len(hru_gdf)):
        hru_id = i + 1
        mgt_lines.append(f"  1.{hru_id:03d}    |           1 |     1.{hru_id:03d} |     1")

    mgt_path = os.path.join(output_dir, "mgt.dat")
    with open(mgt_path, "w") as f:
        f.write("\n".join(mgt_lines))
    created["mgt.dat"] = mgt_path

    # ---- routing.unit ----
    ru_lines = ["her.rou |          | subbasin        |   ru"]
    ru_lines.append("her.rou |          | subbasin        |   ru")
    ru_lines.append("  1.001    |           1")
    ru_path = os.path.join(output_dir, "routing.unit")
    with open(ru_path, "w") as f:
        f.write("\n".join(ru_lines))
    created["routing.unit"] = ru_path

    return created


class HRUGenerator:
    def __init__(self):
        self.hru_gdf: Optional[gpd.GeoDataFrame] = None
        self.simulation_data: Dict = {}

    def generate(self, gis_service, slope_thresholds: List[float] = None,
                 lu_threshold: float = 1.0, soil_threshold: float = 1.0,
                 output_dir: str = None) -> HRUResult:
        """
        Full HRU generation pipeline.
        1. Compute unique combos from overlaid data
        2. Create polygon geometries
        3. Export to TxtInOut
        """
        try:
            data = gis_service.data

            if data.dem is None:
                return HRUResult(success=False, hru_count=0, error="DEM is required. Download real elevation data first.")
            if data.landuse is None:
                return HRUResult(success=False, hru_count=0, error="Land use raster is required.")

            slope = data.slope if data.slope is not None else compute_slope(data.dem, data.dem_transform)
            landuse = data.landuse

            # Get transforms
            lt = data.landuse_transform if data.landuse_transform else data.dem_transform
            st = data.slope_transform if data.slope_transform else data.dem_transform

            # Compute unique HRU grid
            unique_grid = np.zeros_like(landuse, dtype=np.int64)

            soil_arr = np.zeros_like(landuse, dtype=np.int32)
            if data.soil is not None and len(data.soil) > 0:
                if lt:
                    out_shape = landuse.shape
                    soil_arr = features.rasterize(
                        [(geom, i + 1) for i, geom in enumerate(data.soil.geometry)],
                        out_shape=out_shape,
                        transform=lt,
                        fill=0,
                    )

            slope_cls = np.zeros_like(landuse, dtype=np.int32)
            for r in range(slope.shape[0]):
                for c in range(slope.shape[1]):
                    if not np.isnan(slope[r, c]):
                        slope_cls[r, c] = int(classify_slope(slope[r, c]))

            landuse_safe = np.nan_to_num(landuse, nan=1).astype(np.int64)
            soil_part = soil_arr.astype(np.int64)
            slope_part = slope_cls.astype(np.int64)
            unique_grid = (landuse_safe * 1000000 + soil_part * 1000 + slope_part).astype(np.int32)

            # Polygonize
            if lt is None:
                return HRUResult(success=False, hru_count=0, error="No transform available for polygonization")

            poly_gdf = polygonize_hrus(unique_grid, lt, slope_threshold=slope_thresholds[0] if slope_thresholds else 0.0)

            if len(poly_gdf) == 0:
                return HRUResult(success=False, hru_count=0, error="No HRU polygons generated. Check data alignment.")

            if "area_ha" not in poly_gdf.columns:
                poly_proj = poly_gdf.to_crs(3857)
                poly_gdf["area_ha"] = poly_proj.geometry.area / 10000

            # Filter tiny slivers (area_ha is in hectares)
            min_ha = max(0.0001, lu_threshold)
            poly_gdf = poly_gdf[poly_gdf["area_ha"] >= min_ha].copy()

            # Renumber HRUs
            poly_gdf["hru_id"] = range(1, len(poly_gdf) + 1)

            # Assign land use names
            poly_gdf = assign_lu_names(poly_gdf)
            poly_proj = poly_gdf.to_crs(3857)
            poly_gdf["area_ha"] = poly_proj.geometry.area / 10000

            self.hru_gdf = poly_gdf

            # Export to TxtInOut
            txtinout_path = None
            if output_dir:
                created = export_txtinout(poly_gdf, output_dir)
                txtinout_path = output_dir

            # Build summary
            summary = {
                "total_hrus": len(poly_gdf),
                "total_area_km2": round(poly_proj.geometry.area.sum() / 1e6, 2),
                "landuse_classes": poly_gdf["landuse"].nunique() if "landuse" in poly_gdf.columns else 0,
                "soil_types": poly_gdf["soil_code"].nunique() if "soil_code" in poly_gdf.columns else 0,
            }

            return HRUResult(
                success=True,
                hru_count=len(poly_gdf),
                geojson=poly_gdf.__geo_interface__,
                txtinout_path=txtinout_path,
                details=summary
            )

        except Exception as e:
            logger.error(f"HRU generation failed: {e}")
            import traceback
            traceback.print_exc()
            return HRUResult(success=False, hru_count=0, error=str(e))


hru_generator = HRUGenerator()