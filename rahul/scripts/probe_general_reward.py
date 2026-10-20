#!/usr/bin/env python3
"""Offline microprobe of a pinned General scorer, not an end-to-end task run.

Run through Slurm on amd-tw-verification. Extract only the reviewed _grade_sc
function from the saved source, run the task's actual source-data check against
copies of its two published databases, and substitute controlled judge scores.
No model endpoint, task solver, container image, or external grading package is
used. This tests aggregation mechanics, not how a judge scores a real answer.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
TASK = "s3k_0000_accounting_audit_tax_en_t1_rl_008"
SNAPSHOT = ROOT / "research/mimo/general_review/snapshots" / TASK
FIXTURES = ROOT / "research/mimo/probes/fixtures" / TASK


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Submit this probe through Slurm, not on the login node.")
    if os.environ.get("SLURM_JOB_PARTITION") != "amd-tw-verification":
        raise SystemExit("Required partition: amd-tw-verification")

    source_path = SNAPSHOT / "verify.py"
    meta_path = SNAPSHOT / "verifier_meta.json"
    meta = json.loads(meta_path.read_text())
    assert not meta.get("src_protect"), "This probe does not simulate protection helpers."
    assert all(item["method"] in {"llm", "rule"} for item in meta["items"])
    assert not any(item.get("gate") for item in meta["items"])
    nodes = [
        node for node in ast.parse(source_path.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "_grade_sc"
    ]
    assert len(nodes) == 1
    aggregation = compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec")

    rule_namespace = {}
    # This task's reviewed check_code contains only pathlib/sqlite3 imports and
    # a function reading fixed rows from the provided databases.
    exec(compile(meta["check_code"], str(meta_path) + ":check_code", "exec"), rule_namespace)

    class JudgeUnavailable(Exception):
        pass

    observations = []
    with tempfile.TemporaryDirectory(prefix="mimo-general-probe-") as temporary:
        work = Path(temporary)
        workspace = work / "workspace"
        workspace.mkdir()
        shutil.copytree(FIXTURES / "system", work / "system")

        def run_rule(check_code, function_name, ws):
            assert check_code == meta["check_code"]
            return rule_namespace[function_name](ws)

        actual_source_check = run_rule(meta["check_code"], "check_source_data_present", workspace)
        assert actual_source_check["score"] == 1, actual_source_check

        for verdict in (0.0, 0.25, 0.5, 0.75, 1.0, "unavailable"):
            def fake_judge(items, ws, votes=1):
                if verdict == "unavailable":
                    raise JudgeUnavailable("Controlled offline failure")
                return {
                    item["id"]: {"score": verdict, "detail": "Controlled judge substitute"}
                    for item in items
                }

            namespace = {
                "_meta": lambda: meta,
                "_run_rule_sc": run_rule,
                "_run_llm_sc": fake_judge,
                "_JudgeUnavailable": JudgeUnavailable,
                "os": SimpleNamespace(environ={}),
            }
            exec(aggregation, namespace)
            result = namespace["_grade_sc"](workspace)
            if verdict == "unavailable":
                assert result["reward_error"] == "judge_crashed"
            else:
                assert result["score"] == 0.5 + 0.5 * verdict
            observations.append({"controlled_answer_score": verdict, "result": result})

    files = [source_path, meta_path, *sorted((FIXTURES / "system").glob("*/state.db"))]
    report = {
        "task_id": TASK,
        "status": "controlled_aggregation_reproduced",
        "slurm": {
            "job_id": os.environ["SLURM_JOB_ID"],
            "partition": os.environ["SLURM_JOB_PARTITION"],
            "hostname": socket.gethostname(),
        },
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in files},
        "actual_source_check": actual_source_check,
        "observations": observations,
        "interpretation": [
            "For this branch and pristine inputs, raw reward equals 0.5 + 0.5 * answer score.",
            "This increasing affine map preserves within-task ordering of answer scores.",
            "Judge unavailability is returned as reward_error, not the 0.5 baseline.",
        ],
        "limitations": [
            "Judge outputs were substituted; no real answer was graded.",
            "Executed the extracted _grade_sc function, not _grade or the complete runtime.",
            "No image inspection, actual model rollout, or RL training was performed.",
            "External grading package selection, binarization and masking by trainer remain untested.",
            "This establishes aggregation behavior, not an incentive-reversal exploit.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({
        "output": str(args.output),
        "job_id": report["slurm"]["job_id"],
        "cases": len(observations),
        "raw_rewards": [x["result"]["score"] for x in observations],
    }))


if __name__ == "__main__":
    main()
