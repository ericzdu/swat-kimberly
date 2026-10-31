"""SWAT+ Editor routes — browse and edit raw TxtInOut input files."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import swat_editor_service as editor

router = APIRouter(prefix="/api/swat/editor", tags=["swat-editor"])


class FileWrite(BaseModel):
    name: str
    title: str = ""
    header: list[str] | None = None
    rows: list[list[str]] | None = None
    raw: str | None = None


@router.get("/{farm_id}/files")
def list_files(farm_id: str):
    return editor.list_files(farm_id)


@router.get("/{farm_id}/file")
def read_file(farm_id: str, name: str = Query(...)):
    try:
        result = editor.read_file(farm_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("/{farm_id}/file")
def write_file(farm_id: str, body: FileWrite):
    try:
        result = editor.write_file(
            farm_id, body.name, title=body.title,
            header=body.header, rows=body.rows, raw=body.raw,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Write failed"))
    return result


class SoilWrite(BaseModel):
    title: str = ""
    soils: list[dict]


@router.get("/{farm_id}/soil")
def read_soil(farm_id: str):
    try:
        result = editor.read_soil(farm_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("/{farm_id}/soil")
def write_soil(farm_id: str, body: SoilWrite):
    try:
        result = editor.write_soil(farm_id, body.soils, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Write failed"))
    return result
