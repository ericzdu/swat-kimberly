"""
Unified LLM integration — Ollama (local) and cloud APIs for agent + simple chat.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from db import get_setting, save_setting
from utils.text import safe_text, is_plausible_api_key, sanitize_api_key

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# MiniMax's Anthropic-compatible endpoint. Do NOT fall back to ANTHROPIC_BASE_URL —
# that env var targets the real Anthropic provider, and using it here sends the
# MiniMax key to api.anthropic.com (→ 401). Only MINIMAX_BASE_URL may override.
MINIMAX_ANTHROPIC_BASE = (
    os.environ.get("MINIMAX_BASE_URL")
    or "https://api.minimax.io/anthropic"
)

# Models known to support LangChain / Ollama tool calling well
OLLAMA_TOOL_MODELS = ("llama3.1", "llama3.2", "llama3.3", "qwen2.5", "qwen3", "mistral", "mixtral", "command-r")

PROVIDERS = ["ollama", "groq", "openai", "anthropic", "openrouter", "minimax"]

PROVIDER_LABELS = {
    "ollama": "Ollama (Local)",
    "groq": "Groq",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "openrouter": "OpenRouter",
    "minimax": "MiniMax",
}

PROVIDER_MODELS: dict[str, list[str]] = {
    "ollama": [],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-7"],
    "openrouter": [
        "openrouter/auto",
        "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet",
        "meta-llama/llama-3.3-70b-instruct",
    ],
    "minimax": [
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M3",
        "MiniMax-M2",
    ],
}

DEFAULT_MODELS = {
    "ollama": "llama3.2",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "openrouter": "openrouter/auto",
    "minimax": "MiniMax-M2.5",
}


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    latency_ms: float


class LLMConfigError(Exception):
    def __init__(self, message: str):
        super().__init__(safe_text(message))


def get_api_key(provider: str) -> str:
    if provider == "openai":
        raw = get_setting("api_key_openai", "") or os.environ.get("OPENAI_API_KEY", "")
    elif provider == "minimax":
        # Never fall back to ANTHROPIC_API_KEY — a stray Anthropic key would be sent
        # to MiniMax (or vice-versa). MiniMax uses its own key only.
        raw = (
            get_setting("api_key_minimax", "")
            or os.environ.get("MINIMAX_API_KEY", "")
        )
    else:
        raw = get_setting(f"api_key_{provider}", "")
    key = sanitize_api_key(raw)
    if raw and not is_plausible_api_key(key):
        return ""
    return key


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split system prompts from user/assistant turns for Anthropic API."""
    system_parts: list[str] = []
    turns: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(str(content))
        elif role in ("user", "assistant"):
            turns.append({"role": role, "content": str(content)})
    if not turns:
        turns = [{"role": "user", "content": "Hello"}]
    return "\n\n".join(system_parts), turns


def _anthropic_text(content_blocks) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def _anthropic_chat(api_key: str, model: str, messages: list[dict], base_url: str) -> str:
    from anthropic import Anthropic

    system, turns = _to_anthropic_messages(messages)
    client = Anthropic(api_key=api_key, base_url=base_url)
    kwargs: dict[str, Any] = {"model": model, "max_tokens": 1024, "messages": turns}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return _anthropic_text(resp.content) or "No response from model."


def get_saved_config() -> dict[str, str]:
    return {
        "provider": get_setting("provider", "ollama"),
        "model": get_setting("model", ""),
    }


def save_config(provider: str, model: str) -> None:
    save_setting("provider", provider)
    save_setting("model", model)


def save_api_keys(keys: dict[str, str]) -> None:
    for key, value in keys.items():
        cleaned = sanitize_api_key(value)
        if cleaned and is_plausible_api_key(cleaned):
            save_setting(f"api_key_{key}", cleaned)


