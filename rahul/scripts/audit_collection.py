#!/usr/bin/env python3
"""Run independent audit manifests, verifying and replaying each on compute.

The compute job must provide the exact dependencies declared by the manifests.
Use the regular rlaudit CLI for per-manifest Slurm dependency provisioning.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from rlaudit.cli import main as cli
from rlaudit.manifest import load
from rlaudit.pipeline import compare, execute, require_compute
from rlaudit.snapshot import verify, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_compute()
    base = args.output.resolve()
    if base.exists():
        raise SystemExit("Choose a fresh output directory")
    # Validate names before starting so independent runs cannot collide.
    configs = [(path.resolve(), load(path)) for path in args.manifests]
    names = [config["name"] for _, config in configs]
    folders = [folder for name in names for folder in (name, name + "-replay")]
    if len(folders) != len(set(folders)):
        raise SystemExit("Collection names and their replay directories must be unique")
    base.mkdir(parents=True)
    results = []
    for manifest, config in configs:
        name = config["name"]
        run, replay = base / name, base / (name + "-replay")
        result = {"name": name, "manifest": str(manifest), "run": str(run), "replay": str(replay)}
        try:
            report = execute(manifest, run)
            result.update(status=report["status"], task_count=report["task_count"],
                          finding_counts=report["finding_counts"], coverage=report["coverage"],
                          probe_results=report["probe_results"], integrity=verify(run))
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli(["replay", str(run), "--output", str(replay), "--backend", "current"])
            if code not in (0, 3):
                raise ValueError(f"Replay failed with exit status {code}")
            result["comparison"] = compare(run, replay)
            if not result["comparison"]["reproduced"]:
                raise ValueError("Replay differs from original")
        except Exception as exc:
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        results.append(result)
        write_json(base / "summary.json", {"status": "running", "results": results})
    complete = all(result["status"] == "completed" for result in results)
    summary = {"status": "completed" if complete else "incomplete", "results": results,
               "limits": ["Completed operations and reproducibility do not establish environment correctness.",
                          "Consult each report's declared scope, cases, source pins and coverage limits."]}
    write_json(base / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "summary": str(base / "summary.json"),
                      "runs": [{k: r[k] for k in ("name", "status")} for r in results]}, indent=2))
    return 0 if complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
