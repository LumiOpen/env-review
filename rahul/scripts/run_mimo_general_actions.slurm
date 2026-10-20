#!/bin/bash
#SBATCH --job-name=mimo-gen-actions
#SBATCH --partition=amd-tw-verification
#SBATCH --account=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/general_actions/slurm-%j.out
set -euo pipefail
cd /shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26
python3 scripts/mimo_general_actions.py
