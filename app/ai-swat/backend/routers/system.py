"""LLM provider and settings routes."""
from fastapi import APIRouter
from pydantic import BaseModel

from db import get_setting
from services.llm_service import (
    get_saved_config,
    list_providers_for_api,
    llm,
    provider_health,
    save_api_keys,
    save_config,
    test_provider,
)

router = APIRouter(prefix="/api/system", tags=["system"])


class SettingsSave(BaseModel):
    provider: str
    model: str


class KeysSave(BaseModel):
    groq: str = ""
    openai: str = ""
    anthropic: str = ""
    openrouter: str = ""
    minimax: str = ""


@router.get("/ping")
def ping():
    return {"ok": True, "service": "ai-swat-api"}


@router.get("/status")
def system_status():
    """Single call for Settings page — backend, providers, and AI readiness."""
    from services.chat_service import get_chat_ai_status
    return {
        "backend": {"ok": True},
        "ai": get_chat_ai_status(),
        "providers": list_providers_for_api(),
        "settings": get_saved_config(),
    }


@router.get("/providers")
def get_providers():
    return list_providers_for_api()


@router.get("/health")
def health_check():
    return provider_health()


@router.get("/settings")
def get_settings():
    return get_saved_config()


@router.post("/settings")
def save_settings(settings: SettingsSave):
    save_config(settings.provider, settings.model)
    return {"ok": True}


@router.post("/test")
def test_provider_route(body: dict):
    return test_provider(body.get("provider", ""), body.get("model") or None)


@router.post("/keys")
def save_keys(keys: KeysSave):
    from utils.text import is_plausible_api_key, sanitize_api_key
    data = keys.model_dump()
    rejected = [name for name, val in data.items() if val.strip() and not is_plausible_api_key(sanitize_api_key(val))]
    save_api_keys(data)
    if rejected:
        return {
            "ok": False,
            "error": f"Invalid API key for {', '.join(rejected)}. Paste the key from the provider website, not an error message.",
        }
    return {"ok": True}
