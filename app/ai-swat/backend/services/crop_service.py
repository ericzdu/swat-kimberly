"""In-app crop settings — no external QSWAT+ required."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from db import db_one, update_farm
from services import data_service

CROP_CATALOG: list[dict[str, str]] = [
    {"id": "corn", "label": "Corn", "swat_plt": "corn", "lum": "corn"},
    {"id": "wheat", "label": "Wheat", "swat_plt": "wheat", "lum": "whea"},
    {"id": "soybeans", "label": "Soybeans", "swat_plt": "soyb", "lum": "soyb"},
    {"id": "cotton", "label": "Cotton", "swat_plt": "cotton", "lum": "cott"},
    {"id": "alfalfa", "label": "Alfalfa", "swat_plt": "alfa", "lum": "alfa"},
    {"id": "sorghum", "label": "Sorghum", "swat_plt": "sorg", "lum": "sorg"},
    {"id": "barley", "label": "Barley", "swat_plt": "barl", "lum": "barl"},
]

_CROP_BY_ID = {c["id"]: c for c in CROP_CATALOG}

_SWAT_PLT_TO_ID = {
    "alfa": "alfalfa",
    "corn": "corn",
    "wheat": "wheat",
    "whea": "wheat",
    "soyb": "soybeans",
    "cott": "cotton",
    "sorg": "sorghum",
    "barl": "barley",
}


def list_crop_options() -> list[dict[str, str]]:
    return [{"id": c["id"], "label": c["label"]} for c in CROP_CATALOG]


def get_crop_settings(farm_id: str) -> dict[str, Any]:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"error": "Farm not found"}
    crop_type = (farm.get("crop_type") or "").strip()
    planting_date = (farm.get("planting_date") or "").strip()
    meta = _CROP_BY_ID.get(crop_type, {})
    return {
        "farm_id": farm_id,
        "crop_type": crop_type,
        "crop_label": meta.get("label", ""),
        "planting_date": planting_date,
        "configured": bool(crop_type and planting_date),
        "setup_path": f"/setup?farm={farm_id}",
        "options": list_crop_options(),
    }


def is_crop_configured(farm: dict) -> bool:
    return bool((farm.get("crop_type") or "").strip() and (farm.get("planting_date") or "").strip())


def read_crop_from_txtinout(txtinout: Path) -> dict[str, str]:
    """Read crop from plant.ini in an uploaded SWAT+ project."""
    plant_ini = txtinout / "plant.ini"
    if not plant_ini.exists():
        return {}
    text = plant_ini.read_text(encoding="utf-8", errors="replace").lower()
    crop_id = ""
    for plt, cid in _SWAT_PLT_TO_ID.items():
        if re.search(rf"\b{re.escape(plt)}\b", text):
            crop_id = cid
            break
    if not crop_id:
        return {}
    meta = _CROP_BY_ID.get(crop_id, {})
    planting = _planting_date_from_txtinout(txtinout)
    return {
        "crop_type": crop_id,
        "crop_label": meta.get("label", crop_id),
        "planting_date": planting,
    }


def crop_in_txtinout(txtinout: Path) -> bool:
    return bool(read_crop_from_txtinout(txtinout).get("crop_type"))


def _planting_date_from_txtinout(txtinout: Path) -> str:
    time_sim = txtinout / "time.sim"
    if time_sim.exists():
        for line in time_sim.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                for token in parts[1:]:
                    if token.isdigit() and len(token) == 4:
                        return f"{token}-04-01"
    return "2005-04-01"


def sync_crop_from_txtinout(farm_id: str) -> dict[str, Any]:
    """Copy crop details from plant.ini into the farm record (does not overwrite plant.ini)."""
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"ok": False, "error": "Farm not found"}
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    inferred = read_crop_from_txtinout(txtinout)
    if not inferred.get("crop_type"):
        return {"ok": False, "configured": False}
    if is_crop_configured(farm):
        return {"ok": True, "configured": True, "message": "Crop already set", **get_crop_settings(farm_id)}
    update_farm(
        farm_id,
        crop_type=inferred["crop_type"],
        planting_date=inferred["planting_date"],
    )
    settings = get_crop_settings(farm_id)
    return {
        "ok": True,
        "configured": True,
        "message": f"Detected {inferred['crop_label']} from your uploaded SWAT+ project.",
        **settings,
    }


def save_crop_settings(farm_id: str, crop_type: str, planting_date: str) -> dict[str, Any]:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return {"ok": False, "error": "Farm not found"}

    crop_type = crop_type.strip().lower()
    planting_date = planting_date.strip()
    if crop_type not in _CROP_BY_ID:
        labels = ", ".join(c["label"] for c in CROP_CATALOG)
        return {"ok": False, "error": f"Choose a crop: {labels}"}
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", planting_date):
        return {"ok": False, "error": "Planting date must be YYYY-MM-DD."}

    update_farm(farm_id, crop_type=crop_type, planting_date=planting_date)
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    apply_msg = ""
    if txtinout.exists():
        try:
            _apply_crop_to_txtinout(txtinout, _CROP_BY_ID[crop_type])
            apply_msg = " Field model updated with your crop."
        except Exception as exc:
            apply_msg = f" Saved crop details, but could not update field model: {exc}"

    settings = get_crop_settings(farm_id)
    return {
        "ok": True,
        "message": f"Crop set to {_CROP_BY_ID[crop_type]['label']} planted {planting_date}.{apply_msg}",
        **settings,
    }


def _patch_hru_landuse(line: str, lum_code: str) -> str:
    if not line.strip().startswith("1."):
        return line
    parts = line.split("|")
    if len(parts) < 6:
        return line
    parts[4] = f" {lum_code[:4].ljust(4)} "
    return "|".join(parts)


def _apply_crop_to_txtinout(txtinout: Path, crop: dict[str, str]) -> None:
    plt = crop["swat_plt"]
    lum = crop["lum"][:4]
    comm = f"{plt}_comm"

    plant_ini = txtinout / "plant.ini"
    plant_ini.write_text(
        "plant.ini: AI-SWAT+ crop settings\n"
        "pcom_name          plt_cnt  rot_yr_ini          plt_name     lc_status      lai_init       bm_init      phu_init      plnt_pop      yrs_init      rsd_init  \n"
        f"{comm:<21}        1         1  \n"
        f"                                        {plt:<12}     n       0.00000       0.00000       0.00000       0.00000       0.00000   10000.00000  \n",
        encoding="utf-8",
    )

    lum_path = txtinout / "landuse.lum"
    if lum_path.exists():
        lines = lum_path.read_text(encoding="utf-8", errors="replace").splitlines()
        header = lines[0] if lines else "landuse.lum"
        body = [ln for ln in lines[1:] if ln.strip() and not ln.strip().startswith(f"{lum}_lum")]
        row_name = f"{lum}_lum"
        body.append(
            f"{row_name:<28}          null         {comm:<39}                                       null      rowc_grow_g       cross_slope              null              null      convtill_res              null              null              null              null              null  "
        )
        lum_path.write_text(header + "\n" + "\n".join(body) + "\n", encoding="utf-8")

    hru_path = txtinout / "hru-data.hru"
    if hru_path.exists():
        lines = hru_path.read_text(encoding="utf-8", errors="replace").splitlines()
        hru_path.write_text(
            "\n".join(_patch_hru_landuse(ln, lum) for ln in lines),
            encoding="utf-8",
        )


def apply_saved_crop_to_txtinout(farm_id: str) -> None:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm or not is_crop_configured(farm):
        return
    txtinout = data_service.resolve_farm_txtinout(farm_id, farm)
    if txtinout.exists():
        _apply_crop_to_txtinout(txtinout, _CROP_BY_ID[farm["crop_type"]])


def crop_setup_message(farm_id: str) -> str:
    return (
        "Open **Setup** in AI-SWAT+, find **Crop details**, choose your crop and planting date, "
        f"then save. Link: /setup?farm={farm_id}. Do not use QSWAT+ — everything is done in this app."
    )
