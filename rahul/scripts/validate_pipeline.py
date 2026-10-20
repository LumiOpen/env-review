#!/usr/bin/env python3
"""End-to-end audit and replay checks; execute only in a Slurm compute job.

Use an isolated environment containing pyarrow==24.0.0, python-docx==1.2.0 and
lxml==5.4.0. No dataset downloads, Docker pulls, model calls, or training.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from rlaudit.cli import main as cli
from rlaudit.pipeline import compare, execute, require_compute
from rlaudit.snapshot import verify, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_compute()
    root = Path(__file__).resolve().parents[1]
    base = args.output.resolve()
    if base.exists():
        raise SystemExit("Choose a fresh validation output directory")
    base.mkdir(parents=True)
    results = []
    for name, manifest, expected_count in [
        ("toy", "examples/local/pipeline.json", 2),
        ("mimo-general", "examples/mimo_general.json", 1),
        ("mimo-code", "examples/mimo_code.json", 2602),
    ]:
        run = base / name
        report = execute(root / manifest, run)
        assert report["status"] == "completed", report["status"]
        assert report["task_count"] == expected_count
        if name == "mimo-general":
            assert report["probe_results"][0]["scores"] == [1.0, 0.0]
        verified = verify(run)
        replay = base / (name + "-replay")
        with contextlib.redirect_stdout(io.StringIO()):
            status = cli(["replay", str(run), "--output", str(replay), "--backend", "current"])
        assert status == 0, f"{name} replay failed"
        comparison = compare(run, replay)
        assert comparison["reproduced"], comparison
        results.append({"name":name, "run":str(run), "replay":str(replay),
                        "task_count":report["task_count"], "finding_counts":report["finding_counts"],
                        "integrity":verified, "comparison":comparison})
    summary = {"status":"validated", "results":results,
               "scope":"Real local and MiMo data through common runner; frozen-source replay and semantic comparison. General probe is component-only."}
    write_json(base / "validation.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
