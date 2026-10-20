#!/usr/bin/env python3
"""Audit cached MiMo subsets and verify a frozen-source replay on compute."""
import argparse
import contextlib
import io
import json
from pathlib import Path

from rlaudit.cli import main as cli
from rlaudit.pipeline import compare, execute, require_compute
from rlaudit.snapshot import verify, write_json


COUNTS = {"cyber": 1000, "webdev": 2093, "music": 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--subsets", choices=list(COUNTS), nargs="+", default=list(COUNTS))
    args = parser.parse_args()
    require_compute()
    if len(set(args.subsets)) != len(args.subsets):
        parser.error("Select each subset once")
    root = Path(__file__).resolve().parents[1]
    base = args.output.resolve()
    if base.exists():
        raise SystemExit("Choose a fresh output directory")
    base.mkdir(parents=True)
    results = []
    for subset in args.subsets:
        run = base / subset
        replay = base / (subset + "-replay")
        result = {"subset": subset, "run": str(run), "replay": str(replay)}
        try:
            report = execute(root / f"examples/mimo_{subset}.json", run)
            result.update(status=report["status"], task_count=report["task_count"],
                          finding_counts=report["finding_counts"], coverage=report["coverage"],
                          integrity=verify(run))
            if report["task_count"] != COUNTS[subset]:
                raise ValueError(f"Expected {COUNTS[subset]} rows, got {report['task_count']}")
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli(["replay", str(run), "--output", str(replay), "--backend", "current"])
            if code not in (0, 3):
                raise ValueError(f"Replay failed with exit status {code}")
            result["comparison"] = compare(run, replay)
            if not result["comparison"]["reproduced"]:
                raise ValueError("Replay differs from original")
        except Exception as exc:
            # Preserve independent subset results; failed runs keep their state
            # and evidence through the normal pipeline failure handler.
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        results.append(result)
        write_json(base / "summary.json", {"status": "running", "results": results})
    completed = all(item["status"] == "completed" for item in results)
    summary = {
        "status": "completed" if completed else "incomplete",
        "dataset_revision": "e8e81e4945270b6212204bad99de1e598f7fb077",
        "scope": "All rows; static metadata contracts and any explicitly configured component probes.",
        "limits": ["No full environment execution or policy training.",
                   "No container images, website screenshots, visual judges, or ABC/MIDI rendering.",
                   "Completed means the requested operations finished, not that environments are correct."],
        "results": results,
    }
    write_json(base / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "summary": str(base / "summary.json"),
                      "subsets": [{k: r[k] for k in ("subset", "status") } for r in results]}, indent=2))
    return 0 if completed else 3


if __name__ == "__main__":
    raise SystemExit(main())
