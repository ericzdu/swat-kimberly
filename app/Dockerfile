# syntax=docker/dockerfile:1
# =============================================================================
# AI-SWAT+ API image — self-contained & portable.
#   Stage 1 compiles the SWAT+ rev-62 engine for Linux from source (the repo only
#   ships a Windows .exe, which can't run in a Linux container).
#   Stage 2 is the FastAPI backend with the engine + rev-62 template + demo baked in.
# Build from the PROJECT ROOT:  docker build -t ai-swat-api .
# =============================================================================

# ---------- Stage 1: build the SWAT+ rev-62 Linux engine ----------
FROM debian:bookworm-slim AS engine
RUN apt-get update && apt-get install -y --no-install-recommends \
        gfortran cmake make git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git clone --depth 1 --branch 62.0.0 https://github.com/swat-model/swatplus.git
WORKDIR /build/swatplus
# Project engine patches (engine_patches/*.patch), shared with calibration/model/TxtInOut's
# builds so the app and the calibration run the same engine. lai_reset_on_cut: a hay cut
# (biomass harvest) sets LAI and phuacc to 0 instead of the stock 0.5*HI*eff decline.
COPY engine_patches/ /build/patches/
RUN for p in /build/patches/*.patch; do git apply --verbose "$p"; done
# gfortran_release_linux preset: -O, static libs, NO -ffpe-trap (release is crash-tolerant)
RUN cmake --preset gfortran_release_linux \
    && cmake --build build/release -j"$(nproc)"
# Grab whatever the versioned target was named and normalise it to /opt/swatplus/swatplus.
# pySWATPlus accepts it on Linux as long as it is an executable ELF (od check below).
RUN set -eux; \
    bin="$(find build/release -maxdepth 1 -type f -executable -name 'swatplus*' | head -n1)"; \
    test -n "$bin"; \
    install -D "$bin" /opt/swatplus/swatplus; \
    od -An -tx1 -N4 /opt/swatplus/swatplus | tr -d ' \n' | grep -qi '^7f454c46'

# ---------- Stage 2: FastAPI backend runtime ----------
FROM python:3.11-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin libgdal-dev g++ libgfortran5 curl \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_CONFIG=/usr/bin/gdal-config \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_ROOT=/data \
    SWATPLUS_EXE=/opt/swatplus/swatplus \
    REV62_TEMPLATE=/opt/ai-swat/rev62_template/TxtInOut \
    DEMO_TXTINOUT=/opt/ai-swat/a10_single_hru/a10_single_hru/Scenarios/Default/TxtInOut \
    SWAT_API_ONLY=false

WORKDIR /app
COPY ai-swat/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# backend source
COPY ai-swat/backend/ /app/

# baked assets — kept OUTSIDE /data so the runtime data volume never hides them
COPY rev62_template/ /opt/ai-swat/rev62_template/
COPY a10_single_hru/ /opt/ai-swat/a10_single_hru/
RUN find /opt/ai-swat -iname '*.exe' -delete   # drop bundled Windows engine copies

# the compiled Linux engine
COPY --from=engine /opt/swatplus/swatplus /opt/swatplus/swatplus
RUN chmod +x /opt/swatplus/swatplus \
    && mkdir -p /data/gis /data/farms /data/outputs /data/observed /data/sensitivity /data/db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/farms || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
