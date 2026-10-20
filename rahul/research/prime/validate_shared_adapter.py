"""Compare migrated component evidence with the original reviewed pilot.

Run on compute after scripts/audit_prime.slurm. Engine fingerprints deliberately
differ across the migration; each new run must reproduce its own frozen replay.
"""

import argparse
import json
import math
from pathlib import Path

from rlaudit.pipeline import require_compute
from rlaudit.snapshot import verify


def read(path):
    return json.loads(path.read_text())


def finding_projection(run):
    return sorted((row["finding_id"], row["probe_id"], row["task_id"], row["status"])
                  for line in (run / "findings.jsonl").read_text().splitlines()
                  if line.strip() for row in [json.loads(line)])


def project(run):
    relations, observations = {}, {}
    for relation in read(run / "probes.json")["results"]:
        relations[relation["id"]] = {key: relation.get(key) for key in
            ("status", "scores", "relation_satisfied", "case_ids")}
        for observation in relation["observations"]:
            if observation["status"] != "observed":
                raise ValueError(f"unobserved case: {observation['id']}")
            if observation["id"] in observations:
                raise ValueError("duplicate case ID")
            observations[observation["id"]] = observation
    return relations, observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=Path("runs/prime-v1"))
    parser.add_argument("--collection", type=Path, default=Path("runs/prime-shared-v1"))
    parser.add_argument("--output", type=Path, default=Path("research/prime/shared_adapter_validation.json"))
    args = parser.parse_args()
    require_compute()
    summary = read(args.collection / "summary.json")
    if summary["status"] != "completed":
        raise ValueError("collection did not complete")
    results, disagreements = [], []
    for item in summary["results"]:
        name = item["name"]
        old, new = args.baseline / name, args.collection / name
        integrity = verify(new)
        verify(args.collection / (name + "-replay"))
        old_relations, old_cases = project(old)
        new_relations, new_cases = project(new)
        if old_relations != new_relations or old_cases.keys() != new_cases.keys():
            raise ValueError(f"relation or case inventory changed for {name}")
        for case_id, observation in new_cases.items():
            previous = old_cases[case_id]
            if observation["reward"] != previous["reward"]:
                raise ValueError(f"case reward changed: {case_id}")
            details, old_details = observation["details"], previous["details"]
            if details["rubric_metrics"] != old_details["rubric_metrics"]:
                raise ValueError(f"source metrics changed: {case_id}")
            if "rubric_reward" in old_details and details["rubric_reward"] != old_details["rubric_reward"]:
                raise ValueError(f"weighted source reward changed: {case_id}")
            if "parsed_answer" in old_details and details["parsed_answer"] != old_details["parsed_answer"]:
                raise ValueError(f"source parsed answer changed: {case_id}")
            if "game" in old_details:
                if details["state"]["game"] != old_details["game"]:
                    raise ValueError(f"source game state changed: {case_id}")
                if [call["response"] for call in details["tool_calls"]] != [entry["response"] for entry in old_details["feedback"]]:
                    raise ValueError(f"source tool feedback changed: {case_id}")
            oracle = details.get("oracle")
            if oracle is not None and not math.isclose(observation["reward"], oracle["expected_reward"], abs_tol=1e-12, rel_tol=0):
                disagreements.append({"case_id": case_id, "source_reward": observation["reward"],
                                      "reference_reward": oracle["expected_reward"], "reference_facts": oracle})
        old_findings, new_findings = finding_projection(old), finding_projection(new)
        if old_findings != new_findings:
            raise ValueError(f"finding identities or statuses changed: {name}")
        if item["integrity"]["status"] != "verified" or not item["comparison"]["reproduced"]:
            raise ValueError(f"integrity/replay failed: {name}")
        results.append({"name": name, "task_count": item["task_count"], "case_count": len(new_cases),
                        "relation_count": len(new_relations), "baseline_scores_and_source_metrics_match": True,
                        "finding_ids": [row[0] for row in new_findings],
                        "integrity": integrity, "comparison": item["comparison"]})
    result = {"status": "passed", "partition": "amd-tw-verification", "baseline": str(args.baseline),
              "collection": str(args.collection), "task_count": sum(row["task_count"] for row in results),
              "case_count": sum(row["case_count"] for row in results), "results": results,
              "independent_reference_disagreements": disagreements,
              "limits": ["Cross-engine parity uses case IDs, source scores/metrics, parser/game observations, relation outcomes, and finding IDs; it does not compare changed input fingerprints.",
                         "Each migrated run's replay must match its own fingerprint and semantic digest.",
                         "Model-free component checks; no agent rollout, training, GPU, paid judge, or prevalence estimate."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": result["status"], "cases": result["case_count"],
                      "findings": sum(len(row["finding_ids"]) for row in results),
                      "reference_disagreements": len(disagreements), "output": str(args.output)}))


if __name__ == "__main__":
    main()
