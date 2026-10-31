"""
AI-SWAT+ FastAPI Backend
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from db import init_db
from services.llm_service import PROVIDERS, PROVIDER_LABELS, PROVIDER_MODELS, get_ai_status, llm
from services.swat_service import swat

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI-SWAT+ Model API",
    version="0.4.0",
    description="SWAT+ API with farmer UX and Ollama/cloud LLM integration",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
config.ensure_data_dirs()

from routers import chat, data, farms, gis, interact, scenarios, simulate, swat, swat_editor, system

app.include_router(farms.router)
app.include_router(swat.router)
app.include_router(swat_editor.router)
app.include_router(data.router)
app.include_router(simulate.router)
app.include_router(scenarios.router)
app.include_router(chat.router)
app.include_router(system.router)
app.include_router(gis.router)
app.include_router(interact.router)

if not config.SWAT_API_ONLY:
    from routers import agent

    app.include_router(agent.router)


@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "swat": swat.engine_status(),
        "ai": get_ai_status(),
        "api_only": config.SWAT_API_ONLY,
        "data_root": str(config.DATA_ROOT),
    }
