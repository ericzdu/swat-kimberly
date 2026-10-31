"""Chat session list, load, and create."""
from __future__ import annotations

from typing import Any

from db import (
    create_chat_session,
    delete_chat_session,
    get_chat_session,
    get_session_messages,
    list_chat_sessions,
)


def list_sessions(farm_id: str) -> list[dict[str, Any]]:
    sessions = list_chat_sessions(farm_id)
    return [
        {
            "id": s["id"],
            "farm_id": s["farm_id"],
            "title": s["title"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
            "message_count": int(s.get("message_count") or 0),
            "last_preview": (s.get("last_preview") or "")[:120],
        }
        for s in sessions
    ]


def create_session(farm_id: str, title: str = "New chat") -> dict[str, Any]:
    session = create_chat_session(farm_id, title=title)
    return {
        "id": session["id"],
        "farm_id": session["farm_id"],
        "title": session["title"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "message_count": 0,
        "last_preview": "",
    }


def load_session_messages(session_id: str) -> dict[str, Any]:
    session = get_chat_session(session_id)
    if not session:
        return {"error": "Session not found"}
    messages = get_session_messages(session_id)
    return {
        "session": {
            "id": session["id"],
            "farm_id": session["farm_id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "message_count": len(messages),
        },
        "messages": messages,
    }


def remove_session(session_id: str) -> dict[str, Any]:
    if not delete_chat_session(session_id):
        return {"ok": False, "error": "Session not found"}
    return {"ok": True}
