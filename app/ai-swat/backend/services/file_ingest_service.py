"""Classify, sort, and import user-uploaded field files for SWAT+."""
from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd

import config
from db import db_one, update_farm
from services import crop_service, readiness_service
from services import data_download_service, pyswat_facade
from services.data_download_service import (
    BOUNDARY_NAME,
    DEM_NAME,
    LANDUSE_NAME,
    MANIFEST_NAME,
    SOIL_NAME,
    WEATHER_NAME,
    _dem_mean_elevation,
    _write_data_manifest,
    build_farm_model_from_downloads,
)
from utils.text import safe_text

INBOX_INDEX = "inbox_index.json"
TXTINOUT_MARKERS = ("file.cio", "hru-data.hru", "fig.dat")


def _inbox(farm_id: str) -> Path:
    d = config.farm_inbox_dir(farm_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gis(farm_id: str) -> Path:
    d = config.farm_gis_dir(farm_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)[:180]


def save_upload_to_inbox(farm_id: str, filename: str, content: bytes) -> dict[str, Any]:
    """Store a file in the farm inbox; extract zip archives automatically."""
    inbox = _inbox(farm_id)
    fname = _safe_name(filename or "upload.bin")
    dest = inbox / fname
    dest.write_bytes(content)
    extracted: list[str] = []

    if fname.lower().endswith(".zip"):
        extract_dir = inbox / f"{fname}_extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                rel = _safe_name(name.replace("\\", "/").split("/")[-1])
                if not rel:
                    continue
                target = extract_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
                extracted.append(str(target.relative_to(inbox)))
        # Also try nested folder extract preserving structure for shapefiles
        nested = inbox / f"{fname}_tree"
        if nested.exists():
            shutil.rmtree(nested)
        with zipfile.ZipFile(BytesIO(content)) as zf:
            zf.extractall(nested)
        extracted.append(str(nested.relative_to(inbox)))

    index = inspect_inbox(farm_id)
    return {
        "ok": True,
        "farm_id": farm_id,
        "saved_as": str(dest.relative_to(inbox)),
        "extracted": extracted,
        "file_count": len(index.get("files", [])),
        "summary": index.get("summary"),
        "message": "File saved to inbox. Use import_uploaded_field_data_for_swat to classify and build the model.",
    }


def _read_geojson_hint(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown"
    features = data.get("features", [data] if data.get("type") == "Feature" else [])
    if not features:
        return "unknown"
    props = (features[0] or {}).get("properties") or {}
    keys = " ".join(str(k).lower() for k in props.keys())
    if any(k in keys for k in ("soil", "clay", "sand", "texture", "mukey")):
        return "soil"
    geom = (features[0] or {}).get("geometry") or {}
    if geom.get("type") in ("Polygon", "MultiPolygon"):
        return "boundary"
    return "boundary"


def classify_path(path: Path) -> dict[str, Any]:
    name = path.name.lower()
    ext = path.suffix.lower()
    role = "unknown"
    confidence = "low"
    detail = ""

    if name in TXTINOUT_MARKERS or name.endswith(".cio") or name.endswith(".sim"):
        role, confidence, detail = "txtinout", "high", "SWAT+ project file"
    elif ext in (".pcp", ".tem", ".cli"):
        role, confidence, detail = "swat_weather", "high", "SWAT+ weather file"
    elif ext == ".sol":
        role, confidence, detail = "soil", "high", "SWAT+ soils file"
    elif ext in (".tif", ".tiff", ".asc", ".img"):
        if any(x in name for x in ("lu", "land", "crop", "nlcd")):
            role, confidence, detail = "landuse", "medium", "Land use raster"
        elif any(x in name for x in ("dem", "elev", "srtm", "dtm", "height")):
            role, confidence, detail = "dem", "high", "Elevation raster"
        else:
            role, confidence, detail = "dem", "medium", "GeoTIFF (assumed elevation)"
    elif ext == ".csv":
        role, confidence, detail = "weather_csv", "medium", "Tabular data (check for weather)"
    elif ext in (".json", ".geojson"):
        if "weather" in name or "meteo" in name or "climate" in name:
            role, confidence, detail = "weather_json", "high", "Weather JSON"
        else:
            hint = _read_geojson_hint(path)
            role = hint if hint != "unknown" else "geojson"
            confidence, detail = "medium", f"GeoJSON ({hint})"
    elif ext in (".shp", ".kml", ".gpkg"):
        if "soil" in name:
            role, confidence, detail = "soil_vector", "medium", "Soil vector"
        else:
            role, confidence, detail = "boundary_vector", "medium", "Field boundary vector"
    elif ext == ".zip":
        role, confidence, detail = "archive", "low", "Archive — extract first"

    return {
        "path": str(path),
        "name": path.name,
        "size": path.stat().st_size if path.exists() else 0,
        "role": role,
        "confidence": confidence,
        "detail": detail,
    }


def inspect_inbox(farm_id: str) -> dict[str, Any]:
    inbox = _inbox(farm_id)
    files: list[dict[str, Any]] = []
    for path in sorted(inbox.rglob("*")):
        if not path.is_file():
            continue
        if path.name == INBOX_INDEX:
            continue
        files.append(classify_path(path))

    by_role: dict[str, list] = {}
    for f in files:
        by_role.setdefault(f["role"], []).append(f["name"])

    has_txtinout = any(
        path.is_file() and path.name.lower() in TXTINOUT_MARKERS
        for path in inbox.rglob("*")
    )

    summary = {
        "total_files": len(files),
        "roles": {k: len(v) for k, v in by_role.items()},
        "has_complete_txtinout": has_txtinout,
        "can_build_from_gis": bool(
            any(r in by_role for r in ("dem",)) and
            any(r in by_role for r in ("boundary", "boundary_vector", "geojson"))
        ),
        "missing_for_gis_build": _missing_roles(by_role, has_txtinout),
    }

    index = {"files": files, "summary": summary}
    (inbox / INBOX_INDEX).write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {"ok": True, "farm_id": farm_id, "inbox_dir": str(inbox), **index}


def _missing_roles(by_role: dict, has_txtinout: bool) -> list[str]:
    if has_txtinout:
        return []
    missing = []
    if "dem" not in by_role:
        missing.append("elevation (DEM GeoTIFF)")
    if not any(r in by_role for r in ("boundary", "boundary_vector", "geojson")):
        missing.append("field boundary (GeoJSON/shapefile)")
    if "soil" not in by_role and "soil_vector" not in by_role:
        missing.append("soil (optional — can download if missing)")
    if not any(r in by_role for r in ("weather_json", "weather_csv", "swat_weather")):
        missing.append("weather (CSV/JSON or download)")
    if "landuse" not in by_role:
        missing.append("land use raster (optional — derived from boundary if missing)")
    return missing


def _find_txtinout_root(inbox: Path) -> Optional[Path]:
    candidates: list[Path] = []
    for marker in TXTINOUT_MARKERS:
        for hit in inbox.rglob(marker):
            if not hit.is_file():
                continue
            root = hit.parent
            has_hru = (root / "hru-data.hru").exists()
            has_cio = (root / "file.cio").exists() or (root / "fig.dat").exists()
            if has_hru or marker in ("hru-data.hru", "fig.dat"):
                candidates.append(root)
    if not candidates:
        return None

    def score(p: Path) -> tuple:
        name_bonus = 1 if p.name.lower() == "txtinout" else 0
        has_both = int((p / "hru-data.hru").exists() and ((p / "file.cio").exists() or (p / "fig.dat").exists()))
        return (has_both, name_bonus, len(p.parts))

    return max(candidates, key=score)


def _pick_dem_tif(search_root: Path) -> Optional[Path]:
    tifs = [p for p in search_root.rglob("*.tif") if p.is_file()]
    if not tifs:
        return None
    preferred = [
        p for p in tifs
        if any(k in p.name.lower() for k in ("dem", "elev", "slope"))
        and "aux" not in p.name.lower()
        and "clip" not in p.name.lower()
        and "hillshade" not in p.name.lower()
    ]
    pool = preferred or tifs
    return max(pool, key=lambda p: p.stat().st_size)


def _pick_boundary_vector(search_root: Path) -> Optional[Path]:
    shps = [p for p in search_root.rglob("*.shp") if p.is_file()]

    def rank(shp: Path) -> tuple:
        low = shp.name.lower()
        if "hru" in low and "wshed" not in low:
            return (0, len(low))
        if "subbas" in low:
            return (1, len(low))
        if "field" in low or "farm" in low:
            return (2, len(low))
        if "wshed" in low or "watershed" in low:
            return (4, len(low))
        return (3, len(low))

    if not shps:
        return None
    return min(shps, key=rank)


def _finalize_uploaded_txtinout(farm_id: str, txtinout: Path, inbox: Path) -> dict[str, Any]:
    """Register GIS layers and crop from a complete uploaded SWAT+ project."""
    gis = _gis(farm_id)
    sources: list[str] = []
    placed: dict[str, str] = {}

    search_roots = [txtinout, inbox]
    dem = None
    for root in search_roots:
        if root.exists():
            dem = _pick_dem_tif(root)
            if dem:
                break
    if dem:
        shutil.copy2(dem, gis / DEM_NAME)
        placed["dem"] = DEM_NAME
        sources.append(f"Elevation from upload ({dem.name})")

    boundary_shp = None
    for root in search_roots:
        if root.exists():
            boundary_shp = _pick_boundary_vector(root)
            if boundary_shp:
                break
    if boundary_shp:
        try:
            _vector_to_geojson(boundary_shp, gis / BOUNDARY_NAME)
            placed["boundary"] = BOUNDARY_NAME
            sources.append(f"Boundary from upload ({boundary_shp.name})")
        except Exception as exc:
            sources.append(f"Boundary shapefile found but could not convert: {safe_text(str(exc))}")

    for root in search_roots:
        if not root.exists():
            continue
        for sol in root.rglob("*.sol"):
            if sol.is_file():
                shutil.copy2(sol, gis / "soils.sol")
                placed["soil"] = "soils.sol"
                sources.append(f"Soil from upload ({sol.name})")
                break
        if "soil" in placed:
            break

    center = (0.0, 0.0)
    boundary_path = gis / BOUNDARY_NAME
    if boundary_path.exists():
        try:
            import geopandas as gpd
            gdf = gpd.read_file(boundary_path)
            if not gdf.empty and gdf.crs:
                gdf = gdf.to_crs("EPSG:4326")
                centroid = gdf.geometry.unary_union.centroid
                center = (float(centroid.y), float(centroid.x))
        except Exception:
            pass

    _write_data_manifest(gis, sources or ["Uploaded SWAT+ project"], center)
    crop_result = crop_service.sync_crop_from_txtinout(farm_id)
    update_farm(farm_id, data_source="upload_verified", setup_complete=True)
    return {"placed": placed, "sources": sources, "crop": crop_result}


def _import_txtinout_folder(farm_id: str, src: Path, inbox: Optional[Path] = None) -> dict[str, Any]:
    dest = config.farm_txtinout_dir(farm_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    validation = pyswat_facade.validate_txtinout(dest)
    if not validation.get("valid"):
        return {"ok": False, "error": validation.get("error", "Invalid TxtInOut")}
    finalize = _finalize_uploaded_txtinout(farm_id, dest, inbox or _inbox(farm_id))
    update_farm(farm_id, txtinout_path=str(dest), data_source="upload_verified", setup_complete=True)
    readiness = readiness_service.get_farm_readiness(farm_id)
    return {
        "ok": True,
        "mode": "txtinout",
        "txtinout_dir": str(dest),
        "validation": validation,
        "finalize": finalize,
        "ready_to_simulate": readiness.get("ready_to_simulate"),
        "message": "Imported complete SWAT+ project from your upload.",
    }


def _csv_to_weather_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    cols = {c.lower().strip(): c for c in reader.fieldnames}

    def pick(*names: str) -> Optional[str]:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    date_col = pick("date", "time", "day", "datetime")
    precip_col = pick("precip", "precipitation", "precip_mm", "rain", "pcp", "prcp")
    tmax_col = pick("tmax", "temp_max", "temperature_max", "max_temp", "tx")
    tmin_col = pick("tmin", "temp_min", "temperature_min", "min_temp", "tn")
    if not date_col:
        raise ValueError("CSV needs a date column (date, time, day...)")

    times: list[str] = []
    precip: list[float] = []
    tmax: list[Optional[float]] = []
    tmin: list[Optional[float]] = []

    for row in reader:
        raw = (row.get(date_col) or "").strip()
        if not raw:
            continue
        dt = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(raw[:10], fmt)
                break
            except ValueError:
                continue
        if not dt:
            continue
        times.append(dt.strftime("%Y-%m-%d"))
        precip.append(float(row[precip_col] or 0) if precip_col else 0.0)
        tmax.append(float(row[tmax_col]) if tmax_col and row.get(tmax_col) not in (None, "") else None)
        tmin.append(float(row[tmin_col]) if tmin_col and row.get(tmin_col) not in (None, "") else None)

    if len(times) < 30:
        raise ValueError("CSV needs at least 30 days of weather rows")

    return {
        "daily": {
            "time": times,
            "precipitation_sum": precip,
            "temperature_2m_max": tmax,
            "temperature_2m_min": tmin,
        },
        "source": f"uploaded_csv:{path.name}",
    }


def _copy_best(files: list[Path], dest: Path) -> Optional[Path]:
    if not files:
        return None
    chosen = max(files, key=lambda p: p.stat().st_size)
    shutil.copy2(chosen, dest)
    return chosen


def _vector_to_geojson(path: Path, out_path: Path) -> None:
    import geopandas as gpd
    gdf = gpd.read_file(path)
    if gdf.crs:
        gdf = gdf.to_crs("EPSG:4326")
    gdf.to_file(out_path, driver="GeoJSON")


def import_inbox_for_swat(farm_id: str, run_build: bool = True) -> dict[str, Any]:
    """
    Classify inbox files, copy into GIS/TxtInOut layout, build field model when possible.
    """
    inbox = _inbox(farm_id)
    gis = _gis(farm_id)
    if not any(inbox.rglob("*")):
        return {"ok": False, "error": "Inbox is empty. Upload files first (zip, GeoTIFF, CSV, GeoJSON, or TxtInOut zip)."}

    inspection = inspect_inbox(farm_id)
    steps: list[dict[str, Any]] = [{"step": "inspect", "summary": inspection.get("summary")}]

    txt_root = _find_txtinout_root(inbox)
    if txt_root:
        result = _import_txtinout_folder(farm_id, txt_root, inbox=inbox)
        steps.append({"step": "txtinout_import", **result})
        if result.get("ok"):
            readiness = readiness_service.get_farm_readiness(farm_id)
            return {
                "ok": True,
                "mode": "txtinout",
                "message": result.get("message"),
                "steps": steps,
                "ready_to_simulate": readiness.get("ready_to_simulate"),
                "readiness": readiness,
            }
        return {"ok": False, "error": result.get("error"), "steps": steps}

    classified = inspection.get("files", [])
    by_role: dict[str, list[Path]] = {}
    for item in classified:
        by_role.setdefault(item["role"], []).append(Path(item["path"]))

    sources: list[str] = []
    placed: dict[str, str] = {}

    dem_files = by_role.get("dem", [])
    if dem_files:
        src = _copy_best(dem_files, gis / DEM_NAME)
        if src:
            placed["dem"] = DEM_NAME
            sources.append(f"Elevation from upload ({src.name})")

    lu_files = by_role.get("landuse", [])
    if lu_files:
        src = _copy_best(lu_files, gis / LANDUSE_NAME)
        if src:
            placed["landuse"] = LANDUSE_NAME
            sources.append(f"Land use from upload ({src.name})")

    for role, dest_name in (("boundary", BOUNDARY_NAME), ("geojson", BOUNDARY_NAME)):
        for path in by_role.get(role, []):
            if role == "geojson" and _read_geojson_hint(path) == "soil":
                continue
            shutil.copy2(path, gis / dest_name)
            placed["boundary"] = dest_name
            sources.append(f"Boundary from upload ({path.name})")
            break
        if "boundary" in placed:
            break

    if "boundary" not in placed:
        for path in by_role.get("boundary_vector", []):
            _vector_to_geojson(path, gis / BOUNDARY_NAME)
            placed["boundary"] = BOUNDARY_NAME
            sources.append(f"Boundary from upload ({path.name})")
            break

    for role in ("soil",):
        for path in by_role.get(role, []):
            shutil.copy2(path, gis / SOIL_NAME)
            placed["soil"] = SOIL_NAME
            sources.append(f"Soil from upload ({path.name})")
            break
    for path in by_role.get("soil_vector", []):
        _vector_to_geojson(path, gis / SOIL_NAME)
        placed["soil"] = SOIL_NAME
        sources.append(f"Soil from upload ({path.name})")
        break

    for path in by_role.get("weather_json", []):
        shutil.copy2(path, gis / WEATHER_NAME)
        placed["weather"] = WEATHER_NAME
        sources.append(f"Weather from upload ({path.name})")
        break

    for path in by_role.get("weather_csv", []):
        try:
            payload = _csv_to_weather_json(path)
            (gis / WEATHER_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            placed["weather"] = WEATHER_NAME
            sources.append(f"Weather from CSV ({path.name})")
            break
        except Exception as exc:
            steps.append({"step": "weather_csv", "ok": False, "error": safe_text(str(exc))})

    steps.append({"step": "placed_files", "placed": placed, "sources": sources})

    if "boundary" not in placed:
        return {
            "ok": False,
            "error": "Could not find a field boundary in your upload. Include GeoJSON, shapefile, or draw on Maps.",
            "steps": steps,
            "missing": inspection.get("summary", {}).get("missing_for_gis_build"),
        }

    boundary_data = json.loads((gis / BOUNDARY_NAME).read_text(encoding="utf-8"))
    if boundary_data.get("type") == "Feature":
        boundary_data = {"type": "FeatureCollection", "features": [boundary_data]}
    boundary_info = data_download_service.save_boundary(farm_id, boundary_data)

    if "dem" not in placed:
        return {
            "ok": False,
            "error": "No elevation (DEM) file found. Upload a .tif DEM or use online download.",
            "steps": steps,
        }

    if "weather" not in placed:
        steps.append({"step": "weather", "ok": False, "note": "No weather file — trying online download for boundary area"})
        try:
            fetch = data_download_service.fetch_online_data(farm_id)
            if fetch.get("ok"):
                placed["weather"] = WEATHER_NAME
                sources.append("Weather from Open-Meteo (filled missing upload)")
                steps.append({"step": "weather_download", "ok": True})
            else:
                return {"ok": False, "error": fetch.get("error", "Weather missing"), "steps": steps}
        except Exception as exc:
            return {"ok": False, "error": safe_text(str(exc)), "steps": steps}

    if "soil" not in placed:
        try:
            fetch = data_download_service.fetch_online_data(farm_id)
            if fetch.get("ok") and (gis / SOIL_NAME).exists():
                placed["soil"] = SOIL_NAME
                sources.append("Soil from SoilGrids (filled missing upload)")
        except Exception:
            pass

    if "landuse" not in placed:
        try:
            gdf = gpd.GeoDataFrame.from_features(boundary_data.get("features", []), crs="EPSG:4326")
            data_download_service._create_landuse_from_boundary(gdf, gis / DEM_NAME, gis / LANDUSE_NAME)
            placed["landuse"] = LANDUSE_NAME
            sources.append("Land use from boundary (cropland)")
        except Exception as exc:
            steps.append({"step": "landuse", "ok": False, "error": safe_text(str(exc))})

    center = boundary_info.get("center", {})
    _write_data_manifest(
        gis,
        sources + ["Imported from user file upload"],
        (center.get("lat", 0), center.get("lon", 0)),
    )
    steps.append({"step": "manifest", "ok": True})

    if not run_build:
        return {"ok": True, "message": "Files sorted into field dataset.", "steps": steps, "placed": placed}

    build = build_farm_model_from_downloads(farm_id)
    steps.append({"step": "build", **{k: build.get(k) for k in ("ok", "error", "hru_count", "message")}})
    if not build.get("ok"):
        return {"ok": False, "error": build.get("error"), "steps": steps, "placed": placed}

    crop_service.apply_saved_crop_to_txtinout(farm_id)
    farm_row = db_one("SELECT soil_type FROM farms WHERE id = ?", (farm_id,)) or {}
    update_farm(farm_id, data_source="upload_verified", soil_type=farm_row.get("soil_type"))

    readiness = readiness_service.get_farm_readiness(farm_id)
    return {
        "ok": True,
        "message": "Sorted your uploaded files and built a SWAT+ field model.",
        "placed": placed,
        "sources": sources,
        "hru_count": build.get("hru_count"),
        "steps": steps,
        "ready_to_simulate": readiness.get("ready_to_simulate"),
        "readiness": readiness,
    }


def setup_from_uploaded_files(farm_id: str, run_first_simulation: bool = False) -> dict[str, Any]:
    """Inspect inbox → import → optional first simulation."""
    from services.field_setup_service import auto_setup_field_for_swat

    result = import_inbox_for_swat(farm_id, run_build=True)
    if not result.get("ok"):
        return result
    if run_first_simulation and result.get("ready_to_simulate"):
        sim = auto_setup_field_for_swat(farm_id, run_first_simulation=True)
        result["simulation"] = sim
    return result


def _txtinout_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any((path / m).exists() for m in TXTINOUT_MARKERS)


def _inbox_file_count(farm_id: str) -> int:
    inspection = inspect_inbox(farm_id)
    return int((inspection.get("summary") or {}).get("total_files") or 0)


def field_has_transferable_data(farm_id: str) -> dict[str, Any]:
    """Whether this field has inbox uploads and/or an imported SWAT+ setup to move."""
    inbox_files = _inbox_file_count(farm_id)
    txt_dir = config.farm_txtinout_dir(farm_id)
    has_txtinout = _txtinout_ready(txt_dir)
    gis = config.farm_gis_dir(farm_id)
    has_gis = gis.is_dir() and any(gis.iterdir())
    return {
        "farm_id": farm_id,
        "inbox_files": inbox_files,
        "has_txtinout": has_txtinout,
        "has_gis": has_gis,
        "should_transfer": inbox_files > 0 or has_txtinout or has_gis,
    }


def copy_field_setup(from_farm_id: str, to_farm_id: str) -> dict[str, Any]:
    """
    Copy inbox, GIS datasets, and TxtInOut from one field to another.
    Use when uploads or imports landed on the wrong field.
    """
    if from_farm_id == to_farm_id:
        return {"ok": False, "error": "Source and destination field are the same."}

    from_farm = db_one("SELECT * FROM farms WHERE id = ?", (from_farm_id,))
    to_farm = db_one("SELECT * FROM farms WHERE id = ?", (to_farm_id,))
    if not from_farm:
        return {"ok": False, "error": f"Source field not found: {from_farm_id}"}
    if not to_farm:
        return {"ok": False, "error": f"Destination field not found: {to_farm_id}"}

    info = field_has_transferable_data(from_farm_id)
    if not info.get("should_transfer"):
        return {
            "ok": False,
            "error": f"Field '{from_farm['name']}' has no uploaded files or SWAT+ setup to copy.",
        }

    copied: list[str] = []
    src_gis = config.farm_gis_dir(from_farm_id)
    dst_gis = config.farm_gis_dir(to_farm_id)
    if src_gis.is_dir() and any(src_gis.iterdir()):
        if dst_gis.exists():
            shutil.rmtree(dst_gis)
        shutil.copytree(src_gis, dst_gis)
        copied.append("gis_and_inbox")

    src_txt = Path(from_farm.get("txtinout_path") or config.farm_txtinout_dir(from_farm_id))
    dst_txt = config.farm_txtinout_dir(to_farm_id)
    if _txtinout_ready(src_txt):
        if dst_txt.exists():
            shutil.rmtree(dst_txt)
        shutil.copytree(src_txt, dst_txt)
        update_farm(
            to_farm_id,
            txtinout_path=str(dst_txt),
            data_source=from_farm.get("data_source") or "upload",
            setup_complete=from_farm.get("setup_complete") or 0,
            crop_type=from_farm.get("crop_type") or "",
            planting_date=from_farm.get("planting_date") or "",
        )
        crop_service.apply_saved_crop_to_txtinout(to_farm_id)
        copied.append("txtinout")

    if not copied:
        return {"ok": False, "error": "Nothing was copied — source field data may be missing on disk."}

    readiness = readiness_service.get_farm_readiness(to_farm_id)
    return {
        "ok": True,
        "from_farm_id": from_farm_id,
        "from_farm_name": from_farm["name"],
        "to_farm_id": to_farm_id,
        "to_farm_name": to_farm["name"],
        "copied": copied,
        "inbox_files": info.get("inbox_files", 0),
        "has_txtinout": info.get("has_txtinout", False),
        "ready_to_simulate": readiness.get("ready_to_simulate"),
        "message": (
            f"Copied setup from '{from_farm['name']}' to '{to_farm['name']}' "
            f"({', '.join(copied)})."
        ),
    }
