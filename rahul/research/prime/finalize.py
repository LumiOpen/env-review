"""Summarize the completed Prime pilot without modifying sealed run bundles."""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research/prime"
CLASSIFICATIONS = {
    "fractional-intermediate": ("confirmed_component_false_acceptance", "Fractional intermediate accepted for full reward"),
    "forbidden-exponent": ("confirmed_component_false_acceptance", "Forbidden exponentiation accepted for full reward"),
    "exact-reversal-49": ("confirmed_component_underreward", "Exact reversed answer loses significant whitespace in parser"),
    "declared-lcs-metric": ("confirmed_declared_metric_mismatch", "SequenceMatcher differs from described longest common subsequence metric"),
}


def read(path):
    return json.loads(Path(path).read_text())


def relative(path):
    return str(Path(path).relative_to(ROOT))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    args = parser.parse_args()
    collection = args.collection.resolve()
    summary = read(collection / "summary.json")
    if summary["status"] != "completed":
        raise SystemExit("Collection is not complete")
    findings, results = [], []
    for item in summary["results"]:
        if not item["comparison"]["reproduced"]:
            raise ValueError("A frozen replay did not reproduce")
        run = Path(item["run"])
        report, probes = read(run / "report.json"), read(run / "probes.json")
        by_probe = {probe["probe_id"]: probe for probe in probes["results"]}
        for finding in report["findings"]:
            category, title = CLASSIFICATIONS[finding["probe_id"]]
            proof = by_probe[finding["probe_id"]]
            findings.append({
                "pipeline_finding_id": finding["finding_id"], "pipeline_status": finding["status"],
                "reviewed_status": category, "title": title, "task_id": finding["task_id"],
                "environment": report["declared_provenance"]["environment"],
                "probe_id": finding["probe_id"], "run": relative(run),
                "expected_values": proof["relation"]["values"], "observed_values": proof["scores"],
                "observations": [{"case_id": case["case_id"], "reward": case["reward"],
                                  "details": case["details"], "result_path": relative(case["result_path"])}
                                 for case in proof["observations"]],
                "independent_review": ("research/prime/review/reverse_findings.json"
                                       if "reverse" in item["name"] else "research/prime/review/verify_countdown.55676.out"),
                "limits": ["Reviewed source component only; no agent rollout, prevalence estimate or training-impact demonstration."],
            })
        results.append({"name": item["name"], "run": relative(run), "replay": relative(item["replay"]),
                        "task_count": report["task_count"], "finding_counts": report["finding_counts"],
                        "case_count": probes["coverage"]["configured_cases"],
                        "probe_relations": len(probes["results"]), "integrity": item["integrity"],
                        "fingerprint": report["fingerprint"], "semantic_sha256": report["semantic_sha256"],
                        "comparison": item["comparison"]})
    wordle = read(collection / "prime-wordle/probes.json")
    duplicate = next(p for p in wordle["results"] if p["probe_id"] == "duplicate-letter-replay")
    marks = duplicate["observations"][0]["details"]["game"]["guesses"][0]["marks"]
    expected_marks = ["correct", "present", "absent", "absent", "correct"]
    if marks != expected_marks:
        raise ValueError("Wordle duplicate-letter example differs from independent expected marks")
    write(BASE / "review/wordle_findings.json", {
        "status": "no_concern_in_selected_cases", "selected_targets": ["abbey", "apple"],
        "cases": 14, "duplicate_example": {"answer": "apple", "guess": "allee",
                                           "expected_marks": expected_marks, "observed_marks": marks},
        "limits": "Direct state/tool/rubric replay only; not a full agent rollout or exhaustive feedback test.",
    })
    write(BASE / "reviewed_findings.json", {"schema_version": "rlaudit.review/v1", "findings": findings,
                                           "note": "Independent classifications supplement unchanged sealed automatic candidate reports."})
    write(BASE / "validation.json", {
        "status": "completed", "collection": relative(collection), "audit_job_id": 55684,
        "unit_tests": {"count": 56, "status": "passed", "job_id": 55683, "log": "research/prime/tests-55683.log"},
        "partition": "amd-tw-verification", "gpus": 0, "model_calls": 0, "paid_judge_calls": 0,
        "task_rows": sum(r["task_count"] for r in results), "cases_per_pass": sum(r["case_count"] for r in results),
        "reviewed_findings": len(findings), "all_replays_reproduced": True, "results": results,
        "runtime_pins": {"verifiers": "0.3.0", "datasets": "4.3.0", "pyarrow": "24.0.0"},
        "local_file_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for pattern in ("examples/prime_*.json", "examples/drivers/prime_*.py")
                              for p in sorted(ROOT.glob(pattern))},
        "limits": ["Source component evidence only, not model performance or learned exploitation.",
                   "Selected cases are purposive and cannot estimate environment or Hub defect prevalence."],
    })
    print(json.dumps({"status": "completed", "task_rows": sum(r["task_count"] for r in results),
                      "cases_per_pass": sum(r["case_count"] for r in results), "reviewed_findings": len(findings)}))


if __name__ == "__main__":
    main()
