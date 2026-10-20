"""Common audit stages, independent of dataset and grading implementation."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from . import __version__
from .manifest import load, PARTITION
from .snapshot import canonical, freeze, seal, write_json, verify_inputs


def require_compute():
    if not os.environ.get("SLURM_JOB_ID") or os.environ.get("SLURM_JOB_PARTITION") != PARTITION:
        raise ValueError(f"Audit execution requires a Slurm job in {PARTITION}; use --backend slurm")


def stable_finding(finding):
    item = dict(finding)
    identity = {key: item.get(key) for key in ["task_id", "check_id", "probe_id", "status", "summary"]}
    item["finding_id"] = hashlib.sha256(canonical(identity)).hexdigest()[:24]
    return item


def semantic_projection(report):
    """Only comparable results; timing, output paths and worker IDs stay in evidence."""
    return {
        "status": report["status"],
        "fingerprint": report["fingerprint"],
        "tasks_sha256": report["tasks_sha256"],
        "coverage": {key: {k:v for k,v in value.items() if k != "elapsed_seconds"}
                     for key,value in report["coverage"].items()},
        "findings": [{k: f.get(k) for k in ["finding_id", "task_id", "check_id", "probe_id", "status", "evidence_level", "summary"]} for f in report["findings"]],
        "probe_results": report["probe_results"],
    }


def execute(config_path, output):
    require_compute()
    from .adapters import normalize, run_checks
    from .probes import run_probes

    config = load(config_path)
    output = Path(output).resolve()
    config, lock, sources = freeze(config, config_path, output)
    started = datetime.now(timezone.utc).isoformat()
    write_json(output / "state.json", {"status":"running", "started_at":started, "stage":"normalize"})
    try:
        adapted = normalize(config["adapter"], sources)
        tasks = adapted["tasks"]
        if not tasks:
            raise ValueError("Adapter selected no tasks; empty audits are not successful checks")
        if len(tasks) > config["execution"]["max_tasks"]:
            raise ValueError("Normalized task count exceeds execution.max_tasks")
        task_ids = [t["task_id"] for t in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate normalized task IDs; probe targets would be ambiguous")
        task_data = b"".join(canonical(task) + b"\n" for task in tasks)
        (output / "tasks.jsonl").write_bytes(task_data)
        write_json(output / "adapter.json", {key: value for key, value in adapted.items() if key != "tasks"})
        checks = run_checks(tasks, config["checks"])
        write_json(output / "checks.json", checks)
        write_json(output / "state.json", {"status":"running", "started_at":started, "stage":"probes"})
        adapter_findings = [{"check_id":"adapter", "task_id":o.get("task_id"), "status":o.get("status", "observation"),
                             "evidence_level":"static", "summary":o["summary"], "evidence":[o.get("detail", {})],
                             "limitations":["Normalization observation; no grader verdict established."]}
                            for o in adapted.get("observations", [])]
        errors = [f for f in adapter_findings + checks.get("findings", []) if f.get("status") == "error"]
        data_errors = bool(errors)
        # Bad records must not reach a driver, but independent valid tasks can
        # still be audited. A source-wide error with no task ID blocks all.
        blocked = set(task_ids) if any(f.get("task_id") is None for f in errors) else {f["task_id"] for f in errors}
        runnable = []
        skipped_targets = []
        for probe in config["probes"]:
            skipped_targets.extend({"probe_id": probe["id"], "task_id": tid}
                                   for tid in probe["task_ids"] if tid in blocked)
            targets = [tid for tid in probe["task_ids"] if tid not in blocked]
            if targets:
                runnable.append({**probe, "task_ids": targets})
        probes = run_probes(runnable, tasks, sources, output, config["execution"])
        if skipped_targets:
            probes.setdefault("coverage", {}).update({
                "skipped_requested_probes":len(config["probes"]) - len(runnable),
                "skipped_probe_task_targets":skipped_targets,
                "skip_reason":"static_schema_or_contract_errors"})
        write_json(output / "probes.json", probes)
        findings = [stable_finding(f) for f in adapter_findings + checks.get("findings", []) + probes.get("findings", [])]
        findings.sort(key=lambda f: (str(f.get("task_id", "")), str(f.get("check_id", "")), f["finding_id"]))
        (output / "findings.jsonl").write_bytes(b"".join(canonical(f) + b"\n" for f in findings))
        # Probe implementation supplies compact comparable outcomes separately;
        # full process logs and artifacts remain in probes.json and case folders.
        comparable = []
        incomplete = False
        for result in probes.get("results", []):
            status = result.get("status", "unknown")
            if status in {"error", "inconclusive", "budget_exhausted", "skipped"}:
                incomplete = True
            comparable.append({
                key: result.get(key) for key in ["probe_id", "task_id", "status", "scores", "relation_satisfied"]
            })
        verify_inputs(output)
        report = {
            "schema_version":"rlaudit.report/v1", "tool_version":__version__,
            "name":config["name"], "status":("completed_with_data_errors" if data_errors else "completed_with_inconclusive_probes" if incomplete else "completed"),
            "declared_provenance":config.get("provenance", {}),
            "fingerprint":lock["fingerprint"], "tasks_sha256":hashlib.sha256(task_data).hexdigest(),
            "task_count":len(tasks), "finding_counts":dict(Counter(f["status"] for f in findings)),
            "coverage":{"adapter":adapted.get("coverage", {}), "checks":checks.get("coverage", {}),
                        "probes":{**probes.get("coverage", {}),
                                  "probed_task_ids":sorted({r["task_id"] for r in probes.get("results", []) if r.get("status") != "inconclusive"}),
                                  "unprobed_task_ids":sorted(set(task_ids) - {r["task_id"] for r in probes.get("results", []) if r.get("status") != "inconclusive"})}},
            "findings":findings, "probe_results":comparable,
            "limits":["Audit coverage is explicit; skipped checks are not passes.",
                      "A declared paired relation is a supplied oracle, not independently established task validity.",
                      "A component reproduction does not establish total environment reward or training impact."],
            "execution":{"started_at":started, "finished_at":datetime.now(timezone.utc).isoformat(),
                         "slurm_job_id":os.environ["SLURM_JOB_ID"], "partition":PARTITION,
                         "runtime_versions":lock["runtime_versions"]},
        }
        semantic = semantic_projection(report)
        report["semantic_sha256"] = hashlib.sha256(canonical(semantic)).hexdigest()
        write_json(output / "report.json", report)
        write_json(output / "state.json", {"status":report["status"], "started_at":started, "finished_at":report["execution"]["finished_at"]})
        seal(output)
        return report
    except Exception as exc:
        write_json(output / "state.json", {"status":"failed", "started_at":started, "error":f"{type(exc).__name__}: {exc}"})
        # Failed executions preserve evidence without masquerading as passes.
        seal(output)
        raise


def compare(left, right):
    from .snapshot import verify
    verify(left)
    verify(right)
    a = json.loads((Path(left) / "report.json").read_text())
    b = json.loads((Path(right) / "report.json").read_text())
    same_inputs = a["fingerprint"] == b["fingerprint"]
    same_results = a["semantic_sha256"] == b["semantic_sha256"]
    return {"same_fingerprint":same_inputs, "same_semantic_results":same_results,
            "reproduced":same_inputs and same_results,
            "left_semantic_sha256":a["semantic_sha256"], "right_semantic_sha256":b["semantic_sha256"]}
