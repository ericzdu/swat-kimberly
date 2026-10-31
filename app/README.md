# AI-SWAT+

AI-powered hydrological decision support for growers and farmers. Chat naturally about irrigation, fertilizer, and yield — AI-SWAT+ runs SWAT+ simulations and translates the results into actionable recommendations.

## Tech Stack

- **Backend**: FastAPI + LangChain + pySWATPlus
- **Frontend**: Next.js 15 + shadcn/ui + Tailwind CSS 4
- **LLM**: Ollama (local) with Groq/OpenAI fallback
- **Container**: Docker + Docker Compose

## Quick Start

### 1. Clone and setup

```bash
# Backend
cd backend
uv sync
uv run fastapi dev main.py

# Frontend (new terminal)
cd frontend
pnpm install
pnpm dev
```

### 2. Install Ollama

```bash
# Install Ollama (https://ollama.com)
ollama pull llama3.1:8b
```

### 3. Environment variables (optional)

```bash
# For cloud LLM fallback
export GROQ_API_KEY=your_key
export OPENAI_API_KEY=your_key
```

### 4. Open browser

```
http://localhost:3000
```

## Project Structure

```
backend/
  main.py              # FastAPI entry
  agents/              # LangChain farm agent
  services/            # LLM and SWAT services
  routers/             # API endpoints
  db/                  # SQLAlchemy models

frontend/
  app/                 # Next.js pages
  components/          # UI components
  lib/                 # API client

docker/
  docker-compose.yml   # Full stack deployment
```

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/chat` | Chat with AI advisor |
| `POST /api/simulate` | Run SWAT+ simulation |
| `GET /api/farms` | Farm CRUD |
| `GET /api/system/health` | LLM provider status |

## Build with Docker

```bash
cd docker
docker compose up -d
```

## Development Status

**Phase 1 POC** — Core backend and UI scaffolded. LLM integration and SWAT+ simulation are wired but may need real model files for full testing.

## Next Steps

1. Load actual SWAT+ TxtInOut folder for your watershed
2. Calibrate with observed flow/soil data
3. Connect NASA Harvest satellite data for real-time weather
4. Deploy to cloud for multi-farm SaaS
