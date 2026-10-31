#!/usr/bin/env bash
# Re-run Exp 1 after the nitrogen-cap fix (2026-08-06).
#
# Why: `evaluate_monthly_i` defaulted to max_n=400 while MonthlySwatEnv ran uncapped, so every
# open-loop row -- and the CMA-ES objective itself -- solved a different problem than PPO. The
# cap was worth +1,372 $/ha to the open-loop row; `policy - fixed` goes +377 -> -995 once the
# objectives match. See runs/archive/capped_*/README.md.
#
# Run order is the locked one: foresight gate -> controller -> irrigation.
#
#   bash scripts/rerun_exp1.sh                # lambda_n = 0 correction
#   NO3_PRICE=8  OUT_TAG=n8  bash scripts/rerun_exp1.sh
#
# Long runs must be detached or the harness reaps the process group at ~30 min:
#   perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/rerun_exp1.sh
#
# Stage checkpoints are config-keyed, so an interrupted run resumes exactly where it stopped
# and a different lambda can never resume into this one.
set -uo pipefail
cd "$(dirname "$0")/.."

NO3_PRICE="${NO3_PRICE:-0.0}"
OUT_TAG="${OUT_TAG:-}"
BUDGET="${BUDGET:-300000}"
PPO_SEEDS="${PPO_SEEDS:-3}"
N_ENVS="${N_ENVS:-4}"
# The controller is a 3-parameter fit: the archived run is within 0.01 % of its final value
# by eval 217 of 504, so 2200 (220 evals) is convergence, not a corner cut.
GATE_BUDGET="${GATE_BUDGET:-2200}"
# Dominates ceiling cost: one oracle optimisation per window, 15 windows.
PER_WINDOW_BUDGET="${PER_WINDOW_BUDGET:-2000}"
# SKIP_CEILING=1 reuses an existing runs/exp1_ceiling.json instead of re-searching it.

suffix=""
[ -n "$OUT_TAG" ] && suffix="_${OUT_TAG}"
LOG="runs/rerun_exp1${suffix}.log"
mkdir -p runs
: > "$LOG"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "host=$(hostname)  cores=$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
log "git=$(git rev-parse --short HEAD 2>/dev/null || echo none)"
log "no3_price=$NO3_PRICE  budget=$BUDGET  ppo_seeds=$PPO_SEEDS  n_envs=$N_ENVS"

# Guard: the cap fix must be in place, or this reproduces the bug it exists to fix.
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

if [ "${SKIP_CEILING:-0}" = "1" ]; then
    log "=== 1/3 foresight gate: SKIPPED (SKIP_CEILING=1) ==="
else
    log "=== 1/3 foresight gate (exp1_ceiling) ==="
    uv run python -m swat_gym.experiments.exp1_ceiling \
        --budget "$GATE_BUDGET" --per-window-budget "$PER_WINDOW_BUDGET" \
        ${OUT_TAG:+--out "runs/exp1_ceiling${suffix}.json"} >> "$LOG" 2>&1
    log "ceiling exit=$?"
fi

log "=== 2/3 feedback controller (exp1_controller) ==="
# --no3-price must match the irrigation arm: the controller is a policy-class row in the same
# frontier, so optimising it at a different nitrate price makes the comparison meaningless.
uv run python -m swat_gym.experiments.exp1_controller \
    --budget "$GATE_BUDGET" --no3-price "$NO3_PRICE" \
    ${OUT_TAG:+--out "runs/exp1_controller${suffix}.json"} >> "$LOG" 2>&1
log "controller exit=$?"

log "=== 3/3 irrigation (CMA re-optimised uncapped + PPO seeds + frozen) ==="
uv run python -m swat_gym.experiments.exp1_irrigation \
    --budget "$BUDGET" --ppo-seeds "$PPO_SEEDS" --n-envs "$N_ENVS" \
    --no3-price "$NO3_PRICE" \
    ${OUT_TAG:+--out "runs/exp1_irrigation${suffix}.json"} >> "$LOG" 2>&1
log "irrigation exit=$?"

log "=== done ==="
touch "runs/RERUN_EXP1${suffix}_COMPLETE"
