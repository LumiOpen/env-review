#!/usr/bin/env bash
#SBATCH --job-name=mimo-code-fixture-inspect
#SBATCH --partition=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_review/logs/code_fixture_inspect-%j.out
#SBATCH --error=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_review/logs/code_fixture_inspect-%j.err

set -euo pipefail

# Inspect a stopped container only. No task code, image entrypoint, or test runs.
IMAGE='docker.io/xiaomimimo/mimo-v2.6-rl-oss@sha256:88326a734ec3abb1fa9d44744796f819880f4801a74b940965d488ca69fd8b24'
ROOT='/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26'
OUT="$ROOT/research/mimo/code_review/image_inspection/${SLURM_JOB_ID:?run through sbatch}"
mkdir -p "$OUT/files"

if [[ "${SLURM_JOB_PARTITION:-}" != 'amd-tw-verification' ]]; then
  echo 'Required Slurm partition: amd-tw-verification' >&2
  exit 2
fi
if ! timeout 20 docker version --format '{{.Server.Version}}' > "$OUT/docker_server_version.txt" 2> "$OUT/docker_check_error.txt"; then
  echo 'Docker daemon unavailable on compute node; no image pull attempted' >&2
  exit 3
fi

DOCKER_STORAGE="$(docker info --format '{{.DockerRootDir}}')"
df -Pk "$DOCKER_STORAGE" > "$OUT/docker_storage.txt"
AVAILABLE_KB="$(awk 'NR==2 {print $4}' "$OUT/docker_storage.txt")"
if [[ "$AVAILABLE_KB" -lt 20971520 ]]; then
  echo 'Less than 20 GiB available in Docker storage; no pull attempted' >&2
  exit 4
fi

# The image reference is an immutable digest. Pull is bounded inside the job.
timeout 780 docker pull "$IMAGE" > "$OUT/pull.log" 2>&1
docker image inspect "$IMAGE" --format '{{json .RepoDigests}}' > "$OUT/repo_digests.json"

CID=''
cleanup() {
  if [[ -n "$CID" ]]; then
    docker rm -f "$CID" > /dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# No bind mounts, host socket, home mount, or container start. The entrypoint is
# overridden defensively even though docker create does not execute it.
CID="$(docker create --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 4g --cpus 2 \
  --entrypoint /bin/true "$IMAGE")"

paths=(
  'pytago/tests/test_core.py'
  'examples/bitwisenot.py'
  'examples/bitwisenot.go'
  'pyproject.toml'
  'setup.py'
  '.git/HEAD'
  '.git/packed-refs'
  '.git/refs/heads/main'
  '.git/refs/heads/master'
)

for rel in "${paths[@]}"; do
  dest="$OUT/files/$rel"
  mkdir -p "$(dirname "$dest")"
  if docker cp "$CID:/testbed/$rel" "$dest" > /dev/null 2> "$OUT/copy_error.tmp"; then
    printf 'present\t%s\n' "$rel" >> "$OUT/path_status.tsv"
  else
    printf 'missing\t%s\n' "$rel" >> "$OUT/path_status.tsv"
    rm -f "$dest"
  fi
done
rm -f "$OUT/copy_error.tmp"

python - "$OUT" "$IMAGE" <<'PY'
import hashlib
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
files = []
for line in (out / 'path_status.tsv').read_text().splitlines():
    status, rel = line.split('\t', 1)
    path = out / 'files' / rel
    files.append({
        'path': f'/testbed/{rel}',
        'status': status,
        'size_bytes': path.stat().st_size if status == 'present' else None,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if status == 'present' else None,
    })
report = {
    'image': sys.argv[2],
    'job_id': out.name,
    'method': 'docker pull by digest; docker create stopped, read-only, network none, no mounts; docker cp selected files',
    'files': files,
}
(out / 'inspection.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'output': str(out), 'files': files}, indent=2))
PY
