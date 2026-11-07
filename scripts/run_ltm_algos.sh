#!/usr/bin/env bash
# Overnight algorithm comparison on Exp 3 (swat_gym.experiments.ltm_algos), then its page.
# Detach (the harness reaps children after ~30 min):
#   perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/run_ltm_algos.sh
cd "$(dirname "$0")/.."
LOG=runs/ltm_algos.log
rm -f runs/ltm_algos_done.log
{
  echo "=== start $(date)"
  uv run python -m swat_gym.experiments.ltm_algos "$@" 2>&1 | grep --line-buffered -v "evals  best\|render_mode"
  echo "=== driver exit ${PIPESTATUS[0]} $(date)"
  uv run python scripts/ltm_leach_decomp.py 2>&1 | tail -6
  uv run python scripts/ltm_algos_report.py 2>&1
  echo "=== report exit $? $(date)"
} > "$LOG"
echo "=== ALL DONE $(date)" > runs/ltm_algos_done.log
