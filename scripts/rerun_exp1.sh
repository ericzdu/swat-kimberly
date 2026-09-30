#!/usr/bin/env bash
# Full Exp 1 pipeline: foresight gate -> controller -> grower rule -> irrigation.
#
#   bash scripts/rerun_exp1.sh                # lambda_n = 0
#   NO3_PRICE=8  OUT_TAG=n8  bash scripts/rerun_exp1.sh
#
# Detach long runs (harness reaps at ~30 min):
#   perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/rerun_exp1.sh
#
# Checkpoints are config-keyed, so interrupted runs resume safely.
set -uo pipefail
cd "$(dirname "$0")/.."

NO3_PRICE="${NO3_PRICE:-0.0}"
OUT_TAG="${OUT_TAG:-}"
BUDGET="${BUDGET:-300000}"
PPO_SEEDS="${PPO_SEEDS:-3}"
N_ENVS="${N_ENVS:-4}"
# 3-param controller converges by ~220 evals.
GATE_BUDGET="${GATE_BUDGET:-2200}"
GROWER_EVALS="${GROWER_EVALS:-220}"
PER_WINDOW_BUDGET="${PER_WINDOW_BUDGET:-2000}"
# Ceiling is lambda_n-independent: reused if runs/exp1_ceiling.json exists.
# SKIP_CEILING=0 forces a rerun; SKIP_CEILING=1 always skips.

suffix=""
[ -n "$OUT_TAG" ] && suffix="_${OUT_TAG}"
LOG="runs/rerun_exp1${suffix}.log"
mkdir -p runs
: > "$LOG"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "host=$(hostname)  cores=$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
log "git=$(git rev-parse --short HEAD 2>/dev/null || echo none)"
log "no3_price=$NO3_PRICE  budget=$BUDGET  ppo_seeds=$PPO_SEEDS  n_envs=$N_ENVS"

# Preflight: objective parity and nesting gates.
log "=== preflight: path-equivalence + max_n signature tests ==="
uv run pytest -q \
  "src/swat_gym/tests/test_monthly.py::test_openloop_and_policy_paths_agree_on_identical_plan" \
  "src/swat_gym/tests/test_monthly.py::test_experiment_scorers_require_explicit_max_n" \
  "src/swat_gym/tests/test_monthly.py::test_default_plan_nests_measured_nitrogen" \
  "src/swat_gym/tests/test_monthly.py::test_generated_arms_are_nitrogen_matched_to_measured" \
  "src/swat_gym/tests/test_monthly.py::test_monthly_default_irrigation_within_1pct_of_measured" \
  >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    log "PREFLIGHT FAILED -- open-loop and policy paths disagree. Aborting."
    exit 1
fi
log "preflight ok"

if [ "${SKIP_CEILING:-auto}" = "1" ]; then
    log "=== 1/3 foresight gate: SKIPPED (SKIP_CEILING=1) ==="
elif [ "${SKIP_CEILING:-auto}" = "auto" ] && [ -f runs/exp1_ceiling.json ]; then
    log "=== 1/3 foresight gate: reusing runs/exp1_ceiling.json (lambda_n-independent) ==="
else
    log "=== 1/3 foresight gate (exp1_ceiling) ==="
    uv run python -m swat_gym.experiments.exp1_ceiling \
        --budget "$GATE_BUDGET" --per-window-budget "$PER_WINDOW_BUDGET" >> "$LOG" 2>&1
    log "ceiling exit=$?"
fi

# Stop before PPO if the foresight gate failed.
if [ -f runs/exp1_ceiling.json ]; then
    gate=$(uv run python -c "import json;print(json.load(open('runs/exp1_ceiling.json'))['gate_pass'])" 2>/dev/null)
    log "gate_pass=$gate"
    if [ "$gate" != "True" ] && [ "${FORCE_PPO:-0}" != "1" ]; then
        log "FORESIGHT GATE FAILED -- there is nothing to adapt to above the noise floor."
        log "Stopping before PPO. Write the bounded null, or set FORCE_PPO=1 deliberately."
        exit 2
    fi
fi

log "=== 2/3 feedback controller (exp1_controller) ==="
# --no3-price must match the irrigation arm.
uv run python -m swat_gym.experiments.exp1_controller \
    --budget "$GATE_BUDGET" --no3-price "$NO3_PRICE" \
    ${OUT_TAG:+--out "runs/exp1_controller${suffix}.json"} >> "$LOG" 2>&1
log "controller exit=$?"

log "=== 2b/3 grower rule (exp1_grower_rule) ==="
# Tagged runs reuse the untagged fit and only re-score. Exit 3 = failed rule 5 gate.
if [ -n "$OUT_TAG" ] && [ -f runs/exp1_grower_rule.json ]; then
    uv run python -m swat_gym.experiments.exp1_grower_rule \
        --from-fit runs/exp1_grower_rule.json --no3-price "$NO3_PRICE" \
        --out "runs/exp1_grower_rule${suffix}.json" >> "$LOG" 2>&1
else
    uv run python -m swat_gym.experiments.exp1_grower_rule \
        --evals "$GROWER_EVALS" --no3-price "$NO3_PRICE" \
        ${OUT_TAG:+--out "runs/exp1_grower_rule${suffix}.json"} >> "$LOG" 2>&1
fi
log "grower rule exit=$?"

log "=== 3/3 irrigation (CMA re-optimised uncapped + PPO seeds + frozen) ==="
uv run python -m swat_gym.experiments.exp1_irrigation \
    --budget "$BUDGET" --ppo-seeds "$PPO_SEEDS" --n-envs "$N_ENVS" \
    --no3-price "$NO3_PRICE" \
    ${OUT_TAG:+--out "runs/exp1_irrigation${suffix}.json"} >> "$LOG" 2>&1
log "irrigation exit=$?"

log "=== done ==="
touch "runs/RERUN_EXP1${suffix}_COMPLETE"
