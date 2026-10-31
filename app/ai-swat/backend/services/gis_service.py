"""
GIS Service — data loading for DEM, soil, land use, watershed files.
Supports: GeoTIFF, shapefile (.shp), KML/KMZ, GeoJSON
"""
import os
import tempfile
import logging
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.transform import from_bounds
import geopandas as gpd
import folium
from shapely.geometry import shape, MultiPolygon, Polygon

logger = logging.getLogger(__name__)


@dataclass
class GISData:
    """Container for loaded GIS data."""
    dem: Optional[np.ndarray] = None
    dem_transform: Optional[Any] = None
    dem_bounds: Optional[Tuple] = None
    soil: Optional[gpd.GeoDataFrame] = None
    landuse: Optional[np.ndarray] = None
    landuse_transform: Optional[Any] = None
    landuse_crs: Optional[str] = None
    watershed: Optional[gpd.GeoDataFrame] = None
    slope: Optional[np.ndarray] = None
    slope_transform: Optional[Any] = None
    crs: Optional[str] = None
    center: Optional[Tuple[float, float]] = None

    def has_dem(self) -> bool:
        return self.dem is not None

    def has_soil(self) -> bool:
        return self.soil is not None and len(self.soil) > 0

    def has_landuse(self) -> bool:
        return self.landuse is not None


# ---- Raster loading ----

def load_geotiff(path: str) -> Tuple[np.ndarray, Any, Tuple, str]:
    """Load a GeoTIFF file. Returns: data, transform, bounds, crs."""
    with rasterio.open(path) as src:
        data = src.read(1)
        transform = src.transform
        bounds = src.bounds
        crs = str(src.crs) if src.crs else None
    return data, transform, bounds, crs


def compute_slope(dem: np.ndarray, transform, cellsize: float = 30.0) -> np.ndarray:
    """Compute slope (%) from DEM using finite differences."""
    rows, cols = dem.shape
    slope = np.zeros_like(dem, dtype=np.float32)
    # Simple 3x3 finite difference
    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            dzdx = (dem[r, c + 1] - dem[r, c - 1]) / (2 * cellsize)
            dzdy = (dem[r + 1, c] - dem[r - 1, c]) / (2 * cellsize)
            slope[r, c] = np.sqrt(dzdx**2 + dzdy**2) * 100  # percent
    # Handle edges
    slope[0, :] = slope[1, :]
    slope[-1, :] = slope[-2, :]
    slope[:, 0] = slope[:, 1]
    slope[:, -1] = slope[:, -2]
    return slope


# ---- Vector loading ----

def load_shapefile(path: str) -> gpd.GeoDataFrame:
    """Load a shapefile (.shp) into GeoDataFrame."""
    gdf = gpd.read_file(path)
    if gdf.crs:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def load_kml(path: str) -> gpd.GeoDataFrame:
    """Load KML/KMZ file into GeoDataFrame."""
    gdf = gpd.read_file(path, driver="KML")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf


def load_geojson(path: str) -> gpd.GeoDataFrame:
    """Load GeoJSON into GeoDataFrame."""
    gdf = gpd.read_file(path)
    if gdf.crs:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


# ---- Unified file loader ----

