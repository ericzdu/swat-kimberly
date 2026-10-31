"""
Map Viewer — Folium-based interactive map generation for Gradio.
"""
import folium
from folium import plugins
import json


def create_map(center: tuple = None, zoom: int = 8) -> folium.Map:
    """Create a base Folium map."""
    if center is None:
        center = [39.8283, -98.5795]  # US center
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    plugins.Fullscreen().add_to(m)
    return m


def add_geojson_layer(m: folium.Map, geojson: dict, name: str,
                      style: dict = None, color: str = "blue") -> folium.Map:
    """Add a GeoJSON layer to a Folium map."""
    if style is None:
        style = {"color": color, "weight": 2, "fillOpacity": 0.4}

    # Handle FeatureCollection vs single Feature
    gj_data = geojson
    if geojson.get("type") == "FeatureCollection":
        gj_data = geojson
    elif geojson.get("type") == "Feature":
        gj_data = {"type": "FeatureCollection", "features": [geojson]}

    folium.GeoJson(
        gj_data,
        name=name,
        style_function=lambda x: style,
        popup=folium.GeoJsonPopup(fields=["name"] if "name" in geojson.get("features", [{}])[0].get("properties", {}) else []),
        tooltip=folium.GeoJsonTooltip(fields=["name"] if "name" in geojson.get("features", [{}])[0].get("properties", {}) else ["id"]),
    ).add_to(m)
    return m


def add_raster_overlay(m: folium.Map, affine, bounds, values,
                       name: str, cmap: str = "viridis") -> folium.Map:
    """Add a raster overlay using ImageOverlay (simplified)."""
    import numpy as np

    if values is None:
        return m

    try:
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm

        # Normalize to 0-255 for RGBA
        vmin, vmax = np.nanmin(values), np.nanmax(values)
        normalized = (values - vmin) / (vmax - vmin + 1e-10)
        rgba = cm.get_cmap(cmap)(normalized)[:, :, :4]
        rgba_uint8 = (rgba * 255).astype("uint8")

        import base64
        import io
        from PIL import Image

        img = Image.fromarray(rgba_uint8, mode="RGBA")
        img_io = io.BytesIO()
        img.save(img_io, format="PNG")
        img_str = base64.b64encode(img_io.getvalue()).decode()

        bounds_coords = [[bounds.bottom, bounds.left], [bounds.top, bounds.right]]
        img_overlay = folium.raster_layers.ImageOverlay(
            image=f"data:image/png;base64,{img_str}",
            bounds=bounds_coords,
            opacity=0.6,
            name=name,
            mercator_project=True
        )
        img_overlay.add_to(m)
    except Exception as e:
        pass  # Skip raster if matplotlib not available

    return m


def map_html(gis_service) -> str:
    """
    Generate a Folium map from loaded GIS data in gis_service.
    Returns HTML string for gr.HTML().
    """
    center = gis_service.data.center or [39.8, -98.5]
    m = create_map(center=center, zoom=9)

    # Add layers
    layers_added = []

    if gis_service.data.watershed is not None:
        try:
            add_geojson_layer(m, gis_service.data.watershed.__geo_interface__,
                              "Watershed Boundary", color="#22c55e")
            layers_added.append("Watershed")
        except Exception:
            pass

    if gis_service.data.soil is not None:
        try:
            add_geojson_layer(m, gis_service.data.soil.__geo_interface__,
                              "Soil", color="#92400e")
            layers_added.append("Soil")
        except Exception:
            pass

    if gis_service.data.dem is not None and gis_service.data.dem_bounds is not None:
        try:
            bounds = gis_service.data.dem_bounds
            add_raster_overlay(m, gis_service.data.dem_transform,
                               type('Bounds', (), {'left': bounds[0], 'bottom': bounds[1],
                                                   'right': bounds[2], 'top': bounds[3]})(),
                               gis_service.data.dem, "DEM (Elevation)", cmap="terrain")
            layers_added.append("DEM")
        except Exception:
            pass

    if layers_added:
        folium.LayerControl().add_to(m)

    # If no data, show placeholder
    if not layers_added:
        folium.Marker(
            location=center,
            popup="Upload GIS data to see the map",
            icon=folium.Icon(color="gray", icon="info-sign")
        ).add_to(m)

    return m._repr_html_()


def hru_map_html(hru_gdf, center: tuple = None) -> str:
    """
    Generate a Folium map showing HRU polygons.
    hru_gdf: GeoDataFrame with HRU polygons and properties.
    Returns HTML string.
    """
    center = center or [39.8, -98.5]
    m = create_map(center=center, zoom=10)

    if hru_gdf is None or len(hru_gdf) == 0:
        folium.Marker(location=center, popup="No HRUs generated yet").add_to(m)
        return m._repr_html_()

    # Color by dominant factor
    import numpy as np
    colors = ["#22c55e", "#3b82f6", "#f97316", "#8b5cf6", "#eab308",
              "#ef4444", "#14b8a6", "#ec4899", "#f59e0b", "#6366f1"]

    gj = hru_gdf.__geo_interface__

    def style_fn(feature):
        idx = hash(str(feature["properties"].get("hru_id", 0))) % len(colors)
        return {
            "color": colors[idx],
            "weight": 2,
            "fillOpacity": 0.5,
            "fillColor": colors[idx]
        }

    folium.GeoJson(
        gj,
        style_function=style_fn,
        popup=folium.GeoJsonTooltip(
            fields=["hru_id", "landuse", "soil", "slope_class", "area_ha"]
        ),
        name="HRUs"
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m._repr_html_()