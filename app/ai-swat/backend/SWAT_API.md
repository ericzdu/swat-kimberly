# SWAT+ Model API

Dockerized FastAPI service powered by **pySWATPlus**. Large data lives on the `/data` volume; the API controls runs and returns JSON summaries.

## Test with a10_single_hru (bundled QSWAT+ project)

```powershell
# SWAT+ 61 binary (matches project rev) is in swatplus_bin/
$env:SWATPLUS_EXE="G:\AI-SWAT+ project\swatplus_bin\swatplus-61.0.2.61-gnu-win_amd64-Rel.exe"
$env:DATA_ROOT="G:\AI-SWAT+ project\data"

cd ai-swat\backend
python scripts/test_a10_single_hru.py          # validate only
python scripts/test_a10_single_hru.py --run    # run 2005-2025 via API service
```

TxtInOut path: `a10_single_hru/a10_single_hru/Scenarios/Default/TxtInOut`

## Quick start

```bash
# 1. Download SWAT+ Linux binary from https://github.com/swat-model/swatplus/releases
#    Place in ./swatplus_bin/swatplus-gnu-lin_x86_64

mkdir -p data/gis data/farms data/outputs data/observed data/db
cp .env.example .env

docker compose up --build
```

Open **http://localhost:3000** for the farmer web app (setup wizard, advisor, results).
API docs: **http://localhost:8000/docs**

### Farmer web app (local dev)

```bash
cd ai-swat/backend && python run_server.py   # port 8000
cd ai-swat/src && npm run dev                 # port 5173, proxies /api
```

### AI integration (Ollama or cloud)

**Option A — Ollama (local, free)**
1. Install [Ollama](https://ollama.com)
2. `ollama pull llama3.2`
3. In the app: **Settings** → Provider: **Ollama** → Test → Save

**Option B — Cloud API (Groq, OpenAI, etc.)**
1. Get an API key from your provider
2. **Settings** → paste key → choose model → Test → Save

The farm advisor uses your saved provider. Agent mode calls SWAT+ tools; if that fails, plain chat is used automatically.

Environment: `OLLAMA_HOST` (default `http://127.0.0.1:11434`) for Docker/remote Ollama.


| Endpoint | Description |
|----------|-------------|
| `GET /api/farms/{id}/readiness` | Data checklist for setup wizard |
| `GET /api/farms/{id}/insights` | Dashboard cards (irrigation, fertilizer, yield) |
| `POST /api/scenarios/run` | Run scenario + plain-language advice |
| `POST /api/data/farms/{id}/txtinout` | Upload QSWAT+ project zip |
| `POST /api/data/farms/{id}/demo` | Load bundled a10 demo farm |

Open **http://localhost:8000/docs**

## Data layout (host → container)

```
data/
  gis/{farm_id}/dem.tif          # copy GIS here
  farms/{farm_id}/TxtInOut/      # SWAT+ project (import or generate)
  observed/{farm_id}/discharge.csv
  outputs/{run_id}/              # archived run outputs
  db/ai_swat.db
```

## Workflow

### 1. Create farm

```bash
curl -X POST http://localhost:8000/api/farms \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Farm","location":"Iowa"}'
```

Auto-creates `txtinout_path` at `/data/farms/{id}/TxtInOut`.

### 2. Load data (files on disk)

Copy TxtInOut or GIS into `data/` then register:

```bash
curl -X POST http://localhost:8000/api/data/farms/{farm_id}/gis \
  -H "Content-Type: application/json" \
  -d '{"dem":"gis/{farm_id}/dem.tif","soil":"gis/{farm_id}/soil.shp"}'
```

Or upload a file:

```bash
curl -X POST "http://localhost:8000/api/data/farms/{farm_id}/upload?layer=dem" \
  -F "file=@dem.tif"
```

### 3. Validate TxtInOut

```bash
curl http://localhost:8000/api/swat/validate/{farm_id}
```

### 4. Run SWAT+ model (pySWATPlus)

```bash
curl -X POST http://localhost:8000/api/swat/run \
  -H "Content-Type: application/json" \
  -d '{
    "farm_id": "YOUR_FARM_ID",
    "begin_date": "01-Jan-2010",
    "end_date": "31-Dec-2015",
    "parameters": [
      {"name": "cn2", "change_type": "pctchg", "value": 5}
    ]
  }'
```

### 5. Poll results

```bash
curl http://localhost:8000/api/swat/runs/{run_id}
```

### 6. Metrics vs observed (PerformanceMetrics)

```bash
curl -X POST http://localhost:8000/api/swat/metrics \
  -H "Content-Type: application/json" \
  -d '{
    "farm_id": "YOUR_FARM_ID",
    "sim_file": "channel_sd_day.txt",
    "obs_file": "observed/{farm_id}/discharge.csv",
    "indicators": ["NSE", "KGE", "RMSE"]
  }'
```

### 7. Sensitivity analysis (SensitivityAnalyzer)

```bash
curl -X POST http://localhost:8000/api/swat/sensitivity \
  -H "Content-Type: application/json" \
  -d '{
    "farm_id": "YOUR_FARM_ID",
    "sample_number": 32,
    "parameters": [
      {"name": "esco", "change_type": "absval", "lower_bound": 0, "upper_bound": 1}
    ]
  }'
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_ROOT` | `/data` | Volume root |
| `SWATPLUS_EXE` | `/opt/swatplus/swatplus-gnu-lin_x86_64` | SWAT+ binary in container |
| `SWATPLUS_BIN_HOST` | `./swatplus_bin` | Host folder mounted read-only |
| `SWAT_ALLOW_MOCK` | `false` | Dev only — fake outputs without SWAT+ |
| `SWAT_API_ONLY` | `true` in Docker | Lean server (no chat/GIS UI routes) |

## pySWATPlus integration

All SWAT+ operations go through `services/pyswat_facade.py`:

- `TxtinoutReader.run_swat()` — model execution
- `DataManager.simulated_timeseries_df()` — time series
- `PerformanceMetrics.indicator_from_file()` — NSE, KGE, RMSE
- `SensitivityAnalyzer` — Sobol sensitivity

## Legacy endpoints

`/api/simulate/*` remains available for UI compatibility.
