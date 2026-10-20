#!/bin/bash
#SBATCH --job-name=rlaudit-tests
#SBATCH --partition=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00

set -euo pipefail
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
uv run --no-project --python "$(command -v python)" --with pyarrow==24.0.0 --with verifiers==0.3.0 --with datasets==4.3.0 python -B -m unittest discover -s tests -v
