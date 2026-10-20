"""Independent bounded review of two completed reverse-text probes.

Run on amd-tw-verification. Reads only the frozen fixture and completed probe
results; it neither imports nor modifies the pinned environment source.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "research/prime/data/reverse_rows.json"
RUN = ROOT / "runs/prime-v1/prime-reverse-text"
OUTPUT = ROOT / "research/prime/review/reverse_findings.json"


def lcs_bitset(left: str, right: str) -> int:
    """Compute true LCS length using bit-parallel row updates."""
    masks: dict[str, int] = {}
    for index, character in enumerate(right):
        masks[character] = masks.get(character, 0) | (1 << index)
    state = 0
    for character in left:
        common = masks.get(character, 0) | state
        shifted = (state << 1) | 1
        state = common & ~(common - shifted)
    return state.bit_count()


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or os.environ.get("SLURM_JOB_PARTITION") != "amd-tw-verification":
        raise SystemExit("Run on amd-tw-verification")
    assert lcs_bitset("abc", "ac") == 2
    assert lcs_bitset("abc", "def") == 0
    assert lcs_bitset("ABCBDAB", "BDCABA") == 4

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected = {row["dataset_index"]: row for row in fixture["selected"]}
    row49 = selected[49]
    result49_path = next((RUN / "probes/exact-reversal-49").glob("*/reference/result.json"))
    result49 = json.loads(result49_path.read_text(encoding="utf-8"))
    input49 = json.loads((result49_path.parent / "input.json").read_text(encoding="utf-8"))
    expected49 = row49["source_prompt"][::-1]
    parsed49 = result49["details"]["parsed_answer"]
    assert row49["source_prompt"].endswith(" ")
    assert expected49 == row49["answer"] == result49["details"]["expected_answer"]
    assert input49["task"]["prompt"] == row49["source_prompt"]
    assert input49["case"]["input"]["completion"] == f"<reversed_text>{expected49}</reversed_text>"
    assert parsed49 == expected49[1:]
    predicted49 = 2 * len(parsed49) / (len(parsed49) + len(expected49))
    assert abs(result49["reward"] - predicted49) < 1e-12

    metric_case = fixture["metric_case"]
    result_metric_path = next((RUN / "probes/declared-lcs-metric").glob("*/variant/result.json"))
    result_metric = json.loads(result_metric_path.read_text(encoding="utf-8"))
    actual_lcs = lcs_bitset(metric_case["candidate_answer"], metric_case["answer"])
    assert len(metric_case["candidate_answer"]) == len(metric_case["answer"]) == 41
    assert actual_lcs == 15
    lcs_ratio = 2 * actual_lcs / (len(metric_case["candidate_answer"]) + len(metric_case["answer"]))
    matcher_ratio = SequenceMatcher(None, metric_case["candidate_answer"], metric_case["answer"]).ratio()
    assert abs(lcs_ratio - 0.36585365853658536) < 1e-12
    assert abs(matcher_ratio - result_metric["reward"]) < 1e-12

    findings = [json.loads(line) for line in (RUN / "findings.jsonl").read_text().splitlines()]
    by_probe = {finding["probe_id"]: finding for finding in findings}
    record = {
        "review_scope": "Two selected source-rubric component probes; no prevalence or rollout claim",
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "exact_reversal_row49": {
            "finding_id": by_probe["exact-reversal-49"]["finding_id"],
            "source_dataset_index": 49,
            "prompt_ends_with_space": True,
            "source_gold_equals_character_reversal": True,
            "submitted_answer_equals_source_gold": True,
            "parsed_answer_loses_one_leading_space": True,
            "gold_length": len(expected49),
            "parsed_length": len(parsed49),
            "observed_reward": result49["reward"],
            "expected_exact_reward": 1.0,
            "result_path": str(result49_path.relative_to(ROOT)),
        },
        "declared_lcs_metric": {
            "finding_id": by_probe["declared-lcs-metric"]["finding_id"],
            "source_dataset_index": 0,
            "string_lengths": [41, 41],
            "independent_bitset_lcs_length": actual_lcs,
            "true_lcs_ratio": lcs_ratio,
            "sequence_matcher_ratio": matcher_ratio,
            "observed_reward": result_metric["reward"],
            "result_path": str(result_metric_path.relative_to(ROOT)),
        },
    }
    OUTPUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
