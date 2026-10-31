"""Chat routes — LangGraph agent + LLM fallback + saved sessions."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import chat_session_service
from services.chat_service import get_chat_ai_status, run_agent_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    farm_id: str
    message: str
    session_id: str = ""
    provider: str = ""
    model: str = ""
    use_agent: bool = True


class CreateSessionRequest(BaseModel):
    farm_id: str
    title: str = "New chat"


@router.get("/status")
def chat_ai_status():
    return get_chat_ai_status()


@router.get("/sessions")
def list_chat_sessions(farm_id: str = Query(...)):
    return chat_session_service.list_sessions(farm_id)


@router.post("/sessions")
def create_chat_session(req: CreateSessionRequest):
    return chat_session_service.create_session(req.farm_id, title=req.title or "New chat")


@router.get("/sessions/{session_id}")
def get_chat_session_messages(session_id: str):
    result = chat_session_service.load_session_messages(session_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/sessions/{session_id}")
def delete_chat_session(session_id: str):
    result = chat_session_service.remove_session(session_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("")
def send_chat(req: ChatRequest):
    return run_agent_chat(
        req.farm_id,
        req.message,
        provider=req.provider or None,
        model=req.model or None,
        use_agent=req.use_agent,
        session_id=req.session_id or None,
    )
