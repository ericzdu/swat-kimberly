"""Delete a field (farm) completely — DB rows AND on-disk data.

The plain `db.delete_farm` only removes the farms/messages/chat_sessions rows,
which leaves the field's TxtInOut, GIS, observed, and run-output folders behind
as orphans. This removes both so a deleted field leaves nothing behind.
"""
from __future__ import annotations

import logging
import shutil

import config
from db import db_exec, delete_farm

logger = logging.getLogger(__name__)


def delete_field(farm_id: str) -> dict:
    if not farm_id:
        return {"ok": False, "error": "No field id"}

    # 1) Remove each run's archived output folder, then the simulation rows.
    removed_output_dirs = 0
    try:
        sims = db_exec("SELECT id FROM simulations WHERE farm_id = ?", (farm_id,))
        for s in sims:
            out = config.run_output_dir(s["id"])
            if out.exists():
                shutil.rmtree(out, ignore_errors=True)
                removed_output_dirs += 1
        db_exec("DELETE FROM simulations WHERE farm_id = ?", (farm_id,))
    except Exception as exc:
        logger.warning("delete_field: sim cleanup for %s failed: %s", farm_id, exc)

    # 2) Remove DB rows (messages, chat_sessions, farms).
    delete_farm(farm_id)

    # 3) Remove the field's on-disk data folders.
    removed_dirs = []
    for d in (
        config.farm_txtinout_dir(farm_id).parent,  # DATA_ROOT/farms/{id}
        config.farm_gis_dir(farm_id),              # DATA_ROOT/gis/{id}
        config.farm_observed_dir(farm_id),         # DATA_ROOT/observed/{id}
    ):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed_dirs.append(d.name)

    return {"ok": True, "removed_output_dirs": removed_output_dirs, "removed_data_dirs": removed_dirs}
