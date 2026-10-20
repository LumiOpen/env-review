"""Submit workers without running bulk audit work on the login node."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

from .snapshot import write_json


def submit(config, config_path, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    configuration = dict(config)
    configuration["sources"] = []
    for source in config["sources"]:
        path = Path(config_path).resolve().parent / source["path"]
        if path.is_symlink():
            raise ValueError(f"Symlink source is unsupported: {path}")
        if not path.exists():
            raise ValueError(f"Missing source: {path}")
        if path.is_dir() and output.is_relative_to(path.resolve()):
            raise ValueError("Run output must not be nested inside a directory source")
        configuration["sources"].append({**source, "path":str(path.resolve())})
    job_dir = output.parent / ".rlaudit-jobs" / uuid.uuid4().hex
    job_dir.mkdir(parents=True)
    manifest = job_dir / "pipeline.json"
    write_json(manifest, configuration)
    source_root = Path(__file__).resolve().parents[1]
    command = ["env", "PYTHONDONTWRITEBYTECODE=1", f"PYTHONPATH={source_root}", sys.executable, "-B", "-m", "rlaudit", "_worker", str(manifest), "--output", str(output)]
    if config["execution"]["dependencies"]:
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("Pinned dependency installation needs uv on the submission host")
        prefix = [uv, "run", "--no-project", "--python", sys.executable]
        for name,version in sorted(config["execution"]["dependencies"].items()):
            prefix += ["--with", f"{name}=={version}"]
        command = ["env", "PYTHONDONTWRITEBYTECODE=1", f"PYTHONPATH={source_root}"] + prefix + ["python", "-B", "-m", "rlaudit", "_worker", str(manifest), "--output", str(output)]
    script = job_dir / "worker.sh"
    script.write_text("#!/bin/bash\nset -euo pipefail\nexec " + shlex.join(command) + "\n")
    execution = config["execution"]
    args = ["sbatch", "--parsable", f"--partition={execution['partition']}",
            f"--job-name=rlaudit-{config['name'][:40]}", "--nodes=1", "--ntasks=1",
            f"--cpus-per-task={execution['cpus']}", f"--mem={execution['memory']}",
            f"--time={execution['time_limit']}", f"--output={job_dir}/slurm-%j.log"]
    if execution["gpus"]:
        args.append(f"--gpus={execution['gpus']}")
    completed = subprocess.run(args + [str(script)], text=True, capture_output=True, timeout=30)
    if completed.returncode:
        raise ValueError(f"Slurm submission failed: {completed.stderr.strip()}")
    # Site submission filters can print informational lines before --parsable ID.
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    job_id = lines[-1].split(";", 1)[0] if lines else ""
    if not job_id.isdigit():
        raise ValueError("Slurm returned no parseable job ID; inspect submission logs")
    result = {"status":"submitted", "job_id":job_id, "partition":execution["partition"],
              "output":str(output), "job_directory":str(job_dir), "script":str(script)}
    write_json(job_dir / "submission.json", result)
    return result