def list_ollama_models(refresh: bool = False) -> list[dict[str, Any]]:
    cache_key = "_ollama_cache"
    if not refresh and hasattr(list_ollama_models, cache_key):
        return getattr(list_ollama_models, cache_key)
    try:
        import socket
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(4)
        try:
            import ollama
            client = ollama.Client(host=OLLAMA_HOST)
            resp = client.list()
            models = [{"name": m["name"], "size": m.get("size", 0)} for m in resp.get("models", [])]
        finally:
            socket.setdefaulttimeout(old)
    except Exception as exc:
        logger.debug("Ollama list failed: %s", exc)
        models = []
    setattr(list_ollama_models, cache_key, models)
    return models


def resolve_provider_model(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[str, str]:
    saved = get_saved_config()
    provider = (provider or saved["provider"] or "ollama").strip().lower()
    if provider not in PROVIDERS:
        raise LLMConfigError(f"Unknown provider: {provider}")

    if provider == "ollama":
        ollama_models = [m["name"] for m in list_ollama_models()]
        if not ollama_models:
            raise LLMConfigError(
                "Ollama is not running or has no models. "
                "Install Ollama, run `ollama pull llama3.2`, then try again."
            )
        model = (model or saved["model"] or "").strip()
        if not model:
            model = ollama_models[0]
        elif model not in ollama_models:
            match = next(
                (m for m in ollama_models if m.startswith(model) or model.startswith(m.split(":")[0])),
                None,
            )
            if match:
                model = match
            else:
                raise LLMConfigError(
                    f"Model '{model}' not found in Ollama. Available: {', '.join(ollama_models[:5])}"
                )
        return provider, model

    model = (model or saved["model"] or DEFAULT_MODELS.get(provider, "")).strip()
    if not model:
        raise LLMConfigError(f"No model selected for {provider}")
    if provider != "ollama" and not get_api_key(provider):
        raise LLMConfigError(
            f"No valid API key for {PROVIDER_LABELS.get(provider, provider)}. "
            f"Paste your key in Settings (Step 2) and click Save."
        )
    return provider, model


def build_langchain_llm(provider: str, model: str):
    """Build LangChain chat model for the LangGraph agent."""
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model,
            temperature=0,
            base_url=OLLAMA_HOST,
            num_ctx=8192,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        key = get_api_key("openai")
        if not key:
            raise LLMConfigError("OpenAI API key not set")
        return ChatOpenAI(model=model, temperature=0, api_key=key)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        key = get_api_key("anthropic")
        if not key:
            raise LLMConfigError("Anthropic API key not set")
        return ChatAnthropic(model=model, max_tokens=1024, api_key=key)

    if provider == "groq":
        from langchain_openai import ChatOpenAI
        key = get_api_key("groq")
        if not key:
            raise LLMConfigError("Groq API key not set")
        return ChatOpenAI(
            model=model,
            temperature=0,
            api_key=key,
            base_url="https://api.groq.com/openai/v1",
        )

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        key = get_api_key("openrouter")
        if not key:
            raise LLMConfigError("OpenRouter API key not set")
        return ChatOpenAI(
            model=model,
            temperature=0,
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "http://localhost:8000", "X-Title": "AI-SWAT+"},
        )

    if provider == "minimax":
        from langchain_anthropic import ChatAnthropic
        key = get_api_key("minimax")
        if not key:
            raise LLMConfigError("MiniMax API key not set")
        return ChatAnthropic(
            model=model,
            max_tokens=1024,
            temperature=0,
            api_key=key,
            base_url=MINIMAX_ANTHROPIC_BASE,
        )

    raise LLMConfigError(f"Unsupported provider: {provider}")


