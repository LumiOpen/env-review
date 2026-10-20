"""Count reviewed discovery outputs without assigning labels to unknown cases."""
from __future__ import annotations

from collections import Counter

STATUSES = {"confirmed", "behavior_only", "candidate", "disputed", "rejected", "fixed"}


def summarize_run(run_id: str, task_ids: list[str], candidate_ids: list[str],
                  adjudications: list[dict]) -> dict:
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Candidate IDs must be unique within a run")
    reviewed = {}
    for verdict in adjudications:
        if verdict["run_id"] != run_id:
            continue
        candidate_id = verdict["candidate_id"]
        if candidate_id not in candidate_ids or candidate_id in reviewed:
            raise ValueError(f"Unknown or duplicate adjudication: {run_id}/{candidate_id}")
        if verdict["decision"] not in STATUSES:
            raise ValueError(f"Unknown adjudication decision: {verdict['decision']}")
        reviewed[candidate_id] = verdict
    return {
        "run_id": run_id, "inspected_task_count": len(set(task_ids)),
        "candidate_count": len(candidate_ids), "reviewed_count": len(reviewed),
        "unreviewed_count": len(candidate_ids) - len(reviewed),
        "decisions": dict(sorted(Counter(v["decision"] for v in reviewed.values()).items())),
        "matched_confirmed_defect_ids": sorted({case for v in reviewed.values()
            if v["decision"] in {"confirmed", "fixed"} for case in v.get("case_ids", [])}),
        "task_false_positive_rate": None, "recall": None,
        "metric_limits": "Discovery reference set is incomplete; unflagged tasks are unlabeled. "
                         "Different scopes and selected samples do not support a method ranking.",
    }
