# AI-SWAT+ — Docker deployment

Run the whole app (React UI + FastAPI backend + a real SWAT+ rev-62 engine) on any
machine with Docker. No Windows, no manual SWAT+ install, no host paths.

## Quick start

```bash
docker compose up --build
```

Then open **http://localhost:3000**.

The first build compiles the SWAT+ engine from source (~5–10 min). Later builds are cached.

| Service | Port | What it is |
|---|---|---|
| `swat-web` | http://localhost:3000 | React UI (nginx), proxies `/api` to the backend |
| `swat-api` | http://localhost:8020 | FastAPI + SWAT+ engine |

## What's inside the image

* **SWAT+ rev-62 engine, compiled for Linux** from the official
  `swat-model/swatplus` repo (tag `62.0.0`) using the project's own
  `gfortran_release_linux` CMake preset. The repo only ships a Windows `.exe`,
  which cannot run in a Linux container — so the image builds a native one.
  *Bonus:* the Release preset omits `-ffpe-trap`, so this build does not abort on
  the floating-point edge cases that crash the Windows debug binary.
* **rev-62 project template** (`REV62_TEMPLATE`) — the base every new field is built from.
* **a10 demo project** (`DEMO_TXTINOUT`) — support files for the GIS/Open-Meteo path.

Both asset folders live under `/opt/ai-swat/`, deliberately outside `/data`, so the
runtime volume can never shadow them.

## Configuration

Everything is environment-driven — copy `.env.example` to `.env` and fill in what you need:

```bash
MINIMAX_API_KEY=...        # or OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY
```

Keys are optional at startup — you can also set the provider in the app's **Settings** page.

| Variable | Default in image | Purpose |
|---|---|---|
| `DATA_ROOT` | `/data` | farms, runs, DB (persisted in the `swat-data` volume) |
| `SWATPLUS_EXE` | `/opt/swatplus/swatplus` | the compiled Linux engine |
| `REV62_TEMPLATE` | `/opt/ai-swat/rev62_template/TxtInOut` | base project for new fields |
| `DEMO_TXTINOUT` | `/opt/ai-swat/a10_single_hru/.../TxtInOut` | demo support files |

## Data & persistence

Farms, model runs and the SQLite DB live in the named volume `swat-data`, so they
survive `docker compose down` and image rebuilds.

```bash
docker compose down            # stop, keep data
docker compose down -v         # stop and DELETE all fields/runs
docker volume ls               # find the volume
```

To inspect or back up the data:

```bash
docker compose exec swat-api ls /data/farms
docker run --rm -v ai-swat-project_swat-data:/d -v "$PWD:/out" busybox \
    tar czf /out/swat-data-backup.tar.gz -C /d .
```

## Requirements & limitations

* **Outbound internet** is required when building a field — the backend fetches
  gridMET weather (`thredds.northwestknowledge.net`) and elevation.
* Uncalibrated single-field output stays **directional** — compare scenarios, not absolutes.

## gSSURGO soil in Docker (real, location-specific soil)

The USDA soil dataset ships as a Microsoft Access `.mdb`, which the backend reads
through `pyodbc` — a Windows-only driver. Convert it **once** to SQLite and it works
on every platform, containers included:

```bash
./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb
```

That writes `soils_db/ssurgo.sqlite` (indexed on `MUID`). The conversion itself runs
inside a throwaway Docker container, so you don't need to install anything.
`docker-compose.yml` already mounts `./soils_db` read-only at
`/opt/ai-swat/soils_db`, and the backend picks the file up via `SSURGO_SQLITE`.

Restart the stack and field builds will report the real soil series (e.g. *Portneuf*)
instead of falling back to the template soil:

```bash
docker compose up -d
```

**Without it, nothing breaks** — `soil_service` catches the missing database and the
build continues on the template soil, so fields still build and run. You just get a
generic soil profile rather than the one under your field.

The backend prefers SQLite whenever it's present and falls back to the `.mdb` via
pyodbc on Windows, so both setups keep working from the same code.

## Deploying elsewhere

The images are self-contained, so you can push and run them anywhere:

```bash
docker compose build
docker tag ai-swat-api  <registry>/ai-swat-api:latest
docker tag ai-swat-web  <registry>/ai-swat-web:latest
docker push <registry>/ai-swat-api:latest
docker push <registry>/ai-swat-web:latest
```

For a different host port, change the left side of the port mappings in
`docker-compose.yml` (e.g. `"8080:80"` for the UI).

## Troubleshooting

```bash
docker compose logs -f swat-api      # backend + engine errors
docker compose ps                    # health status
docker compose exec swat-api /opt/swatplus/swatplus --help   # engine sanity check
```

*"No SWAT+ executable"* — the engine stage failed to build; rerun
`docker compose build --no-cache swat-api` and check the compile output.
