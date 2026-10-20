"""Capture real, pinned reverse-text rows and a bounded independent LCS oracle."""
import hashlib
import json
import os
from pathlib import Path
import random
from difflib import SequenceMatcher
from urllib.request import urlopen


REVISION = "b6dc8a0d8c9f59cbd4b38c490aed11f5a31c8c7f"
SHA256 = "3cff91965e9de35d04a1d9297535bd13f8268aa38201abec97b6a5d94e7dabe2"
URL = f"https://huggingface.co/datasets/PrimeIntellect/Reverse-Text-RL/resolve/{REVISION}/data/train-00000-of-00001.parquet"


def lcs_length(left, right):
    """Standard dynamic program for longest common subsequence, O(m*n)."""
    previous = [0] * (len(right) + 1)
    for a in left:
        current = [0]
        for column, b in enumerate(right, 1):
            current.append(previous[column - 1] + 1 if a == b else max(previous[column], current[-1]))
        previous = current
    return previous[-1]


def main():
    if not os.environ.get("SLURM_JOB_ID") or os.environ.get("SLURM_JOB_PARTITION") != "amd-tw-verification":
        raise SystemExit("Run on a Slurm compute node in amd-tw-verification")
    import pyarrow.parquet as pq
    base = Path(__file__).resolve().parent
    path = base / "reverse_train.parquet"
    if not path.exists():
        with urlopen(URL, timeout=60) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024 or hashlib.sha256(payload).hexdigest() != SHA256:
            raise ValueError("Reverse dataset download size/hash mismatch")
        path.write_bytes(payload)
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Reverse dataset hash mismatch")
    rows = pq.read_table(path).to_pylist()
    if len(rows) != 1000 or any(not isinstance(row.get("prompt"), str) for row in rows):
        raise ValueError("Unexpected pinned dataset schema/count")
    indices = list(range(3))
    edge = next((index for index, row in enumerate(rows) if row["prompt"] != row["prompt"].strip()), None)
    if edge is not None and edge not in indices:
        indices.append(edge)
    selected = [{"dataset_index": index, "source_prompt": rows[index]["prompt"], "answer": rows[index]["prompt"][::-1]}
                for index in indices]
    rng = random.Random(20261020)
    metric_case = None
    for row in selected:
        answer = row["answer"]
        if not 3 <= len(answer) <= 256:
            continue
        for attempt in range(100):
            candidate = list(answer)
            rng.shuffle(candidate)
            candidate = "".join(candidate)
            expected = 2 * lcs_length(candidate, answer) / (len(candidate) + len(answer))
            observed = SequenceMatcher(None, candidate, answer).ratio()
            if abs(expected - observed) >= 0.02:
                metric_case = {**row, "candidate_answer": candidate, "lcs_length": lcs_length(candidate, answer),
                               "expected_lcs_ratio": expected, "sequence_matcher_ratio": observed,
                               "attempt": attempt, "sampling_seed": 20261020}
                break
        if metric_case is not None:
            break
    record = {"dataset": "PrimeIntellect/Reverse-Text-RL", "revision": REVISION, "url": URL,
              "sha256": SHA256, "total_rows": len(rows), "selected": selected,
              "metric_case": metric_case,
              "prompt_edge_counts": {"leading_or_trailing_whitespace": sum(r["prompt"] != r["prompt"].strip() for r in rows),
                                     "length_over_200": sum(len(r["prompt"]) > 200 for r in rows)},
              "limits": "Three prefix rows plus one real whitespace edge row; at most100 deterministic response permutations per row; no prevalence claim."}
    (base / "reverse_rows.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "selected": len(selected), "metric_case_found": metric_case is not None,
                      "metric_scores": None if metric_case is None else [metric_case["expected_lcs_ratio"], metric_case["sequence_matcher_ratio"]]}))


if __name__ == "__main__":
    main()
