#!/bin/bash
#SBATCH --job-name=rlaudit-prime
#SBATCH --partition=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src"
uv run --no-project --python "$(command -v python)" \
  --with verifiers==0.3.0 --with datasets==4.3.0 --with pyarrow==24.0.0 \
  python -B scripts/audit_collection.py \
  examples/prime_reverse_text.json examples/prime_countdown.json examples/prime_wordle.json "$@"
