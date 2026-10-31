"""Widget interaction — the single resume door for the generative-UI canvas.

A widget submission becomes a deterministic synthetic message that re-runs the
existing agent path (chat_service.run_interaction). No ToolMessage injection.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from services.chat_service import run_interaction

router = APIRouter(prefix="/api", tags=["interact"])


class InteractRequest(BaseModel):
    farm_id: str
    session_id: str
    widget_id: str
    kind: str
    data: dict = {}
    provider: str = ""
    model: str = ""


@router.post("/interact")
def interact(req: InteractRequest):
    return run_interaction(
        farm_id=req.farm_id,
        session_id=req.session_id,
        widget_id=req.widget_id,
        kind=req.kind,
        data=req.data or {},
        provider=req.provider or None,
        model=req.model or None,
    )
