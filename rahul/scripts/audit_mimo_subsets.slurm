#!/bin/bash
#SBATCH --job-name=rlaudit-mimo-other
#SBATCH --partition=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src"
uv run --no-project --python "$(command -v python)" --with pyarrow==24.0.0 python -B scripts/audit_mimo_subsets.py "$@"
