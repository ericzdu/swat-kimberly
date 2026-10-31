"""File registration and listing under DATA_ROOT."""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import config
from services import pyswat_facade


def _list_dir(path: Path, limit: int = 100) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for entry in sorted(path.iterdir())[:limit]:
        items.append({
            "name": entry.name,
            "path": str(entry),
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else None,
        })
    return items


def register_gis_paths(farm_id: str, paths: dict) -> dict:
    gis_dir = config.farm_gis_dir(farm_id)
    gis_dir.mkdir(parents=True, exist_ok=True)
    registered = {}
    for key, rel in paths.items():
        if not rel:
            continue
        full = config.resolve_data_path(rel)
        if not full.exists():
            registered[key] = {"path": str(full), "exists": False}
        else:
            registered[key] = {"path": str(full), "exists": True}
    meta_path = gis_dir / "registered.json"
    meta_path.write_text(json.dumps(registered, indent=2))
    return {"farm_id": farm_id, "gis_dir": str(gis_dir), "layers": registered}


def register_observed_paths(farm_id: str, files: dict) -> dict:
    obs_dir = config.farm_observed_dir(farm_id)
    obs_dir.mkdir(parents=True, exist_ok=True)
    registered = {}
    for name, rel in files.items():
        full = config.resolve_data_path(rel)
        registered[name] = {"path": str(full), "exists": full.exists()}
    meta_path = obs_dir / "registered.json"
    meta_path.write_text(json.dumps(registered, indent=2))
    return {"farm_id": farm_id, "observed_dir": str(obs_dir), "files": registered}


def get_farm_data_inventory(farm_id: str) -> dict:
    txtinout = config.farm_txtinout_dir(farm_id)
    validation = pyswat_facade.validate_txtinout(txtinout) if txtinout.exists() else None
    return {
        "farm_id": farm_id,
        "gis_dir": str(config.farm_gis_dir(farm_id)),
        "gis_files": _list_dir(config.farm_gis_dir(farm_id)),
        "txtinout_dir": str(txtinout),
        "txtinout_validation": validation,
        "observed_dir": str(config.farm_observed_dir(farm_id)),
        "observed_files": _list_dir(config.farm_observed_dir(farm_id)),
    }


def resolve_farm_txtinout(farm_id: str, farm_record: Optional[dict] = None) -> Path:
    if farm_record and farm_record.get("txtinout_path"):
        p = Path(farm_record["txtinout_path"])
        if p.is_dir():
            return p
    default = config.farm_txtinout_dir(farm_id)
    return default


def save_upload(dest_dir: Path, filename: str, content: bytes) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / os.path.basename(filename)
    dest.write_bytes(content)
    return str(dest)


def extract_txtinout_zip(farm_id: str, content: bytes) -> dict:
    """Extract a TxtInOut zip into the farm's TxtInOut directory."""
    dest = config.farm_txtinout_dir(farm_id)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(BytesIO(content)) as zf:
        names = zf.namelist()
        # If zip contains a TxtInOut subfolder, extract into dest; else extract all to dest
        prefix = ""
        for name in names:
            parts = name.replace("\\", "/").split("/")
            if "TxtInOut" in parts:
                idx = parts.index("TxtInOut")
                prefix = "/".join(parts[: idx + 1]) + "/"
                break
        for name in names:
            if name.endswith("/"):
                continue
            data = zf.read(name)
            rel = name.replace("\\", "/")
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            elif prefix:
                continue
            # Skip nested path prefix if single top-level folder
            parts = rel.split("/")
            if len(parts) > 1 and parts[0] not in ("file.cio", "hru-data.hru"):
                rel = "/".join(parts[1:]) if parts[0] else rel
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    validation = pyswat_facade.validate_txtinout(dest)
    return {
        "farm_id": farm_id,
        "txtinout_dir": str(dest),
        "validation": validation,
        "ready": validation.get("valid", False),
    }


def copy_demo_txtinout(farm_id: str) -> dict:
    """Copy bundled a10 demo project into farm TxtInOut."""
    src = config.demo_txtinout_source()
    if not src.is_dir() or not (src / "file.cio").exists():
        return {
            "farm_id": farm_id,
            "error": f"Demo project not found at {src}",
            "ready": False,
        }
    dest = config.farm_txtinout_dir(farm_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    validation = pyswat_facade.validate_txtinout(dest)
    return {
        "farm_id": farm_id,
        "txtinout_dir": str(dest),
        "validation": validation,
        "ready": validation.get("valid", False),
        "source": "demo",
    }