def load_file(path: str) -> Tuple[str, Any]:
    """
    Auto-detect file type and load appropriately.
    Returns (file_type, data).
    Types: 'raster_geotiff', 'shapefile', 'kml', 'geojson'
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in (".tif", ".tiff", ".img"):
        return "raster_geotiff", load_geotiff(path)

    if ext == ".shp":
        return "shapefile", load_shapefile(path)

    if ext in (".kml", ".kmz"):
        return "kml", load_kml(path)

    if ext in (".geojson", ".json"):
        return "geojson", load_geojson(path)

    raise ValueError(f"Unsupported file format: {ext}")


# ---- Main GIS data class ----

class GISService:
    def __init__(self):
        self.data = GISData()
        self._temp_dir = tempfile.mkdtemp()

    def load_dem(self, path: str) -> Dict[str, Any]:
        """Load DEM (GeoTIFF). Computes slope automatically."""
        dem, transform, bounds, crs = load_geotiff(path)
        cellsize = abs(transform[0])  # pixel size x

        # Compute slope
        slope = compute_slope(dem, transform, cellsize)

        self.data.dem = dem
        self.data.dem_transform = transform
        self.data.dem_bounds = (bounds.left, bounds.bottom, bounds.right, bounds.top)
        self.data.slope = slope
        self.data.slope_transform = transform
        self.data.crs = crs

        # Center point
        self.data.center = ((bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2)

        return {
            "status": "loaded",
            "shape": list(dem.shape),
            "bounds": self.data.dem_bounds,
            "crs": crs,
            "min_elevation": float(np.nanmin(dem)),
            "max_elevation": float(np.nanmax(dem)),
        }

    def load_soil(self, path: str) -> Dict[str, Any]:
        """Load soil shapefile."""
        gdf = load_shapefile(path)

        # Identify common soil attribute columns
        name_col = None
        for col in ["MUSYM", "SHORT_NAM", "SOIL_NAME", "NAME", "SOIL_ID"]:
            if col in gdf.columns:
                name_col = col
                break

        self.data.soil = gdf

        return {
            "status": "loaded",
            "count": len(gdf),
            "columns": list(gdf.columns),
            "name_column": name_col,
            "crs": str(gdf.crs) if gdf.crs else None,
        }

    def load_landuse(self, path: str) -> Dict[str, Any]:
        """Load land use (GeoTIFF or shapefile)."""
        ext = os.path.splitext(path)[1].lower()

        if ext in (".tif", ".tiff", ".img"):
            lu, transform, bounds, crs = load_geotiff(path)
            self.data.landuse = lu
            self.data.landuse_transform = transform
            self.data.landuse_crs = crs
            unique_values = len(np.unique(lu[~np.isnan(lu)]))
            return {
                "status": "loaded",
                "type": "raster",
                "shape": list(lu.shape),
                "unique_classes": unique_values,
            }
        else:
            # Shapefile
            gdf = load_shapefile(path)
            self.data.soil = gdf  # reuse soil slot for landuse polygon too
            return {
                "status": "loaded",
                "type": "vector",
                "count": len(gdf),
                "columns": list(gdf.columns),
            }

    def load_watershed(self, path: str) -> Dict[str, Any]:
        """Load watershed boundary (shp, kml, geojson)."""
        ext = os.path.splitext(path)[1].lower()

        if ext in (".shp",):
            gdf = load_shapefile(path)
        elif ext in (".kml", ".kmz"):
            gdf = load_kml(path)
        else:
            gdf = load_geojson(path)

        self.data.watershed = gdf

        if gdf.crs:
            bounds = gdf.total_bounds  # minx, miny, maxx, maxy
            self.data.center = ((bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2)

        return {
            "status": "loaded",
            "count": len(gdf),
            "bounds": list(gdf.total_bounds),
            "crs": str(gdf.crs) if gdf.crs else None,
        }

    def get_geojson(self) -> Dict[str, Any]:
        """Export current data as GeoJSON for map display."""
        features = []

        # Watershed boundary
        if self.data.watershed is not None:
            gj = self.data.watershed.__geo_interface__
            features.append({
                "type": "watershed",
                "geojson": gj,
                "style": {"color": "#22c55e", "weight": 3, "fillOpacity": 0.1}
            })

        # Soil polygons
        if self.data.soil is not None:
            gj = self.data.soil.__geo_interface__
            features.append({
                "type": "soil",
                "geojson": gj,
                "style": {"color": "#92400e", "weight": 2, "fillOpacity": 0.3}
            })

        return {"features": features, "center": self.data.center}


gis_service = GISService()