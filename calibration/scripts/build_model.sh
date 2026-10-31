#!/usr/bin/env bash
# Rebuild the Kimberly SWAT+ TxtInOut from a clean a10_single_hru template, then
# apply the ports (weather -> soil -> management). Idempotent: always starts fresh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$HOME/Downloads/a10_single_hru/Scenarios/Default/TxtInOut"
TIO="$ROOT/model/TxtInOut"

echo "== reset TxtInOut from template =="
# The engines live inside TxtInOut and the reset wipes it, so rescue them first. Both OS
# families are kept; find_engine picks the native one and ignores the wrong-OS sibling.
# Rev 62.0.0 is current -- the retired 60.5.7 (and its .bak) are deliberately dropped, so a
# rebuilt tree cannot silently fall back to the engine the model is no longer calibrated for.
ENGINES="$(mktemp -d)"
trap 'rm -rf "$ENGINES"' EXIT
for e in swatplus_rev62.0.0 swatplus_62.0.0.linux; do
  [ -f "$TIO/$e" ] || { echo "missing engine $TIO/$e" >&2; exit 1; }
  cp "$TIO/$e" "$ENGINES/"
done

rm -rf "$TIO"
cp -R "$TEMPLATE" "$TIO"
cp "$ENGINES"/swatplus_* "$TIO/"

uv run --with openpyxl python scripts/extract_primary.py   # refresh data/ from the source spreadsheets

echo "== apply ports =="
cd "$ROOT"
uv run python scripts/port_wgn.py
uv run python scripts/port_agrimet.py     # pcp/tmp/slr/hmd/wnd, all measured (AgriMet TWFI)
uv run python scripts/port_soil.py
uv run python scripts/port_management.py
uv run python scripts/port_crops.py
uv run python scripts/port_nutrients.py "$@"   # pass --pet-co only to override the calibration
uv run python scripts/port_reference_params.py   # CN2/OV_N/USLE_P, snow, .gw, basin P block
uv run python scripts/calibrate_petco.py --values 1.0 --apply   # fit pet_co to measured ETos
echo "== build complete =="
