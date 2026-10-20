"""Small CLI for planning, running, verifying and replaying environment audits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .manifest import load
from .snapshot import engine_fingerprint, verify


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def parser():
    root = argparse.ArgumentParser(prog="rlaudit", description=__doc__)
    commands = root.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("plan", help="Validate a manifest without loading task data or executing graders")
    plan.add_argument("manifest", type=Path)
    for name in ["run", "_worker"]:
        run = commands.add_parser(name)
        run.add_argument("manifest", type=Path)
        run.add_argument("--output", required=True, type=Path)
        if name == "run":
            run.add_argument("--backend", choices=["slurm", "current"], default="slurm")
    replay = commands.add_parser("replay", help="Verify a prior run, then rerun its frozen inputs")
    replay.add_argument("run", type=Path)
    replay.add_argument("--output", required=True, type=Path)
    replay.add_argument("--backend", choices=["slurm", "current"], default="slurm")
    for name in ["verify", "report"]:
        command = commands.add_parser(name)
        command.add_argument("run", type=Path)
    comparison = commands.add_parser("compare")
    comparison.add_argument("left", type=Path)
    comparison.add_argument("right", type=Path)
    return root


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        if arguments.action == "plan":
            config = load(arguments.manifest)
            emit({"status":"valid", "name":config["name"], "adapter":config["adapter"],
                  "checks":config["checks"], "probe_count":len(config["probes"]),
                  "source_count":len(config["sources"]), "execution":config["execution"],
                  "note":"Task data and source hashes are checked by the compute worker."})
        elif arguments.action in {"run", "_worker", "replay"}:
            manifest = arguments.manifest if arguments.action != "replay" else arguments.run.resolve() / "pipeline.lock.json"
            if arguments.action == "replay":
                verify(arguments.run)
                previous = json.loads((arguments.run / "inputs.lock.json").read_text())
                if previous["engine_sha256"] != engine_fingerprint()[0]:
                    raise ValueError("Audit engine changed since this run; use the recorded engine with PYTHONPATH=<run>/engine on a compute node")
            config = load(manifest)
            if arguments.action != "_worker" and arguments.backend == "slurm":
                from .slurm import submit
                emit(submit(config, manifest, arguments.output))
            else:
                from .pipeline import execute
                report = execute(manifest, arguments.output)
                emit({key:report[key] for key in ["status", "task_count", "finding_counts", "fingerprint", "semantic_sha256"]})
                if report["status"] != "completed":
                    return 3
        elif arguments.action == "verify":
            emit(verify(arguments.run))
        elif arguments.action == "report":
            verify(arguments.run)
            emit(json.loads((arguments.run / "report.json").read_text()))
        elif arguments.action == "compare":
            from .pipeline import compare
            result = compare(arguments.left, arguments.right)
            emit(result)
            return 0 if result["reproduced"] else 1
        return 0
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print(f"rlaudit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
