#!/usr/bin/env bash
# Convert the USDA "SWAT US SSURGO Soils" MS-Access database to portable SQLite.
#
# WHY: soil_service reads the .mdb through pyodbc + the Microsoft Access driver,
# which exists only on Windows. Converting once to SQLite makes gSSURGO soil work
# everywhere — Linux containers, macOS, CI — with no driver at all.
#
# Runs entirely inside Docker, so no local mdbtools install is needed.
#
#   ./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb [outdir]
#
# Produces <outdir>/ssurgo.sqlite (default outdir: ./soils_db), indexed on MUID.
set -euo pipefail

MDB="${1:?usage: convert_ssurgo.sh <SWAT_US_SSURGO_Soils.mdb> [outdir]}"
OUTDIR="${2:-$(pwd)/soils_db}"
[ -f "$MDB" ] || { echo "No such file: $MDB" >&2; exit 1; }
mkdir -p "$OUTDIR"

SRC_DIR="$(cd "$(dirname "$MDB")" && pwd)"
SRC_FILE="$(basename "$MDB")"

echo "Converting $SRC_FILE -> $OUTDIR/ssurgo.sqlite (a few minutes for the full US dataset)…"

docker run --rm \
  -v "$SRC_DIR:/src:ro" \
  -v "$OUTDIR:/out" \
  debian:bookworm-slim sh -c "
set -e
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq mdbtools sqlite3 >/dev/null 2>&1
cd /out
rm -f ssurgo.sqlite
mdb-schema '/src/$SRC_FILE' sqlite -T SSURGO_Soils > /tmp/schema.sql 2>/dev/null
sqlite3 ssurgo.sqlite < /tmp/schema.sql
{ echo 'PRAGMA synchronous=OFF; PRAGMA journal_mode=MEMORY; BEGIN;'
  mdb-export -I sqlite '/src/$SRC_FILE' SSURGO_Soils
  echo 'COMMIT;'
} | sqlite3 ssurgo.sqlite
sqlite3 ssurgo.sqlite 'CREATE INDEX IF NOT EXISTS idx_muid ON SSURGO_Soils(MUID); VACUUM;'
echo \"rows: \$(sqlite3 ssurgo.sqlite 'SELECT COUNT(*) FROM SSURGO_Soils;')\"
"

echo
echo "Done: $OUTDIR/ssurgo.sqlite"
echo "The backend picks it up automatically (config.SSURGO_SQLITE), or set SSURGO_SQLITE=<path>."
echo "For Docker, docker-compose.yml mounts ./soils_db read-only into the api container."
