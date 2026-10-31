"""Rich farm data status — setup progress, file trees, run outputs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import config
from db import db_exec, db_one
from services import data_service, readiness_service, pyswat_facade
from services.data_download_service import get_boundary_status, MANIFEST_NAME
from services.swat_service import swat


def _fmt_size(n: Optional[int]) -> str:
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _list_files(root: Path, prefix: str = "", depth: int = 0, max_depth: int = 2, limit: int = 80) -> list[dict]:
    if not root.exists() or depth > max_depth:
        return []
    items: list[dict] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    for entry in entries[:limit]:
        rel = f"{prefix}/{entry.name}" if prefix else entry.name
        if entry.is_dir():
            items.append({
                "name": entry.name,
                "path": rel,
                "kind": "dir",
                "size": None,
                "size_label": "",
            })
            if depth < max_depth:
                items.extend(_list_files(entry, rel, depth + 1, max_depth, limit - len(items)))
        else:
            try:
                sz = entry.stat().st_size
            except OSError:
                sz = None
            items.append({
                "name": entry.name,
                "path": rel,
                "kind": "file",
                "size": sz,
                "size_label": _fmt_size(sz),
                "previewable": entry.suffix.lower() in (
                    ".txt", ".dat", ".hru", ".cio", ".sim", ".cli", ".pcp", ".tem",
                    ".json", ".geojson", ".bsn", ".sol", ".plt", ".log", ".fin",
                ) and (sz or 0) < 2_000_000,
            })
        if len(items) >= limit:
            break
    return items


def _sub_dict(parent: dict, key: str) -> dict:
    val = parent.get(key)
    return val if isinstance(val, dict) else {}


def _setup_steps(readiness: dict, boundary: dict) -> list[dict]:
    if not isinstance(readiness, dict):
        readiness = {}
    if not isinstance(boundary, dict):
        boundary = {}
    checks = {c["id"]: c for c in readiness.get("checks", []) if isinstance(c, dict) and c.get("id")}
    steps = [
        {
            "id": "boundary",
            "label": "Farm boundary",
            "status": "ok" if boundary.get("has_boundary") else "missing",
            "detail": f"{boundary.get('area_ha', 0):.1f} ha saved" if boundary.get("has_boundary") else "Draw on Maps",
            "action": f"/gis?farm={readiness.get('farm_id')}",
        },
        {
            "id": "gis",
            "label": "Map layers (DEM, soil, land use)",
            "status": _sub_dict(checks, "gis").get("status", "missing"),
            "detail": _sub_dict(checks, "gis").get("detail", ""),
            "action": f"/gis?farm={readiness.get('farm_id')}",
        },
        {
            "id": "txtinout",
            "label": "Field model (TxtInOut)",
            "status": _sub_dict(checks, "txtinout").get("status", "missing"),
            "detail": _sub_dict(checks, "txtinout").get("detail", ""),
            "action": f"/setup?farm={readiness.get('farm_id')}",
        },
        {
            "id": "weather",
            "label": "Weather data",
            "status": _sub_dict(checks, "weather").get("status", "missing"),
            "detail": _sub_dict(checks, "weather").get("detail", ""),
            "action": f"/gis?farm={readiness.get('farm_id')}",
        },
        {
            "id": "simulation",
            "label": "First simulation run",
            "status": "ok" if _sub_dict(readiness, "last_run").get("status") == "completed" else (
                "warning" if readiness.get("ready_to_simulate") else "missing"
            ),
            "detail": (
                f"Completed {str(_sub_dict(readiness, 'last_run').get('completed_at', ''))[:10]}"
                if _sub_dict(readiness, "last_run").get("status") == "completed"
                else "Ready to run" if readiness.get("ready_to_simulate") else "Complete data first"
            ),
            "action": f"/setup?farm={readiness.get('farm_id')}",
        },
    ]
    return steps


def _progress_pct(steps: list[dict]) -> int:
    weights = {"ok": 1, "optional": 1, "warning": 0.5, "missing": 0}
    if not steps:
        return 0
    score = sum(weights.get(s["status"], 0) for s in steps)
    return int(round(100 * score / len(steps)))


def _load_manifest(gis_dir: Path) -> Optional[dict]:
    path = gis_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _runs_with_outputs(farm_id: str, limit: int = 15) -> list[dict]:
    rows = db_exec(
        """SELECT id, sim_type, status, results, created_at, completed_at
           FROM simulations WHERE farm_id = ? ORDER BY created_at DESC LIMIT ?""",
        (farm_id, limit),
    )
    runs: list[dict] = []
    for row in rows:
        r = dict(row)
        err = None
        if r.get("results"):
            try:
                data = json.loads(r["results"])
                if isinstance(data, dict) and data.get("error"):
                    err = data["error"]
            except json.JSONDecodeError:
                pass
        if r.get("status") == "failed" and not err:
            err = "Simulation failed"
        out_dir = config.run_output_dir(r["id"])
        output_files = swat.list_output_files(r["id"]) if out_dir.exists() else []
        runs.append({
            "run_id": r["id"],
            "sim_type": r.get("sim_type"),
            "status": r.get("status"),
            "error": err,
            "created_at": r.get("created_at"),
            "completed_at": r.get("completed_at"),
            "output_dir": str(out_dir) if out_dir.exists() else None,
            "output_files": output_files[:40],
            "output_count": len(output_files),
        })
    return runs


def get_farm_data_status(farm_id: str) -> dict[str, Any]:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"error": "Farm not found"}

    readiness = readiness_service.get_farm_readiness(farm_id)
    boundary = get_boundary_status(farm_id)
    inventory = data_service.get_farm_data_inventory(farm_id)
    gis_dir = config.farm_gis_dir(farm_id)
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    manifest = _load_manifest(gis_dir)

    steps = _setup_steps(readiness, boundary)
    progress = _progress_pct(steps)

    gis_layers = []
    for key, fname in [
        ("dem", "dem.tif"),
        ("soil", "soil.geojson"),
        ("landuse", "landuse.tif"),
        ("weather", "weather_openmeteo.json"),
        ("boundary", "boundary.geojson"),
    ]:
        p = gis_dir / fname
        gis_layers.append({
            "id": key,
            "file": fname,
            "exists": p.exists(),
            "size_label": _fmt_size(p.stat().st_size) if p.exists() else "",
        })

    return {
        "farm_id": farm_id,
        "farm_name": farm.get("name"),
        "data_source": farm.get("data_source") or "",
        "readiness": readiness,
        "setup": {
            "progress_pct": progress,
            "steps": steps,
            "ready_to_simulate": readiness.get("ready_to_simulate", False),
            "block_reason": readiness.get("block_reason") or "",
        },
        "boundary": boundary,
        "manifest": manifest,
        "gis_layers": gis_layers,
        "gis_dir": str(gis_dir),
        "txtinout_dir": str(txtinout),
        "txtinout_validation": inventory.get("txtinout_validation"),
        "files": {
            "gis": _list_files(gis_dir, max_depth=1),
            "txtinout": _list_files(txtinout, max_depth=1) if txtinout.exists() else [],
        },
        "runs": _runs_with_outputs(farm_id),
        "engine": swat.engine_status(),
    }


def resolve_safe_file_path(farm_id: str, zone: str, rel_path: str) -> Path:
    """Resolve a file under farm gis, txtinout, or run output — reject path traversal."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        raise ValueError("Farm not found")
    rel = Path(rel_path.replace("\\", "/").lstrip("/"))
    if ".." in rel.parts:
        raise ValueError("Invalid path")

    if zone == "gis":
        root = config.farm_gis_dir(farm_id).resolve()
    elif zone == "txtinout":
        root = data_service.resolve_farm_txtinout(farm_id, farm).resolve()
    elif zone.startswith("run:"):
        run_id = zone.split(":", 1)[1]
        row = db_one("SELECT farm_id FROM simulations WHERE id = ?", (run_id,))
        if not row or row["farm_id"] != farm_id:
            raise ValueError("Run not found")
        root = config.run_output_dir(run_id).resolve()
    else:
        raise ValueError("Unknown zone")

    target = (root / rel).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Path outside allowed directory")
    if not target.is_file():
        raise ValueError("File not found")
    return target


def preview_file(farm_id: str, zone: str, rel_path: str, max_lines: int = 120) -> dict:
    path = resolve_safe_file_path(farm_id, zone, rel_path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("File too large to preview")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    truncated = len(lines) > max_lines
    return {
        "path": rel_path,
        "zone": zone,
        "size": path.stat().st_size,
        "lines": lines[:max_lines],
        "truncated": truncated,
        "total_lines": len(lines),
    }