def simple_chat(provider: str, model: str, messages: list[dict]) -> LLMResponse:
    """Direct chat without tools — fallback when agent unavailable."""
    start = time.time()
    api_key = get_api_key(provider)

    if provider == "ollama":
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
        resp = client.chat(
            model=model,
            messages=messages,
            options={"num_predict": 1024, "temperature": 0.3},
        )
        return LLMResponse(
            content=resp["message"]["content"],
            provider=provider,
            model=model,
            latency_ms=(time.time() - start) * 1000,
        )

    if provider == "groq":
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(model=model, messages=messages)
        content = resp.choices[0].message.content or ""
        return LLMResponse(content, provider, model, (time.time() - start) * 1000)

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(model=model, messages=messages)
        content = resp.choices[0].message.content or ""
        return LLMResponse(content, provider, model, (time.time() - start) * 1000)

    if provider == "anthropic":
        content = _anthropic_chat(api_key, model, messages, "https://api.anthropic.com")
        return LLMResponse(content, provider, model, (time.time() - start) * 1000)

    if provider == "minimax":
        content = _anthropic_chat(api_key, model, messages, MINIMAX_ANTHROPIC_BASE)
        return LLMResponse(content, provider, model, (time.time() - start) * 1000)

    if provider == "openrouter":
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "http://localhost:8000", "X-Title": "AI-SWAT+"},
        )
        resp = client.chat.completions.create(model=model, messages=messages)
        content = resp.choices[0].message.content or ""
        return LLMResponse(content, provider, model, (time.time() - start) * 1000)

    raise LLMConfigError(f"Unsupported provider: {provider}")


def provider_health() -> dict[str, str]:
    status = {p: "offline" for p in PROVIDERS}
    ollama_models = list_ollama_models()
    if ollama_models:
        status["ollama"] = "online"
    else:
        status["ollama"] = "offline"
    for p in PROVIDERS:
        if p == "ollama":
            continue
        if get_api_key(p):
            status[p] = "configured"
    return status


def get_ai_status() -> dict[str, Any]:
    saved = get_saved_config()
    health = provider_health()
    ollama_models = list_ollama_models()
    provider = saved.get("provider", "ollama")
    configured = False
    message = ""

    try:
        resolve_provider_model(provider, saved.get("model"))
        configured = True
        message = "AI ready"
    except LLMConfigError as exc:
        message = safe_text(str(exc))

    return {
        "configured": configured,
        "message": message,
        "provider": provider,
        "model": saved.get("model", ""),
        "health": health,
        "ollama_host": OLLAMA_HOST,
        "ollama_models": [m["name"] for m in ollama_models],
        "tool_calling_recommended": [
            m for m in [x["name"] for x in ollama_models]
            if any(tag in m.lower() for tag in OLLAMA_TOOL_MODELS)
        ],
    }


def list_providers_for_api() -> list[dict[str, Any]]:
    ollama_models = [m["name"] for m in list_ollama_models(refresh=True)]
    health = provider_health()
    result = []
    for provider in PROVIDERS:
        models = ollama_models if provider == "ollama" else PROVIDER_MODELS.get(provider, [])
        has_key = provider == "ollama" or is_plausible_api_key(get_api_key(provider) or sanitize_api_key(get_setting(f"api_key_{provider}", "")))
        status = health.get(provider, "offline")
        result.append({
            "id": provider,
            "label": PROVIDER_LABELS[provider],
            "models": models,
            "has_api_key": has_key,
            "status": status,
            "ready": status in ("online", "configured"),
            "kind": "local" if provider == "ollama" else "cloud",
            "default_model": DEFAULT_MODELS.get(provider, ""),
        })
    return result


def test_provider(provider: str, model: Optional[str] = None) -> dict[str, Any]:
    try:
        provider, model = resolve_provider_model(provider, model)
    except LLMConfigError as exc:
        return {"ok": False, "error": safe_text(exc)}

    messages = [{"role": "user", "content": "Reply with exactly: test OK"}]
    try:
        resp = simple_chat(provider, model, messages)
        ok = "test" in resp.content.lower()
        return {"ok": ok, "error": None if ok else f"Unexpected reply: {resp.content[:80]}"}
    except Exception as exc:
        return {"ok": False, "error": safe_text(exc)}


class LLMService:
    """Backward-compatible facade used by system router."""

    def get_ollama_models(self) -> list[dict]:
        return list_ollama_models()

    def chat(self, provider: str, model: str, messages: list) -> LLMResponse:
        provider, model = resolve_provider_model(provider, model)
        return simple_chat(provider, model, messages)

    def health(self) -> dict[str, str]:
        return provider_health()

    def test_provider(self, provider: str, model: str = None) -> dict:
        return test_provider(provider, model)


llm = LLMService()
