"""LangGraph tool listing — for API discovery."""
from fastapi import APIRouter

from agent.tool_factory import build_farm_tools

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/tools")
def list_agent_tools():
    # Sample farm_id for schema discovery — real agent uses farm-scoped tools at runtime
    tools = build_farm_tools("sample-farm-id")
    return [
        {
            "name": t.name,
            "description": t.description,
            "args_schema": t.args_schema.model_json_schema() if t.args_schema else {},
        }
        for t in tools
    ]
